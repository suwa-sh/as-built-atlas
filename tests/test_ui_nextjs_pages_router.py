"""ui-nextjs プロファイルの Pages Router (pages ディレクトリ) と middleware の抽出器を、小さな見本で確かめる。

App Router の抽出器と同じ印で、同じ URL は同じ階層と id になる。両方が同居するリポジトリ (移行の途中) でも、
id はぶつからず、包む関係 (within) は、ソースの置き場から決まる (_app は pages の下だけを包む)。
"""

import json
from pathlib import Path

import pytest
import yaml

from abatlas.enumerate import enumerate_entries
from abatlas.extractors.file_glob import extract
from abatlas.layout import init_repo
from abatlas.schemas import schema_errors
from abatlas.validate import validate_entry_list, validate_profile

REPO_ROOT = Path(__file__).resolve().parent.parent
PROFILE = REPO_ROOT / "profiles" / "ui-nextjs" / "profile.yaml"
PAGES_ROUTER = ("next-pages-router", "next-pages-router-index", "next-pages-app")

# Pages Router の置き場の見本 (ファイル → (階層パス, id))
PAGES = {
    "pages/index.tsx": ("/(root)", "root_r"),
    "pages/dashboard.tsx": ("/dashboard", "dashboard"),
    "pages/documents/index.tsx": ("/documents", "documents"),
    "pages/documents/[id]/index.tsx": ("/documents/[id]", "documents.id_d"),
    "pages/documents/[id]/redactions/[jobId].tsx": ("/documents/[id]/redactions/[jobId]", "documents.id_d.redactions.jobId_d"),
    "pages/documents/tree/[...name].tsx": ("/documents/tree/[...name]", "documents.tree.name_c"),
    "pages/help/[[...slug]].tsx": ("/help/[[...slug]]", "help.slug_o"),
    "pages/settings/billing.tsx": ("/settings/billing", "settings.billing"),  # 同じ名前のフォルダと同居する
    "pages/settings/billing/invoices.tsx": ("/settings/billing/invoices", "settings.billing.invoices"),
    "pages/index/about.tsx": ("/index/about", "index.about"),  # index という名前のフォルダは段に残す (落とすのはファイル名の index だけ)
    "pages/my_page.tsx": ("/my_page", "my__page"),
}
NOT_PAGES = [
    "pages/_app.tsx",  # 枠 (next-pages-app)
    "pages/_document.tsx",
    "pages/_error.tsx",
    "pages/404.tsx",
    "pages/500.tsx",
    "pages/api/teams/[teamId]/documents/index.ts",  # API の受け口は入口にしない (画面から辿った途中の段)
    "pages/api/health.ts",
    "ee/features/workflows/pages/workflow-new.tsx",  # scope の直下の pages ではない (ルーティングと関係ない)
]
CONTENT = {
    "pages/documents/[id]/index.tsx": "export default function Doc() { return null; }\nexport async function getServerSideProps(ctx) { return { props: {} }; }\n",
    "pages/dashboard.tsx": "import x from 'y';\n\nexport default function Dashboard() { return null; }\nexport const getStaticProps = async () => ({ props: {} });\n",
    "pages/help/[[...slug]].tsx": "function Help() { return null; }\nHelp.getInitialProps = async () => ({});\nexport default Help;\n",
}


def _extractor(name: str) -> dict:
    return next(e for e in yaml.safe_load(PROFILE.read_text(encoding="utf-8"))["extractors"] if e["name"] == name)


def _write(root: Path, rel: str, text: str = "export default function () { return null; }\n") -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


@pytest.fixture()
def site(tmp_path: Path) -> Path:
    for rel in [*PAGES, *NOT_PAGES]:
        _write(tmp_path, rel, CONTENT.get(rel, "export default function () { return null; }\n"))
    return tmp_path


def _run(scope: Path, name: str, capsys) -> list[dict]:
    ex = _extractor(name)
    extract(scope, ex["params"], ex["layer"])
    return [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]


def test_pages_router_files_become_url_shaped_entries(site: Path, capsys):
    recs = _run(site, "next-pages-router", capsys) + _run(site, "next-pages-router-index", capsys)
    assert all(schema_errors("entry-candidate", r) == [] for r in recs)
    assert {r["source"]["file"]: (r["path"], r["id"]) for r in recs} == PAGES, "_app・_document・_error・404・500・api と、直下でない pages は画面にしない"
    by_file = {r["source"]["file"]: r for r in recs}
    assert by_file["pages/dashboard.tsx"]["source"]["line"] == 3, "出典の行は export default の行"
    assert by_file["pages/documents/[id]/index.tsx"]["attributes"]["server_props"] is True
    assert by_file["pages/dashboard.tsx"]["attributes"]["static_props"] is True and by_file["pages/dashboard.tsx"]["attributes"]["server_props"] is False
    assert by_file["pages/help/[[...slug]].tsx"]["attributes"]["initial_props"] is True


