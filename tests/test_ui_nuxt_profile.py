"""ui-nuxt プロファイル (Nuxt の画面) を、小さな見本のアプリで確かめる。

抽出器の既定の規則が取るもの・取らないもの (pages の page と入れ子の親、layout、app.vue と error.vue、global の route middleware) と、
エージェントが足す入口 (起動のときにデータを読むプラグイン) が、同じ手順で一覧に並ぶこと。
"""

from pathlib import Path

import pytest
import yaml

from abatlas.enumerate import enumerate_entries
from abatlas.layout import init_repo
from abatlas.validate import validate_entry_list, validate_profile

REPO_ROOT = Path(__file__).resolve().parent.parent
PROFILE = REPO_ROOT / "profiles" / "ui-nuxt" / "profile.yaml"

SFC = '<script setup lang="ts">\nconst x = 1\n</script>\n<template><div /></template>\n'
PARENT = "<script setup lang=\"ts\">\ndefinePageMeta({ layout: 'shop', middleware: ['auth'] })\n</script>\n<template><NuxtPage /></template>\n"
# Nuxt 4 の置き場 (app/ の下)。架空の題材
FILES = {
    "app/app.vue": "<template><NuxtLayout><NuxtPage /></NuxtLayout></template>\n",
    "app/error.vue": SFC,
    "app/pages/index.vue": SFC,
    "app/pages/books.vue": PARENT,  # 入れ子の親 (隣に books/ がある)
    "app/pages/books/index.vue": SFC,  # URL は /books (親と同じ)
    "app/pages/books/[id].vue": SFC,
    "app/pages/books/id.vue": SFC,  # 静的な段。[id] と別の id
    "app/pages/books/[id]/index.vue": SFC,
    "app/pages/users/[[tab]].vue": SFC,
    "app/pages/docs/[...slug].vue": SFC,
    "app/pages/teams/members-[team_id].vue": SFC,  # 値と静的な文字が混ざる段
    "app/pages/(marketing)/about.vue": SFC,  # URL に出ない入れ物
    "app/pages/books/-parts/Cover.vue": SFC,  # - で始まるフォルダの下は、ルーティングの対象外
    "app/pages/-draft.vue": SFC,
    "app/layouts/default.vue": "<template><slot /></template>\n",
    "app/layouts/shop_front.vue": SFC,
    "app/layouts/admin/wide.vue": SFC,
    "app/middleware/01.auth.global.ts": "export default defineNuxtRouteMiddleware((to) => {\n  return navigateTo('/signin')\n})\n",
    "app/middleware/auth.ts": "export default defineNuxtRouteMiddleware(() => {})\n",  # 名前付き。入口にしない
    "app/plugins/state.ts": "export default defineNuxtPlugin(async () => {\n  await $fetch('/api/info')\n})\n",
    "app/components/BookList.vue": SFC,
    "server/api/books/[id].get.ts": "export default defineEventHandler(() => ({}))\n",  # 受け口は入口にしない
    "server/middleware/01.session.ts": "// どの要求の前にも動く\nexport default defineEventHandler(() => {})\n",
}


@pytest.fixture()
def app(tmp_path: Path) -> Path:
    for rel, text in FILES.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return tmp_path


def _profile() -> dict:
    return yaml.safe_load(PROFILE.read_text(encoding="utf-8"))


def _extractors(*names: str) -> list[dict]:
    exs = {ex["name"]: ex for ex in _profile()["extractors"]}
    return [
        {
            "name": n,
            "run": exs[n]["run"],
            "layer": exs[n]["layer"],
            "params": exs[n]["params"],
            "rationale": "test",
        }
        for n in names
    ]


