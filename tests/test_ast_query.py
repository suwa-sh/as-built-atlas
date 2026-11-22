"""ast 抽出器 (コードの構文を読む) と listed 抽出器 (エージェントが足した入口) を、小さな見本のルーティング定義で確かめる。"""

import json
from pathlib import Path

import pytest
import yaml

from abatlas.cli import main as cli_main
from abatlas.enumerate import enumerate_entries
from abatlas.extractors import ast_query, listed
from abatlas.schemas import schema_errors
from abatlas.validate import validate_entry_list

# コードの中でルーティングを定義する画面の見本 (架空)。値は (ファイル, 中身)
ROUTES_TS = """\
import type {RouteRecordRaw} from "vue-router"
import {ORDER_ROUTE} from "../orders/orderTabs"
import {makeAdminRoutes} from "../admin/routes"

const routes: RouteRecordRaw[] = [
    {name: "root", path: "/", redirect: {name: "home"}},
    {
        name: "home",
        path: "/:tenant?/dashboards",
        component: () => import("../dashboards/Dashboard.vue"),
    },
    {path: '/:tenant?/books/:bookId', name: 'books/view', component: () => import("../books/BookView.vue")},
    ORDER_ROUTE,
    ...makeAdminRoutes(),
]
export default routes
"""
ORDER_TABS_TS = """\
export const ORDER_ROUTE = {
    name: "orders/list",
    path: "/:tenant?/orders",
    component: () => import("./Orders.vue"),
}
"""
FILES = {
    "ui/src/routes/routes.ts": ROUTES_TS,
    "ui/src/orders/orderTabs.ts": ORDER_TABS_TS,
    "ui/src/admin/routes.ts": "export function makeAdminRoutes() { return ['users', 'roles'].map(n => ({name: `admin/${n}`, path: `/admin/${n}`})) }\n",
}


def _pair(key: str, hole: str) -> dict:
    return {
        "has": {
            "kind": "pair",
            "all": [
                {"has": {"field": "key", "regex": f"^{key}$"}},
                {"has": {"field": "value", "kind": "string", "pattern": hole}},
            ],
        }
    }


# name と path の両方を持つオブジェクト (書く順は問わない)
ROUTE_RULE = {"kind": "object", "all": [_pair("name", "$NAME"), _pair("path", "$PATH")]}
# routes の配列の直下にある、オブジェクトでない要素 (別のファイルから来る定義、展開)
UNRESOLVED_RULE = {
    "any": [{"kind": "identifier"}, {"kind": "spread_element"}],
    "inside": {"kind": "array", "inside": {"kind": "variable_declarator"}},
}


def _params(**over) -> dict:
    base = {
        "files": "ui/src/routes/**/*.ts",
        "language": "typescript",
        "rule": ROUTE_RULE,
        "fields": {
            "path": "{PATH}",
            "name": "{NAME}",
            "attributes": {"route_name": "{NAME}"},
        },
        "segments": {"drop": [":tenant\\?"]},
        "unresolved": UNRESOLVED_RULE,
    }
    base.update(over)
    return base


@pytest.fixture()
def app(tmp_path: Path) -> Path:
    for rel, text in FILES.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return tmp_path


def _run(module, scope: Path, params: dict, capsys) -> tuple[list[dict], str]:
    capsys.readouterr()
    module.extract(scope, params, "screen")
    cap = capsys.readouterr()
    return [json.loads(line) for line in cap.out.splitlines() if line.strip()], cap.err


def test_every_supported_language_parses():
    """読める言語の一覧は、手で書いた定数。入れてある ast-grep が、その全部を読めることを確かめる。"""
    from ast_grep_py import SgRoot

    for lang in ast_query.SUPPORTED_LANGUAGES:
        assert SgRoot("a", lang).root() is not None, lang


