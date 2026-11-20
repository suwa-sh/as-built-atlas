"""webapp (段階 4): 宣言から画面を組む前提 (宣言の検査・前方一致の絞り込み・静的配信・シーケンス mart) を見本で確かめる。

画面そのもの (JavaScript の描画) はブラウザで見る。ここでは、画面が読む API の約束と build 時の宣言検査、
webapp のファイルの構造 (層の依存の向き、import の実在、自己完結、CSS の読み込み順) を検証する。
"""

import json
import re
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

import duckdb

from abatlas import ANALYSIS_DIR, dbt_workdir, duckdb_path
from abatlas.api import WEBAPP_DIR, create_app
from abatlas.build import build_repo
from abatlas.declarations import DECLARATIONS_TABLE, VIEWS, check_declaration, check_manifest, declared_models, read_declarations
from abatlas.layout import init_repo

FIX = Path(__file__).resolve().parent / "fixtures"
LOCAL = "http://127.0.0.1:8765"


def _entry_list(target: dict) -> dict:
    return {
        "format_version": 1, "target": target, "profile": {"id": "batch-kestra", "version": "0.1.0"},
        "extractors": [{"name": "kestra-flows", "run": "abatlas-extract structured-query", "layer": "scheduler", "params": {}, "rationale": "test"}],
        "enumerated_at": "2026-11-04T00:00:00+09:00",
        "entries": [{"id": "daily.housekeeping", "path": "/daily/housekeeping", "name": "housekeeping", "layer": "scheduler", "status": "approved",
                     "source": {"file": "flows/daily/housekeeping.yaml", "line": 1}, "extractor": "kestra-flows"},
                    {"id": "weekly.report", "path": "/weekly/report", "name": "report", "layer": "scheduler", "status": "candidate",
                     "source": {"file": "flows/weekly/report.yaml", "line": 1}, "extractor": "kestra-flows"}],
    }


@pytest.fixture(scope="module")
def repo(tmp_path_factory) -> Path:
    repo = tmp_path_factory.mktemp("webapp-repo")
    init_repo(repo, "batch-kestra", targets="claude-code")
    an = repo / ANALYSIS_DIR
    result = yaml.safe_load((FIX / "result-housekeeping.yaml").read_text(encoding="utf-8"))
    (an / "results" / "daily.housekeeping.yaml").write_text(yaml.safe_dump(result, allow_unicode=True, sort_keys=False), encoding="utf-8")
    (an / "entry-list.yaml").write_text(yaml.safe_dump(_entry_list(result["target"]), allow_unicode=True, sort_keys=False), encoding="utf-8")
    rep = build_repo(repo)
    assert rep["dbt_ok"] == rep["dbt_nodes"], rep
    return repo


def client(repo: Path) -> TestClient:
    return TestClient(create_app(repo), base_url=LOCAL)


# ---------------------------------------------------------------- 宣言の検査 (build が行う)

def test_core_declarations_pass_against_real_columns(repo: Path):
    assert check_manifest(dbt_workdir(repo) / "target" / "manifest.json", duckdb_path(repo)) == []


def test_every_core_view_kind_is_declared(repo: Path):
    """表示の種類 6 つがコア mart で全部使われている (webapp の 6 描画が見本で確かめられる)。"""
    manifest = json.loads((dbt_workdir(repo) / "target" / "manifest.json").read_text(encoding="utf-8"))
    views = {m["declaration"]["view"] for m in declared_models(manifest) if m["declaration"]["origin"] == "core"}
    assert views == set(VIEWS)


@pytest.mark.parametrize("meta, needle", [
    ({"origin": "core", "view": "chart", "level": "entry", "keys": {"id": "x"}}, "view 'chart'"),
    ({"origin": "core", "view": "matrix", "level": "path", "keys": {"row": "path"}}, "keys.col"),
    ({"origin": "core", "view": "table", "level": "entry", "keys": {"id": "x", "from": "y"}}, "keys.from は view table では使わない"),
    ({"origin": "core", "view": "stat", "level": "path", "attach": "level9", "keys": {"value": "n"}}, "attach 'level9'"),
    ({"origin": "core", "view": "stat", "level": "path", "tags": ["dashboard"], "keys": {"value": "n"}}, "tags"),
    ({"origin": "mine", "view": "stat", "level": "path", "keys": {"value": "n"}}, "origin 'mine'"),
    ({"origin": "core", "view": "stat", "level": "path", "keys": {"value": "missing"}}, "列 'missing' が mart に無い"),
])
def test_declaration_check_rejects_bad_declarations(meta, needle):
    problems = check_declaration("m", meta, {"x", "y", "n", "path"})
    assert any(needle in p for p in problems), problems


def test_build_refuses_declaration_pointing_to_missing_column(repo: Path, tmp_path: Path):
    """repo 独自の mart が実在しない列を keys に書いたら build は失敗し、DuckDB は前の版のまま。"""
    import shutil

    bad = tmp_path / "bad-repo"
    shutil.copytree(repo, bad, symlinks=True)
    models = bad / ANALYSIS_DIR / "dbt" / "models" / "repo"
    (models / "mart_bad.sql").write_text("select count(*) as n from {{ ref('stg_entries') }}\n", encoding="utf-8")
    (models / "schema.yml").write_text(
        "version: 2\nmodels:\n  - name: mart_bad\n    meta:\n      abatlas: { origin: repo, view: stat, level: path, keys: { value: nope } }\n", encoding="utf-8")
    before = duckdb_path(bad).stat().st_mtime_ns
    with pytest.raises(SystemExit) as ex:
        build_repo(bad)
    assert "mart_bad: keys.value が指す列 'nope'" in str(ex.value)
    assert duckdb_path(bad).stat().st_mtime_ns == before
    assert not duckdb_path(bad).with_name(duckdb_path(bad).name + ".building").exists()
    # API が読む宣言 (DuckDB の中) も前の版のまま。dbt の作業先の manifest は書き換わっているが、API はそれを読まない
    assert "mart_bad" in (dbt_workdir(bad) / "target" / "manifest.json").read_text(encoding="utf-8")
    assert "mart_bad" not in [m["name"] for m in client(bad).get("/marts").json()]
    # 部分 build (--select) でも全宣言を検査する
    with pytest.raises(SystemExit) as ex2:
        build_repo(bad, select="mart_bad")
    assert "mart_bad" in str(ex2.value)
    assert duckdb_path(bad).stat().st_mtime_ns == before


