"""glob 抽出器と、それを使う ui-nextjs プロファイル (Next.js の画面) を、小さな見本の app ディレクトリで確かめる。"""

import copy
import json
from pathlib import Path

import pytest
import yaml

from abatlas.enumerate import enumerate_entries
from abatlas.extractors.file_glob import extract, segments_of
from abatlas.layout import init_repo
from abatlas.schemas import schema_errors
from abatlas.validate import validate_entry_list, validate_profile

REPO_ROOT = Path(__file__).resolve().parent.parent
PROFILE = REPO_ROOT / "profiles" / "ui-nextjs" / "profile.yaml"

# Next.js (App Router) の置き場の見本。値は (ファイル, 中身)
PAGES = {
    "src/app/page.tsx": "'use client';\nexport default function Root() { return null; }\n",
    "src/app/login/page.tsx": "import { LoginPage } from './LoginPage';\n\nexport default function () { return <LoginPage />; }\n",
    "src/app/(main)/websites/page.tsx": "export default function () { return null; }\nexport const metadata = { title: 'Websites' };\n",
    "src/app/(main)/websites/[websiteId]/page.tsx": "export default async function ({ params }) { return null; }\n",
    "src/app/(main)/websites/[websiteId]/(reports)/funnels/page.tsx": "export default function () { return null; }\n",
    "src/app/(main)/websites/[websiteId]/sessions/[sessionId]/page.tsx": "export default function () { return null; }\n",
    "src/app/(main)/websites/[websiteId]/@modal/(.)sessions/[sessionId]/page.tsx": "export default function () { return null; }\n",
    "src/app/share/[slug]/[[...path]]/page.tsx": "export default function () { return null; }\n",
    "src/app/(main)/feed/@modal/(..)(..)photo/[id]/page.tsx": "export default function () { return null; }\n",
}
# 画面を包む共通の枠 (layout ファイル)。画面とは別の入口として拾う
LAYOUTS = {
    "src/app/layout.tsx": "export default function ({ children }) { return children; }\n",
    "src/app/(main)/layout.tsx": "'use client';\nexport default function ({ children }) { return children; }\n",
    "src/app/(main)/websites/[websiteId]/layout.tsx": "export default async function ({ children }) { return children; }\n",
}
OTHERS = {
    "src/app/api/websites/[websiteId]/stats/route.ts": "export async function GET() {}\n",
    **LAYOUTS,
    "src/app/_lib/layout.tsx": "export default function ({ children }) { return children; }\n",  # private folder の下は枠にもならない
    "src/components/page.tsx": "export default function () { return null; }\n",  # app の外。入口ではない
    "src/app/_lib/page.tsx": "export default function () { return null; }\n",  # private folder の下はルーティングの対象外
    "src/app/(main)/websites/_parts/preview/page.tsx": "export default function () { return null; }\n",
}


def _params() -> dict:
    return yaml.safe_load(PROFILE.read_text(encoding="utf-8"))["extractors"][0]["params"]


@pytest.fixture()
def app(tmp_path: Path) -> Path:
    for rel, text in {**PAGES, **OTHERS}.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return tmp_path


def _run(scope: Path, params: dict, capsys) -> list[dict]:
    extract(scope, params, "page")
    return [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]


def test_next_pages_become_entries_with_url_shaped_paths(app: Path, capsys):
    recs = _run(app, _params(), capsys)
    assert all(schema_errors("entry-candidate", r) == [] for r in recs)
    by_file = {r["source"]["file"]: r for r in recs}
    assert set(by_file) == set(PAGES), "page ファイルだけが入口 (route / layout / app の外は入口ではない)"
    got = {r["path"]: r["id"] for r in recs}
    assert got == {
        "/(root)": "root_r",
        "/login": "login",
        "/websites": "websites",
        "/websites/[websiteId]": "websites.websiteId_d",
        "/websites/[websiteId]/funnels": "websites.websiteId_d.funnels",  # (reports) は URL に出ないので落ちる
        "/websites/[websiteId]/sessions/[sessionId]": "websites.websiteId_d.sessions.sessionId_d",
        "/websites/[websiteId]/@modal/sessions/[sessionId]": "websites.websiteId_d.modal_s.sessions.sessionId_d",  # 小窓版は別の入口
        "/share/[slug]/[[...path]]": "share.slug_d.path_o",
        "/feed/@modal/photo/[id]": "feed.modal_s.photo.id_d",  # 重なった割り込みの印 (..)(..) も外す
    }


