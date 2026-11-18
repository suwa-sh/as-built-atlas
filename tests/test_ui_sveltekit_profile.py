"""ui-sveltekit プロファイル (SvelteKit の画面。ファイルの置き場がルーティング) を、小さな見本の routes で確かめる。

画面 (+page.svelte)、画面を包む枠 (+layout.svelte)、すべての要求を包むフック (hooks.server) が、別々の入口として並び、
包む関係 (within) が、ソースのフォルダの親子から決まること。
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
PROFILE = REPO_ROOT / "profiles" / "ui-sveltekit" / "profile.yaml"

SVELTE = "<script lang=\"ts\">\n\tlet { data } = $props();\n</script>\n\n<h1>{data.title}</h1>\n"
# 画面 (+page.svelte)。値は (ファイル, 中身)
PAGES = {
    "src/routes/+page.svelte": "<h1>home</h1>\n",
    "src/routes/(app)/books/+page.svelte": SVELTE,
    "src/routes/(app)/books/[id]/+page.svelte": SVELTE,
    "src/routes/(app)/books/[id]/edit/+page.svelte": "<script>\n\tlet { form } = $props();\n</script>\n<form\n\tmethod=\"POST\" action=\"?/save\">\n</form>\n",
    "src/routes/[[lang]]/about/+page.svelte": SVELTE,
    "src/routes/docs/[...rest]/+page.svelte": SVELTE,
    "src/routes/items/[id=integer]/+page.svelte": SVELTE,
    "src/routes/blog/_drafts/+page.svelte": SVELTE,  # Next.js と違い、_ で始まるフォルダも route になる
    "src/routes/(app)/books/[id]/print/+page@.svelte": SVELTE,  # 途中の枠を抜ける page
    "src/routes/smileys/[x+3a]-[x+29]/+page.svelte": SVELTE,  # 記号を表す書き方
}
LAYOUTS = {
    "src/routes/+layout.svelte": "<script>\n\tlet { children } = $props();\n</script>\n{@render children()}\n",
    "src/routes/(app)/+layout.svelte": "<script>\n\tlet { children } = $props();\n</script>\n{@render children()}\n",
    "src/routes/(app)/books/[id]/+layout.svelte": "<slot />\n",
}
HOOKS = {
    "src/hooks.server.ts": "import { sequence } from '@sveltejs/kit/hooks';\n\nexport const handle = sequence(auth, log);\nexport async function handleFetch({ request, fetch }) { return fetch(request); }\n",
}
OTHERS = {
    "src/routes/+layout.ts": "export const load = async ({ fetch }) => ({ user: await (await fetch('/api/user')).json() });\n",
    "src/routes/(app)/books/[id]/+page.server.ts": "export const load = async () => ({});\nexport const actions = { save: async () => {} };\n",
    "src/routes/(app)/books/[id]/+page.ts": "export const load = async ({ data }) => data;\n",
    "src/routes/api/books/+server.ts": "export const GET = async () => new Response('[]');\n",
    "src/routes/(app)/books/BookCard.svelte": "<div />\n",  # + で始まらないファイルは SvelteKit が無視する
    "src/routes/(app)/books/page.spec.ts": "test('x', () => {});\n",
    "src/routes/+error.svelte": "<h1>error</h1>\n",
    "src/hooks.ts": "export const transport = {};\n",
    "src/lib/components/Page.svelte": "<div />\n",
}


@pytest.fixture()
def app(tmp_path: Path) -> Path:
    for rel, text in {**PAGES, **LAYOUTS, **HOOKS, **OTHERS}.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return tmp_path


def _profile() -> dict:
    return yaml.safe_load(PROFILE.read_text(encoding="utf-8"))


def _params(name: str) -> dict:
    return next(e for e in _profile()["extractors"] if e["name"] == name)["params"]


def _run(scope: Path, name: str, layer: str, capsys) -> list[dict]:
    extract(scope, _params(name), layer)
    recs = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert all(schema_errors("entry-candidate", r) == [] for r in recs)
    return recs


def test_ui_sveltekit_profile_is_valid():
    profile = _profile()
    assert validate_profile(profile) == []
    assert (PROFILE.parent / "context.md").is_file()
    roles = {t["id"]: t.get("role", "intermediate") for t in profile["layers"]}
    assert roles == {"page": "entry", "layout": "entry", "shell": "entry", "part": "entry", "component": "intermediate",
                     "api_route": "intermediate", "query": "intermediate", "external": "boundary"}
    # 層の名前は ui-nextjs と同じ (足したのは shell だけ。ui-vue-router、ui-nuxt と同じ名前。上の集合で確かめる)
    assert profile["within"] == [{"layer": "layout", "rule": "source_dir"}, {"layer": "shell", "rule": "source_dir"}]
    # サーバー側で動く load や受け口は DB を直接読み書きできる。io が空だと、その読み書きを結果に書けない
    io = {t["id"]: set(t["io"]) for t in profile["layers"]}
    assert all({"rdb", "object_storage", "external_api"} <= io[t] for t in roles)
    notes = profile["hierarchy"]["notes"]
    hit = lambda path: [n["text"] for n in notes if n["contains"] in path]
    assert len(hit("/books/[id]")) == 1 and "角かっこ" in hit("/books/[id]")[0] and hit("/books") == []
    assert len(hit("/(layout)/(app)")) == 1 and "+layout.svelte" in hit("/(layout)/(app)")[0]
    assert len(hit("/(shell)/hooks.server")) == 1 and "hooks.server" in hit("/(shell)/hooks.server")[0]
    labels = profile["hierarchy"]["entry_labels"]
    name = lambda path: next((x["label"] for x in labels if x["contains"] in path), profile["hierarchy"]["level_labels"][-1])
    assert name("/(layout)/(app)") == "layout" and name("/(shell)/hooks.server") == "shell" and name("/(part)/r/x") == "part" and name("/books/[id]") == "page"


def test_pages_become_entries_with_url_shaped_paths(app: Path, capsys):
    recs = _run(app, "sveltekit-pages", "page", capsys)
    assert {r["source"]["file"] for r in recs} == set(PAGES), "+page.svelte だけが入口 (+server.ts、+layout、+ で始まらないファイル、routes の外は入口ではない)"
    assert {r["path"]: r["id"] for r in recs} == {
        "/(root)": "root_r",
        "/books": "books",                                 # (app) は URL に出ないので落ちる
        "/books/[id]": "books.id_d",
        "/books/[id]/edit": "books.id_d.edit",
        "/[[lang]]/about": "lang_o.about",                 # 省ける段
        "/docs/[...rest]": "docs.rest_c",                  # 残りすべての段
        "/items/[id=integer]": "items.id_d",               # matcher は id から外し、階層パスに残す
        "/blog/_drafts": "blog.__drafts",                  # _ で始まるフォルダも route。名前の _ は重ねる
        "/books/[id]/print": "books.id_d.print",           # 枠を抜ける page も、置き場で段を決める
        "/smileys/[x+3a]-[x+29]": "smileys.x3a-x29",       # 記号を表す書き方は、値の入る段ではない
    }
    by = {r["path"]: r for r in recs}
    assert by["/books"]["source"] == {"file": "src/routes/(app)/books/+page.svelte", "line": 1}, "出典の行は <script の行"
    assert by["/(root)"]["source"]["line"] == 1, "script の無い page は 1 行目"
    assert by["/books/[id]/edit"]["attributes"]["form"] is True and by["/books"]["attributes"]["form"] is False, "POST の form (複数行、大文字) を見分ける"
    assert by["/books/[id]/print"]["source"]["file"].endswith("+page@.svelte")
    assert by["/books/[id]"]["attributes"]["file_segments"] == ["(app)", "books", "[id]"], "加工前の段も残す (入れ物が分かる)"


def test_segments_that_differ_only_by_kind_get_different_ids(app: Path, capsys):
    cases = {
        "src/routes/blog/id/+page.svelte": ("/blog/id", "blog.id"),
        "src/routes/blog/[id]/+page.svelte": ("/blog/[id]", "blog.id_d"),
        "src/routes/blog/id_d/+page.svelte": ("/blog/id_d", "blog.id__d"),
        "src/routes/help/[[all]]/+page.svelte": ("/help/[[all]]", "help.all_o"),
        "src/routes/help/[...all]/+page.svelte": ("/help/[...all]", "help.all_c"),
        "src/routes/help/all/+page.svelte": ("/help/all", "help.all"),
        "src/routes/root/+page.svelte": ("/root", "root"),
        "src/routes/my_page/[my_id]/+page.svelte": ("/my_page/[my_id]", "my__page.my__id_d"),
        "src/routes/photos-[id]/+page.svelte": ("/photos-[id]", "photos-id_d"),  # 段の一部に値が入る (ui-nuxt と同じ印)
        "src/routes/photos-id/+page.svelte": ("/photos-id", "photos-id"),
        "src/routes/range/[from]-[to=date]/+page.svelte": ("/range/[from]-[to=date]", "range.from_d-to_d"),
    }
    for rel in cases:
        (app / rel).parent.mkdir(parents=True)
        (app / rel).write_text(SVELTE, encoding="utf-8")
    recs = {r["source"]["file"]: r for r in _run(app, "sveltekit-pages", "page", capsys)}
    assert {f: (recs[f]["path"], recs[f]["id"]) for f in cases} == cases


def test_hooks_written_as_functions(app: Path, capsys):
    """handle を関数の宣言で書いたリポジトリでも、出典の行は handle の行。"""
    (app / "src/hooks.server.ts").write_text("import x from 'y';\n\nexport async function init() {}\nexport async function handle({ event, resolve }) { return resolve(event); }\n", encoding="utf-8")
    hooks = _run(app, "sveltekit-hooks", "shell", capsys)
    assert hooks[0]["source"]["line"] == 4 and hooks[0]["attributes"]["init"] is True and hooks[0]["attributes"]["handle_fetch"] is False


def test_matcher_only_difference_fails_loudly(app: Path):
    """[id=integer] と [id] は SvelteKit では同居できる (matcher 付きが先に当たる)。id では同じになるので、黙って片方を捨てず止まる。"""
    (app / "src/routes/items/[id]").mkdir(parents=True)
    (app / "src/routes/items/[id]/+page.svelte").write_text(SVELTE, encoding="utf-8")
    with pytest.raises(SystemExit) as ex:
        extract(app, _params("sveltekit-pages"), "page")
    assert "id 'items.id_d' が 2 つのファイルから出た" in str(ex.value)


def test_layouts_and_hooks_become_entries_apart_from_pages(app: Path, capsys):
    layouts = _run(app, "sveltekit-layouts", "layout", capsys)
    assert {r["source"]["file"]: (r["path"], r["id"]) for r in layouts} == {
        "src/routes/+layout.svelte": ("/(layout)", "layout_l"),
        "src/routes/(app)/+layout.svelte": ("/(layout)/(app)", "layout_l.app_g"),  # 入れ物を落とさない: どの入れ物の枠かが名前
        "src/routes/(app)/books/[id]/+layout.svelte": ("/(layout)/(app)/books/[id]", "layout_l.app_g.books.id_d"),
    }
    hooks = _run(app, "sveltekit-hooks", "shell", capsys)
    assert [(r["path"], r["id"], r["source"]) for r in hooks] == [("/(shell)/hooks.server", "shell_s.hooks-server", {"file": "src/hooks.server.ts", "line": 3})], "出典の行は handle の行"
    assert hooks[0]["attributes"] == {"file_segments": ["hooks.server"], "handle": True, "handle_fetch": True, "init": False}
    pages = {r["id"] for r in _run(app, "sveltekit-pages", "page", capsys)}
    assert not pages & ({r["id"] for r in layouts} | {"shell_s.hooks-server"}), "枠とフックの id は画面の id と重ならない"


def _entry_list(repo: Path, app: Path) -> Path:
    profile = _profile()
    doc = {
        "format_version": 1,
        "target": {"repo": "example/app", "commit": "0" * 40, "clone_path": str(app)},
        "profile": {"id": profile["id"], "version": profile["version"]},
        "extractors": [{"name": ex["name"], "run": ex["run"], "layer": ex["layer"], "params": ex["params"], "rationale": "test"} for ex in profile["extractors"]],
    }
    path = repo / "analysis" / "entry-list.yaml"
    path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def test_enumerate_fills_within_with_hooks_outermost(app: Path, tmp_path_factory):
    """フック (src/hooks.server.ts) は src の下のすべての入口を包み、いちばん外側に来る。枠は置き場のフォルダの親子で決まる。"""
    repo = tmp_path_factory.mktemp("svelte-repo")
    init_repo(repo, "ui-sveltekit", targets="claude-code")
    assert (repo / ".abatlas" / "profiles" / "ui-sveltekit" / "context.md").is_file()
    path = _entry_list(repo, app)
    out = enumerate_entries(path, PROFILE)
    assert validate_entry_list(out, _profile()) == []
    assert len(out["entries"]) == len(PAGES) + len(LAYOUTS) + len(HOOKS)
    within = {e["id"]: e.get("within") for e in out["entries"]}
    assert within["shell_s.hooks-server"] is None and within["layout_l"] == ["shell_s.hooks-server"]
    assert within["root_r"] == within["docs.rest_c"] == ["shell_s.hooks-server", "layout_l"]
    assert within["books"] == ["shell_s.hooks-server", "layout_l", "layout_l.app_g"]
    assert within["books.id_d"] == ["shell_s.hooks-server", "layout_l", "layout_l.app_g", "layout_l.app_g.books.id_d"], "同じフォルダの枠も通る"
    # 枠を抜ける page (+page@.svelte) も、決め方 (source_dir) は置き場のまま。抜けていることは、分析の summary に書く (context.md)
    assert within["books.id_d.print"] == within["books.id_d.edit"] == within["books.id_d"]
    again = enumerate_entries(path, PROFILE)
    assert again["entries"] == out["entries"] and again["enumerated_at"] == out["enumerated_at"], "列挙は決定的"