# ---------------------------------------------------------------- API (画面と MCP が同じものを読む)

def test_marts_expose_tags_and_optional_keys(repo: Path):
    marts = {m["name"]: m for m in client(repo).get("/marts").json()}
    monitor = [n for n, m in marts.items() if "monitor" in (m["declaration"].get("tags") or [])]
    assert monitor, "監視画面に載せる mart が宣言されていない"
    for m in marts.values():
        cols = {c["name"] for c in m["columns"]}
        for k, col in m["declaration"]["keys"].items():
            assert col in cols, (m["name"], k, col)


def test_prefix_filter_folds_hierarchy(repo: Path):
    c = client(repo)
    table = next(m for m in c.get("/marts").json() if m["declaration"]["view"] == "table" and m["declaration"]["level"] == "entry" and "path" in m["declaration"]["keys"])
    col = table["declaration"]["keys"]["path"]
    everything = c.get(f"/marts/{table['name']}/rows").json()
    daily = c.get(f"/marts/{table['name']}/rows", params={f"{col}__prefix": "/daily/"}).json()
    weekly = c.get(f"/marts/{table['name']}/rows", params={f"{col}__prefix": "/weekly/"}).json()
    assert daily["total"] + weekly["total"] == everything["total"] and daily["total"] >= 1
    assert all(r[col].startswith("/daily/") for r in daily["rows"])
    assert c.get(f"/marts/{table['name']}/rows", params={"nope__prefix": "/"}).status_code == 400


def test_sequence_mart_orders_calls_before_their_io(repo: Path):
    c = client(repo)
    seq = next(m for m in c.get("/marts").json() if m["declaration"]["view"] == "sequence")
    k = seq["declaration"]["keys"]
    data = c.get(f"/marts/{seq['name']}/rows", params={k["group"]: "/daily/housekeeping"}).json()
    assert data["total"] >= 5
    order = [r[k["seq"]] for r in data["rows"]]
    assert order == sorted(order) and len(set(order)) == len(order), "seq は一意で昇順"
    first = data["rows"][0]
    assert first[k["from"]] == "daily.housekeeping", "最初のメッセージは入口のフレームからの呼び出し"
    # psycopg フレームの I/O (job_runs への書き込み) は、そのフレームへの呼び出しより後に来る
    by_to = {r[k["to"]]: r[k["seq"]] for r in data["rows"]}
    call_psycopg = next(r[k["seq"]] for r in data["rows"] if r["frame_id"] == "psycopg" and r["message_kind"] == "call")
    assert by_to["/rdb/ops_logs/job_runs"] > call_psycopg


# ---------------------------------------------------------------- 静的配信

def test_webapp_is_served_from_the_api_process(repo: Path):
    c = client(repo)
    r = c.get("/")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    assert "app.js" in r.text and "<script src=\"http" not in r.text, "外部 script を読まない"
    assert r.headers["content-security-policy"].startswith("default-src 'self'")
    assert c.get("/app.js").status_code == 200 and c.get("/css/base.css").status_code == 200
    assert c.get("/app.js").headers["cache-control"] == "no-cache", "upgrade 後に古い app.js を使い続けない (毎回再検証)"
    sub = c.get("/views/index.js")
    assert sub.status_code == 200 and sub.headers["cache-control"] == "no-cache", "サブディレクトリのモジュールも配り、毎回再検証させる"
    assert "javascript" in sub.headers["content-type"], "ES モジュールは JavaScript の MIME 型でないとブラウザが実行しない"
    assert c.get("/marts").status_code == 200, "API の経路は静的配信より優先"
    assert c.get("/", headers={"Host": "evil.example"}).status_code == 403, "webapp も Host 検査の中"


# ---------------------------------------------------------------- webapp の構造 (ビルド工程が無いので、崩れはここで止める)
# 層 (下から): lib < model < ui < views < pages < app.js。上の層は下の層 (と同じ層) だけを import できる。
# 検査は正規表現で足りる範囲に抑えている: import / export は行頭から書き、名前付きだけを使う (default と動的 import は使わない)。

WEBAPP_LAYERS = ["lib", "model", "ui", "views", "pages"]
CSS_ORDER = ["base", "shell", "ui", "views", "pages"]
_IMPORT_FROM = re.compile(r"^import\s+([^\"';]*?)\s*from\s*[\"']([^\"']+)[\"']", re.M)
_IMPORT_BARE = re.compile(r"^import\s*[\"']([^\"']+)[\"']", re.M)
_EXPORT_FROM = re.compile(r"^export\s+([^\"';]*?)\s*from\s*[\"']([^\"']+)[\"']", re.M)
_EXPORT_DECL = re.compile(r"^export\s+(?:async\s+function|function|const|let|class)\s+([A-Za-z_$][\w$]*)", re.M)
_EXPORT_LIST = re.compile(r"^export\s*\{([^}]*)\}", re.M)