def test_routes_defined_in_code_become_entries(app: Path, capsys):
    recs, err = _run(ast_query, app, _params(), capsys)
    assert all(schema_errors("entry-candidate", r) == [] for r in recs)
    got = {r["id"]: (r["path"], r["name"], r["source"]["line"]) for r in recs}
    assert got == {
        "root": ("/(root)", "root", 6),  # 段が残らない URL (/) は (root) にする
        "dashboards": ("/dashboards", "home", 7),  # 複数行のオブジェクトは、始まりの行
        "books.bookId": (
            "/books/:bookId",
            "books/view",
            12,
        ),  # name と path の順が逆でも、引用符が ' でも取れる
    }
    assert (
        recs[0]["attributes"] == {"route_name": "root"}
        and recs[0]["source"]["file"] == "ui/src/routes/routes.ts"
    ), "出す順は、ファイルの中の順"
    # 静的に読めない定義は、入口にせず、場所を知らせる
    assert "読めなかった参照: ui/src/routes/routes.ts:13: ORDER_ROUTE" in err
    assert "読めなかった参照: ui/src/routes/routes.ts:14: ...makeAdminRoutes()" in err
    assert "entries=3 unresolved=2" in err


def test_id_can_come_from_another_field_and_unquote_can_be_turned_off(
    app: Path, capsys
):
    recs, _ = _run(
        ast_query,
        app,
        _params(fields={"path": "{PATH}", "id": "{NAME}"}, unresolved=None),
        capsys,
    )
    assert sorted(r["id"] for r in recs) == ["books.view", "home", "root"]
    recs, _ = _run(
        ast_query,
        app,
        _params(
            fields={"path": "{stem}/{NAME}", "name": "{NAME} in {file} ({dir})"},
            unquote=False,
            id={"join": "-"},
            unresolved=None,
        ),
        capsys,
    )
    by = {r["id"]: r for r in recs}
    assert (
        by["routes-books-view"]["name"]
        == "'books/view' in ui/src/routes/routes.ts (ui/src/routes)"
        and by["routes-books-view"]["path"] == "/routes/'books/view'"
    )


def test_stops_with_a_reason(app: Path, capsys):
    cases = [
        (_params(files=None), "params.files が無い"),
        (_params(language="vue"), "language 'vue' は読めない。読める言語: bash"),
        (_params(language=None), "language 'None' は読めない"),
        (_params(rule=None), "params.rule が無いか、形が違う"),
        (
            _params(rule={"kind": "no_such_kind_of_node"}),
            "params.rule を ast-grep が受け付けない",
        ),
        (_params(fields={"name": "{NAME}"}), "params.fields.path が無い"),
        (
            _params(fields={"path": "{URL}"}),
            "ui/src/routes/routes.ts:6: fields.path の {URL} に当たる穴 $URL が、一致の中に無い",
        ),
        (_params(files="ui/src/nowhere/*.ts"), "に一致するファイルが scope に無い"),
        (
            _params(
                segments={"replace": [{"pattern": ".*", "with": ""}]},
                id={"replace": [{"pattern": ".*", "with": ""}]},
            ),
            "id が空になった",
        ),
        (
            _params(segments={"drop": [".*"]}),
            "id 'root' が 2 つの一致から出た: ui/src/routes/routes.ts:6 と ui/src/routes/routes.ts:7",
        ),
        (
            _params(segments={"prefix": "a/b"}),
            "segments.prefix ['a/b'] の段に '/' は書けない",
        ),
        (
            _params(unresolved={"kind": "no_such_kind_of_node"}),
            "params.unresolved を ast-grep が受け付けない",
        ),
        (
            _params(unresolved={}),
            "params.unresolved が無いか、形が違う",
        ),  # 空の規則を、書いたつもりで何も探さない設定として通さない
        (
            _params(segments={"strip_prefix": "ui", "drop_last": False}),
            "segments に、使えない項目がある: ['drop_last', 'strip_prefix']",
        ),
    ]
    (app / "extra.ts").write_text(ROUTES_TS, encoding="utf-8")
    with pytest.raises(
        SystemExit
    ) as ex:  # 対象の範囲の外のファイルから、入口を出さない
        ast_query.extract(app / "ui", _params(files="../extra.ts"), "screen")
    assert "が、対象の範囲 (scope) の外のファイルに一致した" in str(ex.value)
    for params, message in cases:
        with pytest.raises(SystemExit) as ex:
            ast_query.extract(
                app, {k: v for k, v in params.items() if v is not None}, "screen"
            )
        assert message in str(ex.value), (message, str(ex.value))
    assert capsys.readouterr().out == "", "止まるときは、候補を 1 件も出さない"
    recs, err = _run(
        ast_query, app, _params(files="ui/src/nowhere/*.ts", allow_empty=True), capsys
    )
    assert recs == [] and "files=0 entries=0" in err
    # 対象のファイルが 1 つも無くても、規則の誤りは見つける
    for over, message in [
        ({"unresolved": {}}, "params.unresolved が無いか、形が違う"),
        (
            {"rule": {"kind": "no_such_kind_of_node"}},
            "params.rule を ast-grep が受け付けない",
        ),
        ({"segments": {"strip_prefix": "ui"}}, "segments に、使えない項目がある"),
    ]:
        with pytest.raises(SystemExit) as ex:
            ast_query.extract(
                app,
                _params(files="ui/src/nowhere/*.ts", allow_empty=True, **over),
                "screen",
            )
        assert message in str(ex.value), message