def test_segments_that_differ_only_by_kind_get_different_ids(app: Path, capsys):
    """静的な段・動的な段・並行ルート・app 直下は、名前が同じでも Next.js では別の画面。既定パラメータで別の id になる。"""
    cases = {
        "src/app/blog/id/page.tsx": ("/blog/id", "blog.id"),
        "src/app/blog/[id]/page.tsx": ("/blog/[id]", "blog.id_d"),
        "src/app/blog/id_/page.tsx": ("/blog/id_", "blog.id__"),
        "src/app/blog/id_d/page.tsx": ("/blog/id_d", "blog.id__d"),
        "src/app/docs/[...all]/page.tsx": ("/docs/[...all]", "docs.all_c"),
        "src/app/help/[[...all]]/page.tsx": ("/help/[[...all]]", "help.all_o"),
        "src/app/help/all/page.tsx": ("/help/all", "help.all"),
        "src/app/[lang]/page.tsx": ("/[lang]", "lang_d"),
        "src/app/root/page.tsx": ("/root", "root"),  # app 直下 (root_r) とは別
        "src/app/@panel/page.tsx": ("/@panel", "panel_s"),
        "src/app/panel/page.tsx": ("/panel", "panel"),
        "src/app/my_page/[my_id]/page.tsx": ("/my_page/[my_id]", "my__page.my__id_d"),
    }
    for rel in cases:
        (app / rel).parent.mkdir(parents=True)
        (app / rel).write_text("export default function () {}\n", encoding="utf-8")
    recs = {r["source"]["file"]: r for r in _run(app, _params(), capsys)}
    assert {f: (recs[f]["path"], recs[f]["id"]) for f in cases} == cases
    assert recs["src/app/page.tsx"]["id"] == "root_r"
    assert len({r["id"] for r in recs.values()}) == len(recs) == len(PAGES) + len(cases)
    assert all(schema_errors("entry-candidate", r) == [] for r in recs.values())


def test_names_that_differ_only_by_stripped_symbols_fail_loudly(app: Path):
    """記号だけが違う名前 (/a.b と /ab) は既定の加工では同じ id になる。黙って片方を捨てず、両方のファイルを示して止まる。"""
    for rel in ("src/app/a.b/page.tsx", "src/app/ab/page.tsx"):
        (app / rel).parent.mkdir(parents=True)
        (app / rel).write_text("export default function () {}\n", encoding="utf-8")
    with pytest.raises(SystemExit) as ex:
        extract(app, _params(), "page")
    assert "id 'ab' が 2 つのファイルから出た" in str(ex.value) and "a.b/page.tsx" in str(ex.value)


def test_source_line_name_and_attributes(app: Path, capsys):
    by_path = {r["path"]: r for r in _run(app, _params(), capsys)}
    assert by_path["/login"]["source"] == {"file": "src/app/login/page.tsx", "line": 3}, "出典の行は export default の行"
    assert by_path["/login"]["name"] == "login" and by_path["/websites/[websiteId]"]["name"] == "[websiteId]"
    assert by_path["/(root)"]["attributes"]["client"] is True and by_path["/login"]["attributes"]["client"] is False
    assert by_path["/websites"]["attributes"]["metadata"] is True
    assert by_path["/websites/[websiteId]/funnels"]["attributes"]["file_segments"] == ["(main)", "websites", "[websiteId]", "(reports)", "funnels"], "加工前の段も残す (入れ物が分かる)"


def test_output_is_deterministic(app: Path, capsys):
    assert _run(app, _params(), capsys) == _run(app, _params(), capsys)


def test_colliding_ids_are_an_error_not_a_silent_merge(app: Path, capsys):
    # /a-b と /a_b は id の既定の加工では別々 (a-b / a__b) だが、記号を全部落とす設定では同じ ab になる
    for rel in ("src/app/a-b/page.tsx", "src/app/a_b/page.tsx"):
        (app / rel).parent.mkdir(parents=True)
        (app / rel).write_text("export default function () {}\n", encoding="utf-8")
    assert len(_run(app, _params(), capsys)) == len(PAGES) + 2
    with pytest.raises(SystemExit) as ex:
        extract(app, {**_params(), "id": {"replace": [{"pattern": "[^A-Za-z0-9]", "with": ""}]}}, "page")
    assert "id 'ab' が 2 つのファイルから出た" in str(ex.value)