def _layer_of(path: Path, root: Path) -> int:
    rel = path.relative_to(root)
    if rel.parts == ("app.js",):
        return len(WEBAPP_LAYERS)
    assert len(rel.parts) == 2 and rel.parts[0] in WEBAPP_LAYERS, f"{rel}: JS は app.js か、層のディレクトリ ({' / '.join(WEBAPP_LAYERS)}) の直下に置く"
    return WEBAPP_LAYERS.index(rel.parts[0])


def _imports(text: str) -> list[tuple[str, str | None]]:
    """(読み込み先, 束縛の書き方 | None) の一覧。import … from / 副作用だけの import / export … from を拾う。"""
    found = [(m.group(2), m.group(1)) for m in _IMPORT_FROM.finditer(text)]
    found += [(m.group(1), None) for m in _IMPORT_BARE.finditer(text)]
    found += [(m.group(2), m.group(1)) for m in _EXPORT_FROM.finditer(text)]
    return found


def _exports(text: str) -> set[str]:
    names = set(_EXPORT_DECL.findall(text))
    for m in _EXPORT_LIST.finditer(text):
        names |= {part.split(" as ")[-1].strip() for part in m.group(1).split(",") if part.strip()}
    return names


def webapp_module_problems(root: Path) -> list[str]:
    """webapp の JS が約束 (層の向き / 読み込み先と名前の実在 / 名前付きの静的 import だけ) を破っている箇所を返す。"""
    problems = []
    for path in sorted(root.rglob("*.js")):
        rel = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8")
        if re.search(r"\bimport\s*\(", text):
            problems.append(f"{rel}: 動的 import は使わない")
        if re.search(r"^export\s+default\b", text, re.M):
            problems.append(f"{rel}: export default は使わない (名前付きだけ)")
        found = _imports(text)
        # 拾い漏れを作らない: import / export の語は、行頭から始まる文か、コメントの行にだけ書ける
        for no, line in enumerate(text.split("\n"), start=1):
            if re.search(r"\b(?:import|export)\b", line) and not re.match(r"(?:import|export)\b|\s*(?://|/\*|\*)", line):
                problems.append(f"{rel}:{no}: 検査できない書き方 (import / export は行頭から書く。コード行の途中やコメントの外に書かない)")
        statements = len(re.findall(r"^import\b", text, re.M)) + len(re.findall(r"^export\b[^\n;]*\bfrom\s*[\"']", text, re.M))
        if statements != len(found):
            problems.append(f"{rel}: 検査できない書き方の import / export … from がある (名前付きで、読み込み先を引用符で書く)")
        for spec, bindings in found:
            if not spec.startswith(("./", "../")):
                problems.append(f"{rel}: 読み込み先 '{spec}' は相対パス (./ か ../) で書く")
                continue
            target = (path.parent / spec).resolve()
            if not target.is_file() or not target.is_relative_to(root.resolve()):
                problems.append(f"{rel}: 読み込み先 '{spec}' が無い")
                continue
            if _layer_of(target, root.resolve()) > _layer_of(path, root):
                problems.append(f"{rel}: 上の層 '{spec}' を読んでいる (層の向きは {' < '.join(WEBAPP_LAYERS)} < app.js)")
            if bindings is None:
                continue
            m = re.fullmatch(r"\{([^}]*)\}", bindings.strip())
            if not m:
                problems.append(f"{rel}: '{spec}' の import は名前付き ({{ a, b }}) だけにする")
                continue
            exported = _exports(target.read_text(encoding="utf-8"))
            for part in m.group(1).split(","):
                name = part.split(" as ")[0].strip()
                if name and name not in exported:
                    problems.append(f"{rel}: '{spec}' は {name} を export していない")
    return problems


def test_webapp_modules_keep_layer_direction_and_resolve():
    """層の依存の向き、読み込み先のファイルの実在、import した名前の実在 (ビルドが無いので打ち間違いはここで止める)。"""
    assert (WEBAPP_DIR / "app.js").is_file()
    assert webapp_module_problems(WEBAPP_DIR) == []


@pytest.mark.parametrize("rel, code, needle", [
    ("lib/x.js", 'import { model } from "../model/catalog.js";\n', "上の層 '../model/catalog.js'"),
    ("ui/x.js", 'import "../views/index.js";\n', "上の層 '../views/index.js'"),
    ("views/x.js", 'export { pageMarts } from "../pages/marts.js";\n', "上の層 '../pages/marts.js'"),
    ("pages/x.js", 'import { route } from "../app.js";\n', "上の層 '../app.js'"),
    ("pages/x.js", 'import { titleOff } from "../model/catalog.js";\n', "titleOff を export していない"),
    ("pages/x.js", 'import { el } from "../lib/dmo.js";\n', "'../lib/dmo.js' が無い"),
    ("pages/x.js", 'import { el } from "https://cdn.example/dom.js";\n', "相対パス"),
    ("pages/x.js", 'import dom from "../lib/dom.js";\n', "名前付き"),
    ("pages/x.js", 'import * as dom from "../lib/dom.js";\n', "名前付き"),
    ("pages/x.js", 'const m = await import("../lib/dom.js");\n', "動的 import"),
    ("lib/x.js", "export default function x() {}\n", "export default"),
    ("pages/x.js", '  import { route } from "../app.js";\n', "検査できない書き方"),
    ("pages/x.js", 'const y = 1; import { route } from "../app.js";\n', "検査できない書き方"),
    ("pages/x.js", 'import { route } from `../app.js`;\n', "検査できない書き方"),
])
def test_webapp_module_check_catches_violations(tmp_path: Path, rel, code, needle):
    """検査そのものの検査: 実物の写しに違反を 1 つ足すと、その違反が報告される (写しは違反なしから始まる)。"""
    import shutil

    root = tmp_path / "webapp"
    shutil.copytree(WEBAPP_DIR, root)
    assert webapp_module_problems(root) == []
    (root / rel).write_text(code, encoding="utf-8")
    problems = webapp_module_problems(root)
    assert any(needle in p for p in problems), problems