LISTED = [
    {
        "id": "orders",
        "path": "/orders",
        "name": "orders/list",
        "source": {"file": "ui/src/orders/orderTabs.ts", "line": 1},
        "reason": "routes.ts の配列に ORDER_ROUTE として入っている。定義は別のファイルにある",
    },
    {
        "id": "admin.users",
        "path": "/admin/users",
        "source": {"file": "ui/src/admin/routes.ts", "line": 1},
        "reason": "makeAdminRoutes が作る。名前の配列から決まる",
        "attributes": {"generated": True},
    },
]


def test_listed_entries_carry_a_mark_and_checked_evidence(app: Path, capsys):
    recs, err = _run(listed, app, {"entries": LISTED}, capsys)
    assert (
        all(schema_errors("entry-candidate", r) == [] for r in recs)
        and "entries=2" in err
    )
    assert (
        recs[0]["attributes"] == {"listed_by": "agent", "reason": LISTED[0]["reason"]}
        and recs[0]["name"] == "orders/list"
    )
    assert (
        recs[1]["attributes"]
        == {"generated": True, "listed_by": "agent", "reason": LISTED[1]["reason"]}
        and "name" not in recs[1]
    )

    def bad(**over) -> dict:
        return {**LISTED[0], **over}

    cases = [
        ({"entries": []}, "params.entries が無いか、空"),
        ({}, "params.entries が無いか、空"),
        ({"entries": ["orders"]}, "params.entries/0: 形が違う"),
        ({"entries": [bad(reason="")]}, "params.entries/orders: ['reason'] が無い"),
        ({"entries": [bad(reason="  ")]}, "params.entries/orders: reason が空"),
        (
            {"entries": [bad(source={"file": "ui/src/orders/orderTabs.ts"})]},
            "source は {file: 相対パス, line: 1 以上の行} で書く",
        ),
        (
            {"entries": [bad(source={"file": "ui/src/orders/nothing.ts", "line": 1})]},
            "source.file 'ui/src/orders/nothing.ts' がscope に無い",
        ),
        (
            {"entries": [bad(source={"file": "../outside.ts", "line": 1})]},
            "scope の外を指している",
        ),
        (
            {
                "entries": [
                    bad(
                        source={
                            "file": str(app / "ui/src/orders/orderTabs.ts"),
                            "line": 1,
                        }
                    )
                ]
            },
            "が絶対パス (対象の範囲 (scope) からの相対パスで書く)",
        ),
        (
            {
                "entries": [
                    bad(source={"file": "ui/src/orders/orderTabs.ts", "line": 99})
                ]
            },
            "source.line 99 が 'ui/src/orders/orderTabs.ts' の行数 5 を超えている",
        ),
        (
            {"entries": [LISTED[0], LISTED[0]]},
            "params.entries/orders: id が重複している",
        ),
        (
            {"entries": [bad(id=1), bad(id="1", path="/other")]},
            "params.entries/1: id が重複している",
        ),  # 出すときに文字にするので、1 と "1" は同じ id
    ]
    for params, message in cases:
        with pytest.raises(SystemExit) as ex:
            listed.extract(app, params, "screen")
        assert message in str(ex.value), (message, str(ex.value))
    assert capsys.readouterr().out == "", "1 件でも問題があれば、候補を 1 件も出さない"
    recs, _ = _run(listed, app, {"entries": [], "allow_empty": True}, capsys)
    assert recs == []