def test_group_only_path_collision_is_reported(app: Path):
    """(a)/x と (b)/x は同じ URL (Next.js でもビルドエラー)。黙って片方を捨てない。"""
    for rel in ("src/app/(a)/x/page.tsx", "src/app/(b)/x/page.tsx"):
        (app / rel).parent.mkdir(parents=True)
        (app / rel).write_text("export default function () {}\n", encoding="utf-8")
    with pytest.raises(SystemExit) as ex:
        extract(app, _params(), "page")
    assert "id 'x' が 2 つのファイルから出た" in str(ex.value)


@pytest.mark.parametrize("params, needle", [
    ({"files": ["nowhere/**/page.tsx"]}, "一致するファイルが scope に無い"),
    ({"files": ["src/app/**/page.tsx"], "segments": {"strip_prefix": "app"}}, "strip_prefix 'app' の下に無い"),
    ({"files": ["src/app/**/page.tsx"], "segments": {"strip_prefix": "src/app", "empty": "()"}}, "id が空になった"),
    ({}, "params.files が無い"),
])
def test_misconfiguration_fails_loudly(app: Path, params, needle):
    with pytest.raises(SystemExit) as ex:
        extract(app, params, "page")
    assert needle in str(ex.value)


def test_generic_options(app: Path, capsys):
    """Next.js に限らない使い方: ファイル名を最後の段にする、除外、空を許す、name を階層パスに。"""
    for rel in ("jobs/daily/cleanup.sh", "jobs/daily/report.sh", "jobs/lib/common.sh"):
        (app / rel).parent.mkdir(parents=True, exist_ok=True)
        (app / rel).write_text("#!/bin/sh\n# main\nrun\n", encoding="utf-8")
    recs = _run(app, {"files": "jobs/**/*.sh", "exclude": ["jobs/lib/*"], "segments": {"strip_prefix": "jobs", "drop_last": False}, "name": "path", "line_match": "^run"}, capsys)
    assert [(r["id"], r["path"], r["name"], r["source"]["line"]) for r in recs] == [("daily.cleanup", "/daily/cleanup", "/daily/cleanup", 3), ("daily.report", "/daily/report", "/daily/report", 3)]
    assert _run(app, {"files": "nowhere/*.sh", "allow_empty": True}, capsys) == []


def test_segments_of_keeps_raw_and_processed():
    conf = {"strip_prefix": "src/app", "drop": ["\\([^)]+\\)"], "replace": [{"pattern": "^\\(\\.+\\)", "with": ""}]}
    assert segments_of("src/app/(main)/a/@m/(..)b/page.tsx", conf) == (["(main)", "a", "@m", "(..)b"], ["a", "@m", "b"])
    assert segments_of("src/app/(main)/page.tsx", conf) == (["(main)"], ["(root)"])


# ---------------------------------------------------------------- プロファイル (2 本目) が同じ手順で通る