def webapp_external_url_problems(root: Path) -> list[str]:
    """webapp の全ファイルから、外部の URL (http(s):// と、プロトコル相対の //host/…) を書いている箇所を返す。SVG の名前空間だけ許す。

    うっかり外部を読む書き方を止めるための検査で、文字列の検査なので、URL を部品から組み立てる書き方 (例: "/" + "/" + host) までは追えない。
    最後の砦は応答の CSP (default-src 'self')。ブラウザが外部への通信を止める。
    """
    problems = []
    for p in sorted(x for x in root.rglob("*") if x.is_file()):
        rel = p.relative_to(root).as_posix()
        rest = p.read_text(encoding="utf-8").replace("http://www.w3.org/2000/svg", "")
        if re.search(r"https?://", rest, re.I):
            problems.append(f"{rel}: 外部の URL (http:// / https://) を書かない")
        # 引用符 (テンプレート文字列も)・url( ・属性の = の直後の // 。直後が空白 (コメント) でなければ URL とみなす (//host、//${host}、"//" + host)
        if re.search(r"""["'`(=]\s*//[^\s/*]""", rest):
            problems.append(f"{rel}: プロトコル相対の URL (//host/…) を書かない (コメントなら // の後ろに空白を置く)")
    return problems


@pytest.mark.parametrize("rel, code", [
    ("lib/x.js", 'fetch("https://cdn.example/x.js");\n'),
    ("lib/x.js", "fetch('http://cdn.example/x.js');\n"),
    ("lib/x.js", 'fetch("//cdn.example/x.js");\n'),
    ("lib/x.js", "fetch(`//cdn.example/${name}.js`);\n"),
    ("lib/x.js", 'const host = "cdn.example"; fetch(`//${host}/x.js`);\n'),
    ("lib/x.js", 'const host = "cdn.example"; fetch("//" + host + "/x.js");\n'),
    ("lib/x.js", 'fetch("HTTPS://cdn.example/x.js");\n'),
    ("lib/x.js", 'fetch("Http://cdn.example/x.js");\n'),
    ("css/x.css", ".a { background: url(//cdn.example/a.png); }\n"),
    ("css/x.css", ".a { background: url( '//cdn.example/a.png' ); }\n"),
    ("extra.html", "<img src=//cdn.example/a.png>\n"),
])
def test_webapp_external_url_check_catches_violations(tmp_path: Path, rel, code):
    import shutil

    root = tmp_path / "webapp"
    shutil.copytree(WEBAPP_DIR, root)
    assert webapp_external_url_problems(root) == []
    (root / rel).write_text(code, encoding="utf-8")
    assert [p for p in webapp_external_url_problems(root) if p.startswith(rel)], rel


def test_webapp_bundle_is_self_contained():
    """外部の URL を読まない (CSP default-src 'self')。全ファイルを見る。"""
    assert len([p for p in WEBAPP_DIR.rglob("*") if p.is_file()]) > 20
    assert webapp_external_url_problems(WEBAPP_DIR) == []
    html = (WEBAPP_DIR / "index.html").read_text(encoding="utf-8")
    assert re.findall(r"<script\b[^>]*>", html) == ['<script type="module" src="app.js">'], "script は起動のモジュール 1 つだけ (inline も足さない)"
    assert "style=" not in html and "<style" not in html, "inline の style を使わない"
    for ref in re.findall(r"""(?:href|src)=["']([^"'#][^"']*)["']""", html):
        assert (WEBAPP_DIR / ref).is_file(), f"index.html が読む {ref} が無い"


def test_webapp_css_is_loaded_in_layer_order():
    """CSS は css/ の 5 ファイルだけ。index.html がこの順に読む (同じ詳細度の上書きは読み込み順で決まる)。"""
    html = (WEBAPP_DIR / "index.html").read_text(encoding="utf-8")
    links = re.findall(r"""<link\s+rel="stylesheet"\s+href="([^"]+)">""", html)
    assert links == [f"css/{n}.css" for n in CSS_ORDER]
    assert html.count("<link") == len(links), "stylesheet 以外の <link> や、検査できない書き方の <link> が無い"
    assert sorted(p.relative_to(WEBAPP_DIR).as_posix() for p in WEBAPP_DIR.rglob("*.css")) == sorted(links), "css/ 以外に CSS を置かない。css/ の全ファイルをちょうど 1 回ずつ読む"
    for p in WEBAPP_DIR.rglob("*.css"):
        assert "@import" not in p.read_text(encoding="utf-8"), f"{p}: CSS から別の CSS を読まない (順序は index.html だけで決める)"


def test_under_filter_matches_self_and_descendants(repo: Path):
    """`列__under=/daily` は /daily 自身と /daily/... の両方 (入口が子も持つ節のため)。/daily2 は含まない。"""
    c = client(repo)
    table = next(m for m in c.get("/marts").json() if m["declaration"]["view"] == "table" and m["declaration"]["level"] == "entry" and "path" in m["declaration"]["keys"])
    col = table["declaration"]["keys"]["path"]
    under = c.get(f"/marts/{table['name']}/rows", params={f"{col}__under": "/daily"}).json()
    assert under["total"] >= 1 and all(r[col] == "/daily" or r[col].startswith("/daily/") for r in under["rows"])
    exact = c.get(f"/marts/{table['name']}/rows", params={f"{col}__under": "/daily/housekeeping"}).json()
    assert [r[col] for r in exact["rows"]] == ["/daily/housekeeping"]
    assert c.get(f"/marts/{table['name']}/rows", params={f"{col}__under": "/dai"}).json()["total"] == 0