def _entry_list(app: Path, extractors: list[dict]) -> Path:
    repo = app / "atlas"
    (repo / "analysis").mkdir(parents=True)
    path = repo / "analysis" / "entry-list.yaml"
    doc = {
        "format_version": 1,
        "target": {
            "repo": "github.example/acme/shop-ui",
            "commit": "0a1b2c3d4e",
            "clone_path": "..",
            "scope": ".",
        },
        "profile": {"id": "ui-code-routes", "version": "0.1.0"},
        "extractors": extractors,
        "entries": [],
    }
    path.write_text(
        yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    return path


def test_enumerate_mixes_tool_and_agent_entries_and_keeps_approvals(app: Path, capsys):
    """道具が取った入口と、エージェントが足した入口は、同じ一覧に並ぶ。列挙をやり直しても、承認と印は残る。"""
    path = _entry_list(
        app,
        [
            {
                "name": "vue-routes",
                "run": "abatlas-extract ast",
                "layer": "screen",
                "params": _params(),
            },
            {
                "name": "agent-listed",
                "run": "abatlas-extract listed",
                "layer": "screen",
                "params": {"entries": LISTED},
            },
        ],
    )
    out = enumerate_entries(path)
    assert validate_entry_list(out) == []
    by = {e["id"]: e for e in out["entries"]}
    assert sorted(by) == ["admin.users", "books.bookId", "dashboards", "orders", "root"]
    assert {e["extractor"] for e in out["entries"]} == {"vue-routes", "agent-listed"}
    assert (
        by["orders"]["attributes"]["listed_by"] == "agent"
        and "listed_by" not in by["dashboards"]["attributes"]
    )
    assert (
        "読めなかった参照: ui/src/routes/routes.ts:13: ORDER_ROUTE"
        in capsys.readouterr().err
    ), "抽出器の知らせは、列挙の出力に出る"

    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    for e in doc["entries"]:
        if e["id"] == "orders":
            e.update(status="approved", note="定義を読んで確かめた")
    path.write_text(
        yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    again = {e["id"]: e for e in enumerate_entries(path)["entries"]}
    assert (
        again["orders"]["status"] == "approved"
        and again["orders"]["note"] == "定義を読んで確かめた"
    )
    assert again["orders"]["attributes"]["reason"] == LISTED[0]["reason"]

    # 承認の後に、同じ id の指す先を書き換えたら、承認は引き継がない (人が見ていない入口を、承認済みにしない)
    def rewrite(**over) -> None:
        d = yaml.safe_load(path.read_text(encoding="utf-8"))
        d["extractors"][1]["params"]["entries"][0].update(over)
        path.write_text(
            yaml.safe_dump(d, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )

    def approve_orders() -> None:
        d = yaml.safe_load(path.read_text(encoding="utf-8"))
        next(e for e in d["entries"] if e["id"] == "orders").update(
            status="approved", note="定義を読んで確かめた"
        )
        path.write_text(
            yaml.safe_dump(d, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )

    def set_listed_layer(layer: str) -> None:
        d = yaml.safe_load(path.read_text(encoding="utf-8"))
        d["extractors"][1]["layer"] = layer
        path.write_text(
            yaml.safe_dump(d, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )

    # 行と説明の文だけの違いは、同じ入口 (対象のコミットを進めると行はずれる。説明は書き直すたびに言い回しが変わる)
    rewrite(
        source={"file": "ui/src/orders/orderTabs.ts", "line": 2},
        reason="行と説明だけを直した",
    )
    capsys.readouterr()
    moved = {e["id"]: e for e in enumerate_entries(path)["entries"]}
    assert (
        moved["orders"]["status"] == "approved"
        and moved["orders"]["attributes"]["reason"] == "行と説明だけを直した"
    )
    assert "candidate に戻す" not in capsys.readouterr().err
    # 指す先 (階層パス、層、定義のファイル) のどれが変わっても、承認前に戻る
    changes = [
        (
            lambda: rewrite(source={"file": "ui/src/admin/routes.ts", "line": 1}),
            lambda: rewrite(source=LISTED[0]["source"]),
        ),
        (lambda: rewrite(path="/orders/all"), lambda: rewrite(path="/orders")),
        (lambda: set_listed_layer("job"), lambda: set_listed_layer("screen")),
    ]
    for change, undo in changes:
        change()
        moved = {e["id"]: e for e in enumerate_entries(path)["entries"]}
        assert (
            moved["orders"]["status"] == "candidate" and "note" not in moved["orders"]
        )
        assert (
            "入口 'orders' は、approved の後に指す先が変わった"
            in capsys.readouterr().err
        )
        undo()
        enumerate_entries(path)
        approve_orders()

    # 別の入口が、抽出器が出した入口と同じ id になったら止まる (片方を黙って捨てない)。違いは、階層パス・層・定義のファイルのどれでも
    before = path.read_text(encoding="utf-8")
    same_place = {"file": "ui/src/routes/routes.ts", "line": 7}
    for over, shown in [
        (
            {"path": "/somewhere/else", "source": same_place},
            "vue-routes は '/dashboards' (層 screen、ui/src/routes/routes.ts) の 7 行、agent-listed は '/somewhere/else' (層 screen、ui/src/routes/routes.ts) の 7 行",
        ),
        (
            {"path": "/dashboards", "source": LISTED[0]["source"]},
            "agent-listed は '/dashboards' (層 screen、ui/src/orders/orderTabs.ts)",
        ),
    ]:
        rewrite(id="dashboards", **over)
        with pytest.raises(SystemExit) as ex:
            enumerate_entries(path)
        assert "id 'dashboards' が 2 つの抽出器から、違う入口として出た" in str(
            ex.value
        ) and shown in str(ex.value)
    rewrite(id="dashboards", path="/dashboards", source=same_place)
    set_listed_layer("job")
    with pytest.raises(SystemExit) as ex:
        enumerate_entries(path)
    assert "agent-listed は '/dashboards' (層 job、ui/src/routes/routes.ts)" in str(
        ex.value
    )
    set_listed_layer("screen")
    rewrite(
        source={"file": "ui/src/routes/routes.ts", "line": 8}
    )  # 同じファイルの別の行の定義は、別の入口かもしれない
    with pytest.raises(SystemExit) as ex:
        enumerate_entries(path)
    assert (
        "vue-routes は '/dashboards' (層 screen、ui/src/routes/routes.ts) の 7 行、agent-listed は '/dashboards' (層 screen、ui/src/routes/routes.ts) の 8 行"
        in str(ex.value)
    )
    rewrite(source=same_place)
    # 同じ入口の重複 (指す先も行も同じ) は、先に書いた抽出器の候補を残す
    capsys.readouterr()
    same = {e["id"]: e for e in enumerate_entries(path, write=False)["entries"]}
    assert (
        same["dashboards"]["extractor"] == "vue-routes"
        and "先に書いた抽出器の候補を残す" in capsys.readouterr().err
    )
    assert path.read_text(encoding="utf-8") != before
    path.write_text(before, encoding="utf-8")

    # 道具だけが失敗する対象 (読めない言語) でも、エージェントが足した入口だけで一覧を作れる
    only = _entry_list(
        app / "second",
        [
            {
                "name": "agent-listed",
                "run": "abatlas-extract listed",
                "layer": "screen",
                "params": {"entries": LISTED},
            }
        ],
    )
    doc = yaml.safe_load(only.read_text(encoding="utf-8"))
    doc["target"]["clone_path"] = "../.."
    only.write_text(
        yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    assert sorted(e["id"] for e in enumerate_entries(only)["entries"]) == [
        "admin.users",
        "orders",
    ]


def test_code_search_prints_places_without_touching_the_list(app: Path, capsys):
    path = _entry_list(app, [])
    work = path.parent / "work-definition.yaml"
    work.write_text(
        yaml.safe_dump(
            {"target": yaml.safe_load(path.read_text(encoding="utf-8"))["target"]}
        ),
        encoding="utf-8",
    )
    before = path.read_text(encoding="utf-8")
    capsys.readouterr()
    assert (
        cli_main(
            [
                "code-search",
                str(work),
                "--language",
                "typescript",
                "--files",
                "ui/src/**/*.ts",
                "--pattern",
                "import($PATH)",
            ]
        )
        == 0
    )
    out = capsys.readouterr().out.splitlines()
    assert (
        out[0] == 'ui/src/orders/orderTabs.ts:4: import("./Orders.vue")'
        and out[-1] == "# files=3 matches=3"
    )
    assert (
        cli_main(
            [
                "code-search",
                str(work),
                "--language",
                "typescript",
                "--files",
                "ui/src/**/*.ts",
                "--rule",
                json.dumps(ROUTE_RULE),
                "--limit",
                "1",
            ]
        )
        == 0
    )
    out = capsys.readouterr().out.splitlines()
    assert len(out) == 2 and out[-1] == "# files=3 matches=4 (先頭の 1 件だけ出した)"
    for args, message in [
        (
            ["--language", "typescript", "--files", "ui/src/**/*.ts"],
            "--pattern か --rule の、どちらか 1 つを渡す",
        ),
        (
            ["--language", "svelte", "--files", "ui/src/**/*.ts", "--pattern", "a"],
            "language 'svelte' は読めない",
        ),
        (
            ["--language", "typescript", "--files", "nowhere/*.ts", "--pattern", "a"],
            "に一致するファイルが",
        ),
        (
            [
                "--language",
                "typescript",
                "--files",
                "ui/src/**/*.ts",
                "--rule",
                "{broken",
            ],
            "--rule を JSON として読めない",
        ),
    ]:
        assert cli_main(["code-search", str(work), *args]) == 2
        assert message in capsys.readouterr().err, message
    assert path.read_text(encoding="utf-8") == before


def test_dry_run_prints_candidates_and_extractors_prints_params(app: Path, capsys):
    """試しの列挙は、一覧を書かずに候補を出す。抽出器の params の説明は、コマンドで出せる (分析リポジトリには、抽出器のソースが無い)。"""
    path = _entry_list(
        app,
        [
            {
                "name": "vue-routes",
                "run": "abatlas-extract ast",
                "layer": "screen",
                "params": _params(),
            }
        ],
    )
    before = path.read_text(encoding="utf-8")
    capsys.readouterr()
    assert cli_main(["enumerate", str(path), "--dry-run"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert (
        "books.bookId\t/books/:bookId\tscreen\tvue-routes\tcandidate" in out
        and len(out) == 3
    )
    assert path.read_text(encoding="utf-8") == before
    assert cli_main(["extractors"]) == 0
    assert "ast, glob, listed, nested-keys, structured-query" in capsys.readouterr().out
    for kind, needle in [
        ("ast", "unresolved:"),
        ("listed", "reason:"),
        ("glob", "strip_prefix:"),
        ("structured-query", "records:"),
        ("nested-keys", "levels:"),
    ]:
        assert cli_main(["extractors", kind]) == 0
        assert needle in capsys.readouterr().out, kind
    assert cli_main(["extractors", "nope"]) == 2