def test_ui_nextjs_profile_is_valid():
    profile = yaml.safe_load(PROFILE.read_text(encoding="utf-8"))
    assert validate_profile(profile) == []
    assert (PROFILE.parent / "context.md").is_file()
    roles = {t["id"]: t.get("role", "intermediate") for t in profile["layers"]}
    assert roles == {"page": "entry", "layout": "entry", "part": "entry", "component": "intermediate", "api_route": "intermediate", "query": "intermediate", "external": "boundary"}
    assert profile["within"] == [{"layer": "layout", "rule": "source_dir"}], "画面は、祖先のフォルダの枠 (layout) の中で動く"
    for bad_within, needle in (([{"layer": "component", "rule": "source_dir"}], "role: entry の層ではない"),
                               ([{"layer": "layout", "rule": "source_dir"}] * 2, "重複"),
                               ([{"layer": "layout", "rule": "by_url"}], "schema")):
        assert any(needle in f for f in validate_profile({**profile, "within": bad_within})), needle
    # サーバー側で動く page / component は ORM や fetch を直接書ける。io が空だと、その読み書きを結果に書けない (機械チェックが落とす)
    io = {t["id"]: set(t["io"]) for t in profile["layers"]}
    assert all({"rdb", "external_api"} <= io[t] for t in ("page", "component", "api_route", "query", "external"))
    # 段の名前に残る Next.js の書き方 ([id]) は、画面で説明する。contains は入口の詳細のページでの出し分けに使う (部分文字列。Python と JavaScript で方言が違う正規表現にしない)
    notes = profile["hierarchy"]["notes"]
    hit = lambda path: [n["text"] for n in notes if n["contains"] in path]
    assert len(hit("/websites/[websiteId]")) == 1 and "角かっこ" in hit("/websites/[websiteId]")[0]
    assert hit("/login") == []
    assert len(hit("/(layout)/(main)")) == 1 and "layout ファイル" in hit("/(layout)/(main)")[0]
    # 枠の入口は、詳細のページで page ではなく layout と呼ぶ (画面は既定の、階層の末尾の名前)
    labels = profile["hierarchy"]["entry_labels"]
    name = lambda path: next((x["label"] for x in labels if x["contains"] in path), profile["hierarchy"]["level_labels"][-1])
    assert name("/(layout)/(main)") == "layout" and name("/(layout)") == "layout" and name("/settings/teams/[teamId]") == "page"
    assert validate_profile({**profile, "hierarchy": {**profile["hierarchy"], "entry_labels": [{"contains": "(layout)"}]}}), "呼び名の無い出し分けは schema が落とす"
    bad = copy.deepcopy(profile)
    bad["hierarchy"]["notes"][0]["pattern"] = "\\["
    assert validate_profile(bad), "決めていないキー (正規表現の pattern) は schema が落とす"


def test_ui_nextjs_init_and_enumerate_like_the_first_profile(app: Path, tmp_path_factory):
    """バッチの型と同じ手順 (init → entry-list に抽出器を書く → enumerate) で入口が並ぶ。"""
    repo = tmp_path_factory.mktemp("ui-repo")
    init_repo(repo, "ui-nextjs", targets="claude-code")
    assert (repo / ".abatlas" / "profiles" / "ui-nextjs" / "context.md").is_file()
    profile = yaml.safe_load(PROFILE.read_text(encoding="utf-8"))
    ex = profile["extractors"][0]
    entry_list = {
        "format_version": 1,
        "target": {"repo": "example/app", "commit": "0" * 40, "clone_path": str(app)},
        "profile": {"id": profile["id"], "version": profile["version"]},
        "extractors": [{"name": ex["name"], "run": ex["run"], "layer": ex["layer"], "params": ex["params"], "rationale": "test"}],
    }
    path = repo / "analysis" / "entry-list.yaml"
    path.write_text(yaml.safe_dump(entry_list, allow_unicode=True, sort_keys=False), encoding="utf-8")
    out = enumerate_entries(path, PROFILE)
    assert [e["id"] for e in out["entries"]] == sorted(e["id"] for e in out["entries"]) and len(out["entries"]) == len(PAGES)
    assert {e["status"] for e in out["entries"]} == {"candidate"} and {e["layer"] for e in out["entries"]} == {"page"}
    again = enumerate_entries(path, PROFILE)
    assert again["entries"] == out["entries"] and again["enumerated_at"] == out["enumerated_at"], "列挙は決定的"
    assert all("within" not in e for e in out["entries"]), "枠の抽出器を書かなければ、包む関係は付かない (これまでの一覧のまま)"


# ---------------------------------------------------------------- 画面を包む共通の枠 (layout) を、別の入口にする

def _layout_params() -> dict:
    return next(e for e in yaml.safe_load(PROFILE.read_text(encoding="utf-8"))["extractors"] if e["name"] == "next-layouts")["params"]


def test_next_layouts_become_entries_apart_from_pages(app: Path, capsys):
    extract(app, _layout_params(), "layout")
    recs = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert all(schema_errors("entry-candidate", r) == [] for r in recs)
    assert {r["source"]["file"]: (r["path"], r["id"], r["name"]) for r in recs} == {
        "src/app/layout.tsx": ("/(layout)", "layout_l", "(layout)"),  # app 直下の枠は、固定の段だけ
        "src/app/(main)/layout.tsx": ("/(layout)/(main)", "layout_l.main_g", "(main)"),  # 入れ物 (group) を落とさない: どの入れ物の枠かが名前
        "src/app/(main)/websites/[websiteId]/layout.tsx": ("/(layout)/(main)/websites/[websiteId]", "layout_l.main_g.websites.websiteId_d", "[websiteId]"),
    }
    by_file = {r["source"]["file"]: r for r in recs}
    assert by_file["src/app/(main)/layout.tsx"]["attributes"]["client"] is True and by_file["src/app/(main)/layout.tsx"]["source"]["line"] == 2
    page_ids = {r["id"] for r in _run(app, _params(), capsys)}
    assert not page_ids & {r["id"] for r in recs}, "枠の id は画面の id と重ならない"