def test_declarations_are_published_inside_the_duckdb(repo: Path):
    """宣言は集計表と同じファイル (DuckDB) にある。API が 1 接続で宣言と表を読むので、置き換えの途中でも新旧が混ざらない。"""
    with duckdb.connect(str(duckdb_path(repo)), read_only=True) as con:
        decls = read_declarations(con)
        sch, tbl = DECLARATIONS_TABLE
        assert con.execute(f'select count(*) from "{sch}"."{tbl}"').fetchone()[0] == len(decls) >= 10
    api = {m["name"]: m["declaration"] for m in client(repo).get("/marts").json()}
    assert api == {n: d["declaration"] for n, d in decls.items()}
    assert not (duckdb_path(repo).parent / "manifest.json").exists()


def test_empty_declaration_is_reported_not_skipped():
    manifest = {"nodes": {"model.x.mart_empty": {"resource_type": "model", "name": "mart_empty", "meta": {"abatlas": {}}, "schema": "mart"}}}
    models = declared_models(manifest)
    assert [m["name"] for m in models] == ["mart_empty"]
    assert any("view 'None'" in p for p in check_declaration("mart_empty", models[0]["declaration"], None))


@pytest.mark.parametrize("path, ok", [("/daily/job", True), ("/a", True), ("/daily//job", False), ("/daily/", False), ("daily/job", False), ("/", False)])
def test_entry_path_must_be_slash_separated_without_empty_segments(path, ok):
    from abatlas.schemas import schema_errors

    cand = {"format_version": 1, "id": "x", "path": path, "layer": "scheduler", "source": {"file": "f", "line": 1}}
    assert (schema_errors("entry-candidate", cand) == []) == ok, path


def test_sequence_seq_is_dense_per_entry(repo: Path):
    c = client(repo)
    seq = next(m for m in c.get("/marts").json() if m["declaration"]["view"] == "sequence")
    k = seq["declaration"]["keys"]
    data = c.get(f"/marts/{seq['name']}/rows", params={k["group"]: "/daily/housekeeping"}).json()
    assert [r[k["seq"]] for r in data["rows"]] == list(range(1, data["total"] + 1)), "入口ごとの連番 (I/O の件数に依らず衝突しない)"


def test_every_scoped_view_declares_path_for_hierarchy_pages(repo: Path):
    """階層ページで節に絞れる core mart は keys.path / row / group のどれかを宣言している (列名の決め打ちに頼らない)。分析の観点の表は、階層ページに貼らないので見ない。"""
    for m in client(repo).get("/marts").json():
        k = m["declaration"]["keys"]
        if m["declaration"]["origin"] == "core" and m["declaration"]["view"] in ("graph", "sequence", "tree") and m["declaration"].get("subject") != "aspect":
            assert "path" in k, m["name"]


def test_section_picker_groups_analyzed_paths_with_profile_layers(repo: Path):
    """断面図の候補は処理を持つ入口だけ。処理が複数あっても 1 候補で、その層をプロファイルの面に置ける。"""
    c = client(repo)
    tree = next(m for m in c.get("/marts").json()
                if m["declaration"].get("subject") == "entry" and m["declaration"]["view"] == "tree")
    keys = tree["declaration"]["keys"]
    root = f"/marts/{tree['name']}"
    choices = c.get(f"{root}/groups", params={"by": keys["group"], "order": "key", "limit": 1}).json()
    assert choices["total"] == 1
    path = choices["groups"][0]["key"]
    assert path == "/daily/housekeeping"
    frames = c.get(f"{root}/rows", params={keys["group"]: path}).json()["rows"]
    assert len(frames) > 1
    layers = {layer["id"] for layer in c.get("/meta").json()["profile"]["layers"]}
    assert {f[keys["tag"]] for f in frames} <= layers


def test_3d_scene_distinguishes_boundary_layer_and_external_target(repo: Path):
    c = client(repo)
    meta = c.get("/meta").json()
    layers = {layer["id"]: layer for layer in meta["profile"]["layers"]}
    assert layers["external"]["role"] == "boundary" and layers["external"]["tier"] == "job"
    assert meta["resource_kinds"]["external_api"]["label"] == meta["terms"]["external"]
    mart = next(m for m in c.get("/marts").json() if m["declaration"]["view"] == "layers")
    keys = mart["declaration"]["keys"]
    edges = {(r[keys["from"]], r[keys["to"]]) for r in c.get(f"/marts/{mart['name']}/rows").json()["rows"]}
    assert {("shell", "external"), ("external", "/rdb"), ("program", "/external_api")} <= edges


def test_route_can_be_traced_from_sequence_to_tree(repo: Path):
    """経路の画面の前提: sequence の keys.node が tree の keys.id と対応し、読み書きを起こした処理から入口まで親を遡れる。根拠と定義場所は file:line。"""
    c = client(repo)
    marts = c.get("/marts").json()
    seq = next(m for m in marts if m["declaration"]["view"] == "sequence" and "node" in m["declaration"]["keys"])
    tree = next(m for m in marts if m["declaration"]["view"] == "tree" and "group" in m["declaration"]["keys"])
    sk, tk = seq["declaration"]["keys"], tree["declaration"]["keys"]
    assert {"evidence"} <= set(sk) and {"source", "tag"} <= set(tk)
    path = "/daily/housekeeping"
    msgs = c.get(f"/marts/{seq['name']}/rows", params={sk["group"]: path}).json()["rows"]
    frames = {r[tk["id"]]: r for r in c.get(f"/marts/{tree['name']}/rows", params={tk["group"]: path}).json()["rows"]}
    io = next(m for m in msgs if m[sk["to"]] == "/rdb/ops_logs/job_runs")
    with_ev = [m[sk["evidence"]] for m in msgs if m[sk["evidence"]]]
    assert with_ev and all(re.fullmatch(r"[^:]+:\d+(, [^:]+:\d+)*", e) for e in with_ev), with_ev
    assert io[sk["evidence"]] is None, "根拠の無い主張 (不明) は、根拠の場所が空"
    chain, cur = [], io[sk["node"]]
    while cur:
        chain.append(cur)
        cur = frames[cur][tk["parent"]] or None
    assert chain == ["psycopg", "run_sh", "flow"], "読み書きした処理から、入口の処理 (親の無い処理) まで遡れる"
    assert all(re.fullmatch(r".+:\d+", f[tk["source"]]) and f[tk["tag"]] for f in frames.values())