def _entry_list(repo: Path, app: Path, extractors: list[dict]) -> Path:
    profile = _profile()
    path = repo / "analysis" / "entry-list.yaml"
    doc = {
        "format_version": 1,
        "target": {
            "repo": "github.example/acme/shop-nuxt",
            "commit": "0" * 40,
            "clone_path": str(app),
        },
        "profile": {"id": profile["id"], "version": profile["version"]},
        "extractors": extractors,
        "entries": [],
    }
    path.write_text(
        yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    return path


def by_source_line(out: dict, eid: str) -> int:
    return next(e["source"]["line"] for e in out["entries"] if e["id"] == eid)


ALL = (
    "nuxt-pages",
    "nuxt-layouts",
    "nuxt-app-shell",
    "nuxt-global-middleware",
    "nuxt-server-middleware",
)


def test_ui_nuxt_profile_is_valid():
    profile = _profile()
    assert validate_profile(profile) == []
    assert (PROFILE.parent / "context.md").is_file()
    roles = {t["id"]: t.get("role", "intermediate") for t in profile["layers"]}
    assert roles == {
        "page": "entry",
        "layout": "entry",
        "shell": "entry",
        "part": "entry",
        "component": "intermediate",
        "store": "intermediate",
        "api_client": "intermediate",
        "api_route": "intermediate",
        "query": "intermediate",
        "external": "boundary",
    }
    assert "within" not in profile, (
        "入れ子の page (a.vue が隣の a/ を包む) と、definePageMeta で選ぶ layout は、置き場のフォルダ (source_dir) では決まらない"
    )
    # サーバー側を持つ作りでは、受け口と関数がデータを読み書きする。持たない作りでは、ブラウザ側の層は API の呼び出しだけ
    io = {t["id"]: set(t["io"]) for t in profile["layers"]}
    assert all(
        {"rdb", "external_api"} <= io[t] for t in ("api_route", "query", "external")
    )
    assert all(io[t] == {"external_api"} for t in ("component", "store", "api_client"))
    labels = profile["hierarchy"]["entry_labels"]

    def name(path):
        return next(
            (x["label"] for x in labels if x["contains"] in path),
            profile["hierarchy"]["level_labels"][-1],
        )

    assert (
        name("/(layout)/default") == "layout"
        and name("/(shell)/app") == "shell"
        and name("/(part)/r/k") == "part"
        and name("/books/[id]") == "page"
    )
    notes = profile["hierarchy"]["notes"]

    def hit(path):
        return [n["text"] for n in notes if n["contains"] in path]

    assert (
        len(hit("/books/[id]")) == 1
        and "角かっこ" in hit("/books/[id]")[0]
        and hit("/signin") == []
    )
    assert len(hit("/books/index")) == 1 and "URL には出ない" in hit("/books/index")[0]


def test_extractors_take_pages_layouts_and_shell(app: Path, tmp_path_factory, capsys):
    repo = tmp_path_factory.mktemp("nuxt-repo")
    init_repo(repo, "ui-nuxt", targets="claude-code")
    assert (repo / ".abatlas" / "profiles" / "ui-nuxt" / "context.md").is_file()
    path = _entry_list(repo, app, _extractors(*ALL))
    out = enumerate_entries(path, PROFILE)
    assert validate_entry_list(out, _profile()) == []
    got = {e["id"]: (e["path"], e["layer"]) for e in out["entries"]}
    assert got == {
        # 階層は置き場。index も段に残すので、URL が同じ親と子 (/books と /books/index) が別の入口になる
        "index": ("/index", "page"),
        "books": ("/books", "page"),
        "books.index": ("/books/index", "page"),
        "books.id_d": ("/books/[id]", "page"),
        "books.id": ("/books/id", "page"),
        "books.id_d.index": ("/books/[id]/index", "page"),
        "users.tab_o": ("/users/[[tab]]", "page"),
        "docs.slug_c": ("/docs/[...slug]", "page"),
        "teams.members-team__id_d": ("/teams/members-[team_id]", "page"),
        "about": ("/about", "page"),  # (marketing) は落ちる
        # layout: 置き場が名前。名前の中の _ は重ねる
        "layout_l.default": ("/(layout)/default", "layout"),
        "layout_l.shop__front": ("/(layout)/shop_front", "layout"),
        "layout_l.admin.wide": ("/(layout)/admin/wide", "layout"),
        # アプリ全体の枠: app.vue、error.vue、global の middleware (名前付きの middleware は取らない)
        "shell_s.app": ("/(shell)/app", "shell"),
        "shell_s.error": ("/(shell)/error", "shell"),
        "shell_s.middleware.01-auth-global": (
            "/(shell)/middleware/01.auth.global",
            "shell",
        ),
        # サーバー側の middleware も、どの要求でも動く枠。受け口 (server/api) は入口にしない
        "shell_s.server-middleware.01-session": (
            "/(shell)/server-middleware/01.session",
            "shell",
        ),
    }
    assert by_source_line(out, "shell_s.server-middleware.01-session") == 2
    assert all("within" not in e for e in out["entries"])
    by = {e["id"]: e for e in out["entries"]}
    assert (
        by["books"]["attributes"]["nested"] is True
        and by["books.index"]["attributes"]["nested"] is False
    ), "入れ子の親は <NuxtPage> を描く"
    assert (
        by["books"]["attributes"]["layout"] is True
        and by["books"]["attributes"]["middleware"] is True
    )
    assert by["books"]["source"] == {"file": "app/pages/books.vue", "line": 1}
    assert by["shell_s.middleware.01-auth-global"]["source"]["line"] == 1
    assert by["about"]["attributes"]["file_segments"] == ["(marketing)", "about"]
    again = enumerate_entries(path, PROFILE)
    assert again["entries"] == out["entries"], "列挙は決定的"


def test_agent_adds_plugins_as_shell(app: Path, tmp_path_factory):
    """起動のときにデータを読むプラグインは、読んで listed で足す (layer: shell)。"""
    repo = tmp_path_factory.mktemp("nuxt-repo")
    init_repo(repo, "ui-nuxt", targets="claude-code")
    listed = {
        "name": "agent-listed-shell",
        "run": "abatlas-extract listed",
        "layer": "shell",
        "rationale": "test",
        "params": {
            "entries": [
                {
                    "id": "shell_s.plugin.state",
                    "path": "/(shell)/plugin/state",
                    "source": {"file": "app/plugins/state.ts", "line": 1},
                    "reason": "起動のときに /api/info を読む",
                },
            ]
        },
    }
    path = _entry_list(repo, app, [*_extractors("nuxt-app-shell"), listed])
    out = enumerate_entries(path, PROFILE)
    assert validate_entry_list(out, _profile()) == []
    assert {e["id"]: e["layer"] for e in out["entries"]} == {
        "shell_s.app": "shell",
        "shell_s.error": "shell",
        "shell_s.plugin.state": "shell",
    }
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    doc["extractors"][1]["layer"] = "store"
    assert any(
        "role: entry の層ではない" in f for f in validate_entry_list(doc, _profile())
    )