def test_layout_ids_do_not_collide_with_pages_or_same_named_folders(app: Path, capsys):
    """(main) と main、画面の /layout と app 直下の枠は、名前が似ていても別の id になる。"""
    files = {
        "src/app/main/layout.tsx": "layout_l.main",
        "src/app/(layout)/layout.tsx": "layout_l.layout_l",  # 入れ物の名前が固定の段と同じでも、段の数が違うので app 直下の枠 (layout_l) と重ならない
        "src/app/layout_l/layout.tsx": "layout_l.layout__l",
    }
    for rel in [*files, "src/app/layout/page.tsx", "src/app/layout_l/page.tsx"]:
        (app / rel).parent.mkdir(parents=True, exist_ok=True)
        (app / rel).write_text("export default function () {}\n", encoding="utf-8")
    extract(app, _layout_params(), "layout")
    layouts = {r["source"]["file"]: r["id"] for r in (json.loads(l) for l in capsys.readouterr().out.splitlines() if l.strip())}
    assert {f: layouts[f] for f in files} == files and layouts["src/app/(main)/layout.tsx"] == "layout_l.main_g"
    pages = {r["id"] for r in _run(app, _params(), capsys)}
    assert {"layout", "layout__l"} <= pages and not pages & set(layouts.values())


def test_segments_prefix_is_put_before_processed_segments():
    conf = {"strip_prefix": "src/app", "prefix": "(layout)", "drop": ["\\(main\\)"]}
    assert segments_of("src/app/(main)/a/layout.tsx", conf) == (["(main)", "a"], ["(layout)", "a"])
    assert segments_of("src/app/layout.tsx", conf) == ([], ["(layout)"]), "prefix があれば empty の段は置かない"
    assert segments_of("src/app/layout.tsx", {"strip_prefix": "src/app", "prefix": ["x", "y"]})[1] == ["x", "y"]
    with pytest.raises(SystemExit) as ex:
        segments_of("src/app/layout.tsx", {"strip_prefix": "src/app", "prefix": "a/b"})
    assert "段ごとに配列で書く" in str(ex.value)