def test_radial_layout_keeps_tiers_resources_and_boundaries_distinct():
    """同心円は所属を表す。二つの external と、以前の結果にだけある層も別の面に置ける。"""
    import shutil
    import subprocess

    node = shutil.which("node")
    if not node:
        pytest.skip("node が無い")
    source = (WEBAPP_DIR / "views/radial-layout.js").read_text(encoding="utf-8")
    source += (WEBAPP_DIR / "views/call-mesh.js").read_text(encoding="utf-8")
    checks = """
import assert from "node:assert/strict";
const layers = [{id: "page", tier: "frontend"}, {id: "part", tier: "frontend"},
                {id: "query", tier: "backend"}, {id: "external", tier: "backend"}];
const kinds = [["rdb", "RDB"], ["queue", "Queue"], ["external_api", "external API"]];
const layout = (known) => radialLayout(layers, kinds, known, {unknown: "?", store: "datastore", external: "external"});
const {discs, nodes} = layout([]);
const app = discs.filter((d) => d.type === "app");
assert.deepEqual(app.map((d) => d.tier), ["frontend", "backend"]);
assert.ok(app[0].rx > app[1].rx);
assert.ok(discs.every((d, i) => i === 0 || discs[i - 1].h - discs[i - 1].thickness > d.h));
assert.equal(app[0].thickness, app[1].thickness);
for (const d of discs) {
  assert.ok(d.thickness > 0);
  for (const f of d.faces) {
    const face = nodes.get(f.id);
    for (const [x, h, z] of visibleWallParts(f, 0.7).flatMap((piece) => piece.points)) {
      assert.ok(Math.abs(Math.hypot(x - d.x, z - d.z) - d.rx) < 1e-8);
      assert.ok(h === face.bottom || h === face.h);
    }
  }
}
assert.deepEqual(app.map((d) => d.faces.map((f) => f.id)), [["page", "part"], ["query", "external"]]);
// 1 層で筒を一周する場合も、視点側と背面を分け、投影した面同士の打ち消しを防ぐ。
const only = radialLayout([{id:"one", tier:"app"}], [], [], {}).nodes.get("one");
for (const yaw of [-Math.PI, 0, 1.4]) {
  const pieces = visibleWallParts(only, yaw);
  assert.ok(pieces.some((p) => p.front) && pieces.some((p) => !p.front));
  for (const p of pieces) for (const [x, h, z] of p.points) {
    const depth = x * Math.sin(yaw) + z * Math.cos(yaw);
    assert.ok(p.front ? depth >= -1e-8 : depth <= 1e-8);
  }
}
const store = discs.find((d) => d.type === "store"), remote = discs.find((d) => d.type === "remote");
assert.ok(store.h < app[0].h - app[0].thickness);
assert.deepEqual(discs.map((d) => d.tier), ["frontend", "backend", "datastore", "external"]);
assert.ok(discs.every((d) => d.x === 0 && d.z === 0));
assert.ok(remote.h < store.h - store.thickness && remote.rx > app[0].rx && store.rx < app[1].rx);
const legacy = layout(["legacy"]).discs;
assert.deepEqual(legacy.map((d) => d.type), ["app", "app", "app", "store", "remote"]);
assert.equal(legacy.at(-1).rx, Math.max(...legacy.map((d) => d.rx)));
const noExternal = radialLayout(layers, [["rdb", "RDB"]], [], {}).discs;
assert.deepEqual(noExternal.map((d) => d.type), ["app", "app", "store"]);
const noStore = radialLayout(layers, [["external_api", "API"]], [], {}).discs;
assert.deepEqual(noStore.map((d) => d.type), ["app", "app", "remote"]);
assert.equal(nodes.get("external").tier, "backend");
assert.equal(nodes.get("/external_api").tier, "external");
assert.equal(layout(["legacy"]).nodes.get("legacy").tier, "?");
assert.deepEqual(store.faces.map((f) => f.id), ["/rdb", "/queue"]);
const resource = "/rdb/shared/table";
function entry(path) {
  const frames = new Map([
    ["1", {id: "1", parent: null, name: "page", layer: "page"}],
    ["2", {id: "2", parent: "1", name: "lookup", layer: "query"}],
  ]);
  const targets = new Map([[resource, {path: resource, origins: new Map([["2", true]])}]]);
  return {path, section: {frames, targets}};
}
const mesh = callMesh([entry("/a"), entry("/b")]);
assert.equal(mesh.dots.size, 5);
assert.equal(mesh.edges.length, 4);
const root = JSON.stringify(["/a", "1"]), child = JSON.stringify(["/a", "2"]);
assert.ok(mesh.dots.get(root).root && !mesh.dots.get(child).root);
assert.ok(mesh.edges.some((e) => e.from === root && e.to === child));
assert.ok(mesh.edges.some((e) => e.from === child && e.to === resource && e.unknown));
assert.equal(traceSelection(mesh, [resource]).lines.size, 4);
assert.equal(traceSelection(mesh, [child]).lines.size, 2);
for (const {id, area} of mesh.dots.values()) {
  const face = nodes.get(area), point = pointOnFace(face, id);
  assert.deepEqual(point, pointOnFace(face, id));
  const dx = (point[0] - face.x) / face.rx, dz = (point[2] - face.z) / face.rz;
  const r = Math.hypot(dx, dz), a = Math.atan2(dz, dx);
  const delta = (a - face.start + 2 * Math.PI) % (2 * Math.PI);
  assert.ok(delta < face.end - face.start);
  assert.ok(Math.abs(r - 1) < 1e-10 && point[1] > face.bottom && point[1] < face.h);
}
const tree = entry("/a");
tree.section.frames.set("3", {id:"3", parent:"2", name:"nested", layer:"query"});
tree.section.frames.set("4", {id:"4", parent:"3", name:"boundary", layer:"external"});
tree.section.frames.set("5", {id:"5", parent:"4", name:"returnQuery", layer:"query"});
const expanded = callMesh([tree, entry("/b")]);
const detail = radialLayout(layers, kinds, ["legacy"], {unknown:"?"}, "backend");
assert.deepEqual([...detail.nodes.keys()], ["query", "external"]);
assert.ok(detail.discs.every((d) => d.type === "layer" && d.tier === "backend" && d.faces.length === 1));
assert.ok(detail.discs[0].rx > detail.discs[1].rx && detail.discs[0].h - detail.discs[0].thickness > detail.discs[1].h);
const custom = [{id:"assigned",tier:"unknown"}, {id:"unassigned"}];
const customOverview = radialLayout(custom, [], ["legacy"], {unknown:"unknown"});
assert.deepEqual(customOverview.discs.map(d => d.declared), [true, false]);
assert.deepEqual([...radialLayout(custom, [], ["legacy"], {unknown:"unknown"}, "unknown").nodes.keys()], ["assigned"]);
const scoped = layerMesh(expanded, detail.nodes);
const panels = pathPanels(detail.nodes, scoped.dots);
assert.deepEqual(panels.paths, ["/a", "/b"]);
const queryPanels = panels.byLayer.get("query"), externalPanels = panels.byLayer.get("external");
assert.deepEqual([...externalPanels.keys()], ["/a"]);
assert.equal(queryPanels.get("/a").start, externalPanels.get("/a").start);
assert.ok(queryPanels.get("/a").end < queryPanels.get("/b").start);
for (const dot of scoped.dots.values()) {
  const face = panels.byLayer.get(dot.area).get(dot.entry);
  const [x, h, z] = pointOnFace(face, dot.id);
  assert.ok(Math.abs(Math.hypot(x,z) - face.rx) < 1e-8 && h > face.bottom && h < face.h);
  const delta = (Math.atan2(z,x) - face.start + 2*Math.PI) % (2*Math.PI);
  assert.ok(delta <= face.end - face.start);
}
assert.equal(pathPanels(detail.nodes, new Map()).byLayer.get("query").size, 0);
assert.equal(scoped.dots.size, 5);
assert.deepEqual(scoped.edges.map((e) => [scoped.dots.get(e.from).area, scoped.dots.get(e.to).area]), [
  ["query","query"], ["query","external"], ["external","query"]]);
const front = radialLayout(layers, kinds, [], {}, "frontend");
assert.ok(front.nodes.has("part"));
assert.equal(layerMesh(expanded, front.nodes).edges.length, 0);
assert.equal(layerMesh(expanded, new Map()).dots.size, 0);
assert.deepEqual(callerChain(expanded, JSON.stringify(["/a", "4"])).map((p) => p.name), ["page","lookup","nested","boundary"]);
// 複数の RDB の点をまとめて選ぶ。同じ入口にある兄弟の枝と RDB に触れない入口は薄いまま。
const other = entry("/c"), table2 = "/rdb/shared/orders";
other.section.targets.clear();
tree.section.targets.set(table2, {path: table2, origins: new Map([["4", false]])});
const mixed = callMesh([tree, entry("/b"), other]);
const rdb = traceSelection(mixed, [resource, table2]);
assert.equal(rdb.lines.size, 7);
assert.equal(rdb.keep.size, 8);
assert.ok(rdb.keep.has(JSON.stringify(["/a","1"])) && rdb.keep.has(JSON.stringify(["/b","1"])));
assert.ok(!rdb.keep.has(JSON.stringify(["/c","1"])) && !rdb.keep.has(JSON.stringify(["/a","5"])));
assert.ok([...rdb.lines].some((e) => e.unknown));
assert.equal(traceSelection(mixed, []).keep.size, 0);
// 選んだ処理の直接の読み書きは残し、その資源を共有する別入口には遡らない。
const one = traceSelection(mixed, [child]);
assert.ok(one.keep.has(resource) && !one.keep.has(JSON.stringify(["/b","2"])));
// 図の点と「段全体」の点一覧では、一覧の範囲だけが違い、面・点・線の強調は一致する。
const detailView = { nodes: detail.nodes, mesh: scoped, fullMesh: expanded, panels };
const fromDot = resolveTierSelection(detailView, {area: "query", point: child, path: "/a"});
const fromPicker = resolveTierSelection(detailView, {area: "query", point: child});
assert.deepEqual(fromDot.chosenFaces, new Set([queryPanels.get("/a")]));
assert.deepEqual(fromPicker.chosenFaces, fromDot.chosenFaces);
assert.deepEqual(fromPicker.trace, fromDot.trace);
assert.deepEqual(fromPicker.visitedFaces, fromDot.visitedFaces);
assert.ok(!fromPicker.visitedFaces.has(queryPanels.get("/b")));
assert.ok(fromPicker.members.length > fromDot.members.length);
const wholePath = resolveTierSelection(detailView, {path: "/a"});
assert.deepEqual(wholePath.chosenFaces, new Set([queryPanels.get("/a"), externalPanels.get("/a")]));
assert.equal(resolveTierSelection(detailView, {path: "/removed"}).trace, null);
const allView = {nodes, mesh: mixed, fullMesh: mixed, panels: null};
const rdbSelection = resolveTierSelection(allView, {area: "/rdb"});
assert.deepEqual(rdbSelection.trace, rdb);
assert.deepEqual(rdbSelection.roots, new Set(["/a","/b"]));
assert.deepEqual(rdbSelection.chosenFaces, new Set([nodes.get("/rdb")]));
assert.equal(rdbSelection.visibleLineCount, 7);
assert.deepEqual(resolveTierSelection(allView, {area: "part"}).trace.keep, new Set());
const satellite = nodes.get("/external_api"), endpoint = pointOnFace(satellite, "/external_api/service.example/orders");
assert.ok(Math.abs(Math.hypot(endpoint[0] - remote.x, endpoint[2] - remote.z) - remote.rx) < 1e-8);
assert.ok(endpoint[1] > satellite.bottom && endpoint[1] < satellite.h);
"""
    subprocess.run([node, "--input-type=module"], input=source + checks, text=True, check=True)