def test_pages_router_ids_match_app_router_marks(tmp_path: Path, capsys):
    """同じ URL は、App Router でも Pages Router でも、同じ階層と id になる (移行しても、入口の id が変わらない)。"""
    pairs = {
        "src/app/page.tsx": "pages/index.tsx",
        "src/app/blog/[id]/page.tsx": "pages/blog/[id].tsx",
        "src/app/docs/[...all]/page.tsx": "pages/docs/[...all].tsx",
        "src/app/help/[[...all]]/page.tsx": "pages/help/[[...all]]/index.tsx",
        "src/app/my_page/page.tsx": "pages/my_page.tsx",
    }
    app, pages = tmp_path / "a", tmp_path / "p"
    for a, p in pairs.items():
        _write(app, a)
        _write(pages, p)
    by_app = {r["source"]["file"]: (r["path"], r["id"]) for r in _run(app, "next-pages", capsys)}
    by_pages = {r["source"]["file"]: (r["path"], r["id"]) for r in _run(pages, "next-pages-router", capsys) + _run(pages, "next-pages-router-index", capsys)}
    assert {by_app[a]: by_pages[p] for a, p in pairs.items()} == {by_app[a]: by_app[a] for a in pairs}


def test_app_and_middleware_wrappers(site: Path, capsys):
    _write(site, "middleware.ts", "import { NextResponse } from 'next/server';\n\nexport async function middleware(req) { return NextResponse.next(); }\n")
    app = _run(site, "next-pages-app", capsys)
    assert [(r["source"]["file"], r["path"], r["id"], r["layer"]) for r in app] == [("pages/_app.tsx", "/(layout)/_app", "layout_l.app_a", "layout")]
    mw = _run(site, "next-middleware", capsys)
    assert [(r["source"], r["path"], r["id"]) for r in mw] == [({"file": "middleware.ts", "line": 3}, "/(layout)/_middleware", "layout_l.middleware_a")]


@pytest.fixture()
def mixed(tmp_path_factory):
    """app と pages の両方がある (移行の途中) リポジトリと、すべての抽出器を書いた入口の一覧。"""
    target = tmp_path_factory.mktemp("mixed-target")
    for rel in [*PAGES, *NOT_PAGES]:
        _write(target, rel)
    for rel in ("app/layout.tsx", "app/(auth)/layout.tsx", "app/(auth)/login/page.tsx", "app/(auth)/verify/page.tsx", "app/app_a/page.tsx", "app/(app)/x/layout.tsx", "app/(app)/x/page.tsx"):
        _write(target, rel)
    _write(target, "middleware.ts", "export default function middleware() {}\n")
    repo = tmp_path_factory.mktemp("mixed-repo")
    init_repo(repo, "ui-nextjs", targets="claude-code")
    profile = yaml.safe_load(PROFILE.read_text(encoding="utf-8"))
    extractors = []
    for ex in profile["extractors"]:
        params = json.loads(json.dumps(ex["params"]).replace("src/app", "app"))  # app ディレクトリを pages と同じ直下に合わせる
        extractors.append({"name": ex["name"], "run": ex["run"], "layer": ex["layer"], "params": params, "rationale": "test"})
    doc = {"format_version": 1, "target": {"repo": "example/app", "commit": "0" * 40, "clone_path": str(target)},
           "profile": {"id": profile["id"], "version": profile["version"]}, "extractors": extractors}
    path = repo / "analysis" / "entry-list.yaml"
    path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return target, path


def test_app_and_pages_live_together_without_id_collisions(mixed):
    target, path = mixed
    out = enumerate_entries(path, PROFILE)
    within = {e["id"]: e.get("within") for e in out["entries"]}
    assert len(out["entries"]) == len(PAGES) + 4 + 3 + 1 + 1, "Pages Router の画面 + App Router の画面 4 + App Router の枠 3 + _app + middleware"
    assert validate_entry_list(out, yaml.safe_load(PROFILE.read_text(encoding="utf-8"))) == []
    assert {"layout_l", "layout_l.auth_g", "layout_l.app_g.x", "layout_l.app_a", "layout_l.middleware_a", "app__a", "x"} <= set(within), "App Router の (app) と app_a、Pages Router の _app は別の id"
    # middleware は直下にあるので、すべての入口を包む。_app は pages の下だけを包む (App Router の画面は包まない)
    assert within["documents.id_d"] == ["layout_l.middleware_a", "layout_l.app_a"]
    assert within["login"] == ["layout_l.middleware_a", "layout_l", "layout_l.auth_g"]
    assert within["layout_l.app_a"] == ["layout_l.middleware_a"] and within["layout_l"] == ["layout_l.middleware_a"]
    assert within["layout_l.middleware_a"] is None


def test_same_url_in_app_and_pages_stops_the_enumeration(mixed):
    """Next.js は、同じ URL の画面を app と pages の両方に置くとビルドで止める。列挙も、黙って片方を捨てずに止まる。"""
    target, path = mixed
    _write(target, "pages/login.tsx")
    with pytest.raises(SystemExit) as ex:
        enumerate_entries(path, PROFILE)
    assert "login" in str(ex.value)


def test_profile_stays_valid_and_app_router_defaults_come_first():
    profile = yaml.safe_load(PROFILE.read_text(encoding="utf-8"))
    assert validate_profile(profile) == []
    names = [e["name"] for e in profile["extractors"]]
    assert names[:2] == ["next-pages", "next-layouts"] and set(PAGES_ROUTER) | {"next-middleware"} <= set(names)
    assert profile["within"] == [{"layer": "layout", "rule": "source_dir"}], "_app と middleware も、layout の層の入口として、置き場から包む"
    notes = profile["hierarchy"]["notes"]
    hit = lambda p: [n["text"] for n in notes if n["contains"] in p]
    assert len(hit("/(layout)/_app")) == 2 and len(hit("/(layout)/(main)")) == 1, "_ で始まる枠の段は、route group の説明とは別に説明する"