@pytest.fixture()
def ui_entry_list(app: Path, tmp_path_factory):
    """画面と枠の両方の抽出器を書いた入口の一覧 (列挙の前)。"""
    repo = tmp_path_factory.mktemp("ui-within")
    init_repo(repo, "ui-nextjs", targets="claude-code")
    profile = yaml.safe_load(PROFILE.read_text(encoding="utf-8"))
    entry_list = {
        "format_version": 1,
        "target": {"repo": "example/app", "commit": "0" * 40, "clone_path": str(app)},
        "profile": {"id": profile["id"], "version": profile["version"]},
        "extractors": [{"name": ex["name"], "run": ex["run"], "layer": ex["layer"], "params": ex["params"], "rationale": "test"} for ex in profile["extractors"]],
    }
    path = repo / "analysis" / "entry-list.yaml"
    path.write_text(yaml.safe_dump(entry_list, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return repo, path


def test_enumerate_fills_within_from_source_folders(ui_entry_list):
    """画面ごとの「通る枠」は、ソースのフォルダの親子から道具が決める (外側から)。枠も、外側の枠の中で動く。"""
    _, path = ui_entry_list
    out = enumerate_entries(path, PROFILE)
    within = {e["id"]: e.get("within") for e in out["entries"]}
    assert len(out["entries"]) == len(PAGES) + len(LAYOUTS)
    assert within["login"] == ["layout_l"] and within["root_r"] == ["layout_l"], "(main) の外の画面は、全体の枠だけ"
    assert within["websites"] == ["layout_l", "layout_l.main_g"]
    assert within["websites.websiteId_d"] == ["layout_l", "layout_l.main_g", "layout_l.main_g.websites.websiteId_d"], "同じフォルダの枠も通る"
    assert within["websites.websiteId_d.funnels"] == within["websites.websiteId_d.modal_s.sessions.sessionId_d"] == within["websites.websiteId_d"]
    assert within["feed.modal_s.photo.id_d"] == ["layout_l", "layout_l.main_g"], "階層パスではなくソースの置き場で決める (割り込みルートの小窓も、置き場の枠を通る)"
    assert within["layout_l"] is None and within["layout_l.main_g"] == ["layout_l"]
    assert within["layout_l.main_g.websites.websiteId_d"] == ["layout_l", "layout_l.main_g"]
    assert validate_entry_list(out, yaml.safe_load(PROFILE.read_text(encoding="utf-8"))) == []
    # 人の承認と、2 回目の列挙
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    for e in doc["entries"]:
        e["status"] = "approved" if e["layer"] == "layout" else e["status"]
    path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    again = enumerate_entries(path, PROFILE)
    assert again["entries"] == doc["entries"] and again["enumerated_at"] == out["enumerated_at"], "列挙は決定的で、承認を引き継ぐ"
    # プロファイルを渡さなければ、包む関係は付けない (宣言が分からないため)
    assert all("within" not in e for e in enumerate_entries(path, None, write=False)["entries"])


def test_within_is_checked_against_entries_and_the_profile(ui_entry_list):
    _, path = ui_entry_list
    profile = yaml.safe_load(PROFILE.read_text(encoding="utf-8"))
    good = enumerate_entries(path, PROFILE)

    def problems(mutate, prof=profile):
        doc = copy.deepcopy(good)
        mutate({e["id"]: e for e in doc["entries"]})
        return validate_entry_list(doc, prof)

    assert any("'nope' が entries に無い" in p for p in problems(lambda e: e["login"].update(within=["nope"]), None))
    assert any("自分自身" in p for p in problems(lambda e: e["login"].update(within=["login"]), None))
    assert any("循環" in p for p in problems(lambda e: e["layout_l"].update(within=["layout_l.main_g"]), None))
    assert any("schema" in p for p in problems(lambda e: e["login"].update(within=[]), None)), "空の within は書かない"
    # プロファイルを渡すと、宣言から決まる値と違う within (手で直した・古い一覧) を指摘する
    assert any("enumerate をやり直す" in p for p in problems(lambda e: e["login"].pop("within")))
    assert any("enumerate をやり直す" in p for p in problems(lambda e: e["websites"].update(within=["layout_l.main_g", "layout_l"])))
    # 古い within が残っていても、列挙はやり直せる (検査で止まらない)
    doc = copy.deepcopy(good)
    doc["entries"][0]["within"] = ["nope"]
    path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    assert enumerate_entries(path, PROFILE)["entries"] == good["entries"]


def test_wrappers_in_the_same_folder_do_not_wrap_each_other():
    """包む側の層が 2 つあり、同じフォルダに包む入口が並んでも、包み合って循環しない。包まれる入口からは両方が見える (id 順)。"""
    from abatlas.validate import within_of

    def entry(eid, layer, file):
        return {"id": eid, "path": "/" + eid, "layer": layer, "source": {"file": file, "line": 1}, "status": "candidate"}

    profile = {"within": [{"layer": "frame_a", "rule": "source_dir"}, {"layer": "frame_b", "rule": "source_dir"}]}
    entries = [entry("a", "frame_a", "app/x/a.tsx"), entry("b", "frame_b", "app/x/b.tsx"), entry("top", "frame_a", "app/top.tsx"),
               entry("p", "page", "app/x/y/page.tsx"), entry("q", "page", "other/page.tsx")]
    assert within_of(entries, profile) == {"a": ["top"], "b": ["top"], "p": ["top", "a", "b"]}
    assert within_of(entries, None) == {} and within_of(entries, {"within": []}) == {}
    for e in entries:
        e.update(within=within_of(entries, profile).get(e["id"]) or None)
    doc = {"format_version": 1, "target": {"repo": "x/y", "commit": "0" * 40}, "profile": {"id": "p", "version": "1"}, "extractors": [],
           "entries": [{k: v for k, v in e.items() if v is not None} for e in entries]}
    assert validate_entry_list(doc) == []


def test_within_reaches_the_mart_the_entry_page_reads(ui_entry_list):
    """包む関係は seed → mart まで届き、画面が印 (tags: within) と keys だけで引ける。分析結果が 1 件も無くても集計できる。"""
    from fastapi.testclient import TestClient

    from abatlas.api import create_app
    from abatlas.build import build_repo

    repo, path = ui_entry_list
    enumerate_entries(path, PROFILE)
    rep = build_repo(repo)
    assert rep["dbt_ok"] == rep["dbt_nodes"] and rep["entry_within"] > 0, rep
    c = TestClient(create_app(repo), base_url="http://127.0.0.1:8765")
    marts = c.get("/marts").json()
    tagged = [m for m in marts if "within" in (m["declaration"].get("tags") or [])]
    assert len(tagged) == 1 and "subject" not in tagged[0]["declaration"], "入口の一覧の表 (subject: entry) と取り違えない"
    entry_table = next(m for m in marts if m["declaration"].get("subject") == "entry" and m["declaration"]["view"] == "table")
    assert entry_table["name"] != tagged[0]["name"]
    m, k = tagged[0], tagged[0]["declaration"]["keys"]
    # 1 行 = 包まれる入口 × 包む入口。パスを連ねて持たないので、パスにカンマがあっても画面は取り違えない
    mine = c.get(f"/marts/{m['name']}/rows", params={k["path"]: "/websites/[websiteId]", "order": f"-{k['order']}"}).json()["rows"]
    assert [r[k["members"]] for r in mine] == ["/(layout)/(main)/websites/[websiteId]", "/(layout)/(main)", "/(layout)"], "order の列で並べ替えられる (ここでは内側から)"
    mine = c.get(f"/marts/{m['name']}/rows", params={k["path"]: "/websites/[websiteId]", "order": k["order"]}).json()["rows"]
    assert [r[k["members"]] for r in mine] == ["/(layout)", "/(layout)/(main)", "/(layout)/(main)/websites/[websiteId]"], "包む入口は外側から"
    inner = sorted(r[k["path"]] for r in c.get(f"/marts/{m['name']}/rows", params={k["members"]: "/(layout)/(main)"}).json()["rows"])
    assert "/websites" in inner and "/(layout)/(main)/websites/[websiteId]" in inner and "/login" not in inner and "/(layout)/(main)" not in inner
    assert c.get(f"/marts/{m['name']}/rows", params={k["path"]: "/(layout)"}).json()["total"] == 0, "いちばん外の枠は、何にも包まれない"
    # 古い一覧 (枠を消した・手で直した) のまま集計しない: 欠けた・誤った関係を画面に出さない
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    by_id = {e["id"]: e for e in doc["entries"]}
    before = duckdb_mtime = (repo / "analysis" / "data" / "abatlas.duckdb").stat().st_mtime_ns
    by_id["login"]["within"] = ["layout_l", "layout_l.main_g"]  # 実在するが、宣言からは決まらない関係
    path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    with pytest.raises(SystemExit) as ex:
        build_repo(repo)
    assert "enumerate をやり直す" in str(ex.value) and "login" in str(ex.value)
    doc["entries"] = [e for e in doc["entries"] if e["id"] != "layout_l.main_g"]  # 包む入口を消したのに、参照が残った
    path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    with pytest.raises(SystemExit) as ex:
        build_repo(repo)
    assert "'layout_l.main_g' が entries に無い" in str(ex.value)
    assert (repo / "analysis" / "data" / "abatlas.duckdb").stat().st_mtime_ns == before == duckdb_mtime, "失敗した集計は、前の版を置き換えない"


def test_rejecting_a_wrapper_is_allowed_but_warned(ui_entry_list, capsys):
    """データを読まない枠は、人が除外してよい。除外すると、その処理はどの入口の結果にも現れないので、列挙が知らせる。"""
    _, path = ui_entry_list
    enumerate_entries(path, PROFILE)
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    for e in doc["entries"]:
        if e["id"] == "layout_l.main_g":
            e.update(status="rejected", note="test")
    path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    capsys.readouterr()
    out = enumerate_entries(path, PROFILE)
    assert validate_entry_list(out, yaml.safe_load(PROFILE.read_text(encoding="utf-8"))) == [], "除外は人の判断。検査は通す"
    err = capsys.readouterr().err
    wrapped = sum(1 for e in out["entries"] if "layout_l.main_g" in e.get("within", []))
    assert f"包む入口 'layout_l.main_g' は rejected。中で動く {wrapped} 件" in err and "layout_l'" not in err.replace("layout_l.main_g'", "")