def test_webapp_modules_parse_as_es_modules():
    """node があれば、全モジュールの構文を検査する (ビルドが無いので、構文エラーは画面を開くまで分からない)。node が無い環境では飛ばす。"""
    import shutil
    import subprocess

    node = shutil.which("node")
    if not node:
        pytest.skip("node が無い")
    for p in sorted(WEBAPP_DIR.rglob("*.js")):
        r = subprocess.run([node, "--input-type=module", "--check"], input=p.read_text(encoding="utf-8"), capture_output=True, text=True)
        assert r.returncode == 0, f"{p.relative_to(WEBAPP_DIR)}: {r.stderr[:300]}"


def test_origin_must_match_model_directory():
    """宣言の origin (集計表の持ち主) は、定義の置き場所 (models/core | profile | repo) と合っていなければならない。"""
    from abatlas.declarations import declared_models, origin_problems

    def node(name, path, origin):
        return {"resource_type": "model", "name": name, "original_file_path": path, "schema": "main",
                "meta": {"abatlas": {"origin": origin, "view": "stat", "level": "path", "keys": {"value": "n"}}}}

    manifest = {"nodes": {
        "a": node("mart_a", "models/core/mart_a.sql", "core"),
        "b": node("mart_b", "models/repo/mart_b.sql", "core"),        # 独自の集計表なのに core と書いた
        "c": node("mart_c", "models/profile/sub/mart_c.sql", "profile"),
        "d": node("mart_d", "models/other/mart_d.sql", "repo"),       # 3 つのどれでもない置き場所は見ない
        "e": {**node("mart_e", "", "repo")},                          # 置き場所が分からないものも見ない
    }}
    models = declared_models(manifest)
    assert {m["name"]: m["dir"] for m in models} == {"mart_a": "core", "mart_b": "repo", "mart_c": "profile", "mart_d": "other", "mart_e": None}
    problems = origin_problems(models)
    assert len(problems) == 1 and "mart_b" in problems[0] and "models/repo/" in problems[0], problems


def test_check_manifest_rejects_origin_mismatch(tmp_path):
    """集計の検査 (check_manifest) を通しても、origin と置き場所の食い違いが指摘になる (呼び出しが外れたら、ここで落ちる)。"""
    import json

    from abatlas.declarations import check_manifest

    def node(name, path, origin):
        return {"resource_type": "model", "name": name, "original_file_path": path, "schema": "main",
                "meta": {"abatlas": {"origin": origin, "view": "stat", "level": "path", "keys": {"value": "n"}}}}

    mf = tmp_path / "manifest.json"
    mf.write_text(json.dumps({"nodes": {"a": node("mart_a", "models/core/mart_a.sql", "core"), "b": node("mart_b", "models/repo/mart_b.sql", "core")}}), encoding="utf-8")
    problems = check_manifest(mf, None)
    assert any("mart_b" in p and "models/repo/" in p for p in problems), problems
    mf.write_text(json.dumps({"nodes": {"a": node("mart_a", "models/core/mart_a.sql", "core"), "b": node("mart_b", "models/repo/mart_b.sql", "repo")}}), encoding="utf-8")
    assert check_manifest(mf, None) == []


def _bare_null_children(text: str) -> list[int]:
    """replaceChildren / append / prepend の引数に、null がそのまま入りうる所の行番号 (複数行の呼び出しも見る)。"""
    out = []
    for m in re.finditer(r"\.(replaceChildren|append|prepend)\(", text):
        depth, args, cur = 0, [], ""
        for ch in text[m.end():]:
            if ch in "([{":
                depth += 1
            elif ch in ")]}":
                if depth == 0:
                    break
                depth -= 1
            if ch == "," and depth == 0:
                args.append(cur)
                cur = ""
            else:
                cur += ch
        args.append(cur)
        if any(re.search(r":\s*null\s*$", a) or a.strip() == "null" for a in args):
            out.append(text.count("\n", 0, m.start()) + 1)
    return out


def test_replace_children_never_gets_a_bare_null():
    """replaceChildren と append は、null を「null」という文字にする (el() は捨てる)。条件で出し分ける子は、並びに展開して渡す。"""
    assert _bare_null_children("x.replaceChildren(\n  a > b ? el('p') : null,\n  render(m))") == [1], "複数行の呼び出しも見つける"
    assert _bare_null_children("x.replaceChildren(...(a ? [el('p')] : []), el('div', null, a ? b : null))") == [], "el() の中の null と、展開した並びは、当たらない"
    bad = [f"{p.relative_to(WEBAPP_DIR)}:{n}" for p in sorted(WEBAPP_DIR.rglob("*.js")) for n in _bare_null_children(p.read_text(encoding="utf-8"))]
    assert bad == [], "null を、そのまま子として渡している (文字の null が画面に出る)"
