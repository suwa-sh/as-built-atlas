"""ui-vue-router プロファイル (コードの中でルーティングを定義する画面) を、小さな見本の定義で確かめる。

抽出器の既定の規則が取るもの・取らないものと、エージェントが足す入口 (画面と、アプリ全体の枠) が、同じ手順で一覧に並ぶこと。
"""

from pathlib import Path

import pytest
import yaml

from abatlas.enumerate import enumerate_entries
from abatlas.layout import init_repo
from abatlas.validate import validate_entry_list, validate_profile

REPO_ROOT = Path(__file__).resolve().parent.parent
PROFILE = REPO_ROOT / "profiles" / "ui-vue-router" / "profile.yaml"

# 架空の題材。値は (ファイル, 中身)
ROUTER_TS = """\
import {createRouter, createWebHistory} from "vue-router"
import {ORDER_ROUTE, ORDER_PARENT} from "../orders/orderRoutes"
import {makeAdminRoutes} from "../admin/routes"

const routes = [
    {name: "root", path: "/", redirect: {name: "home"}},
    {name: "home", path: "/dashboards/:dashboard?", component: () => import("../dashboards/Dashboard.vue")},
    {name: "books/view", path: "/books/:bookId", component: () => import("../books/BookView.vue")},
    {name: "books/id", path: "/books/bookId", component: () => import("../books/BookHelp.vue")},
    {name: "docs", path: "/docs/:path(.*)?", component: () => import("../docs/Docs.vue")},
    {
        name: ORDER_PARENT,
        path: "/orders/:id",
        component: () => import("../orders/Order.vue"),
        redirect: (to) => ({name: `${ORDER_PARENT}/items`, params: to.params}),
        children: [
            {name: "orders/items", path: "items", component: () => import("../orders/Items.vue")},
        ],
    },
    ORDER_ROUTE,
    ...makeAdminRoutes(),
    {name: "not-found", path: "/:pathMatch(.*)*", component: () => import("../errors/NotFound.vue")},
]

export default createRouter({history: createWebHistory(), routes})
"""
FILES = {
    "src/router/index.ts": ROUTER_TS,
    "src/orders/orderRoutes.ts": 'export const ORDER_PARENT = "orders/view"\nexport const ORDER_ROUTE = {name: "orders/list", path: "/orders", component: () => import("./Orders.vue")}\n',
    "src/admin/routes.ts": "export function makeAdminRoutes() { return [] }\n",
    "src/App.vue": "<template><TopBar /><router-view /></template>\n<script setup>\nimport TopBar from './layout/TopBar.vue'\nimport {useAuthStore} from './stores/auth'\nuseAuthStore().load()\n</script>\n",
    "src/layout/TopBar.vue": "<template><header /></template>\n<script setup>\nimport {useNoticeStore} from '../stores/notice'\nuseNoticeStore().load()\n</script>\n",
    "src/main.ts": 'import {createApp} from "vue"\nimport App from "./App.vue"\ncreateApp(App).mount("#app")\n',
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


def test_ui_vue_router_profile_is_valid():
    profile = _profile()
    assert validate_profile(profile) == []
    assert (PROFILE.parent / "context.md").is_file()
    roles = {t["id"]: t.get("role", "intermediate") for t in profile["layers"]}
    assert roles == {"screen": "entry", "shell": "entry", "part": "entry", "component": "intermediate", "store": "intermediate", "api_client": "intermediate", "external": "boundary"}
    # 対象はブラウザで動く画面だけ。データの読み書きは、バックエンドの API の呼び出しとして、どの層にも書ける
    assert all(t["io"] == ["external_api"] for t in profile["layers"])
    assert "within" not in profile, "画面と枠の関係は、このプロファイルでは持たない"
    notes = profile["hierarchy"]["notes"]
    hit = lambda path: [n["text"] for n in notes if n["contains"] in path]
    assert len(hit("/flows/:id")) == 1 and "コロン" in hit("/flows/:id")[0] and hit("/flows") == []
    labels = profile["hierarchy"]["entry_labels"]
    name = lambda path: next((x["label"] for x in labels if x["contains"] in path), profile["hierarchy"]["level_labels"][-1])
    assert name("/(shell)/app") == "shell" and name("/flows/:id") == "screen"


def _entry_list(repo: Path, app: Path, extractors: list[dict]) -> Path:
    profile = _profile()
    path = repo / "analysis" / "entry-list.yaml"
    doc = {
        "format_version": 1,
        "target": {"repo": "github.example/acme/shop-ui", "commit": "0" * 40, "clone_path": str(app)},
        "profile": {"id": profile["id"], "version": profile["version"]},
        "extractors": extractors,
        "entries": [],
    }
    path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def test_default_rule_takes_literal_routes_and_reports_the_rest(app: Path, tmp_path_factory, capsys):
    """既定の規則は、文字で書いた定義だけを画面にする。取れない定義は、場所を知らせる (エージェントが読んで足す)。"""
    repo = tmp_path_factory.mktemp("vue-repo")
    init_repo(repo, "ui-vue-router", targets="claude-code")
    assert (repo / ".abatlas" / "profiles" / "ui-vue-router" / "context.md").is_file()
    ex = _profile()["extractors"][0]
    path = _entry_list(repo, app, [{"name": ex["name"], "run": ex["run"], "layer": ex["layer"], "params": ex["params"], "rationale": "test"}])
    capsys.readouterr()
    out = enumerate_entries(path, PROFILE)
    assert validate_entry_list(out, _profile()) == []
    got = {e["id"]: e["path"] for e in out["entries"]}
    assert got == {
        "root_r": "/(root)",
        "dashboards.dashboard_o": "/dashboards/:dashboard?",   # 省ける段
        "books.bookId_d": "/books/:bookId",                     # 値が入る段
        "books.bookId": "/books/bookId",                        # 同じ名前の、固定の段。別の id になる
        "docs.path_o": "/docs/:path(.*)?",                      # 値の形 (正規表現) の付いた、省ける段
        "pathMatch_o": "/:pathMatch(.*)*",                      # どの URL にも当たらないときの画面
    }
    assert "orders/items" not in {e["name"] for e in out["entries"]}, "入れ子の route は、画面にしない (親に含める)"
    by = {e["id"]: e for e in out["entries"]}
    assert by["books.bookId_d"]["attributes"] == {"route_name": "books/view", "route_path": "/books/:bookId"}
    err = capsys.readouterr().err
    for line, text in [(12, "name: ORDER_PARENT"), (16, "children: ["), (20, "ORDER_ROUTE"), (21, "...makeAdminRoutes()")]:
        assert f"読めなかった参照: src/router/index.ts:{line}: {text}" in err, (line, err)
    again = enumerate_entries(path, PROFILE)
    assert again["entries"] == out["entries"] and again["enumerated_at"] == out["enumerated_at"], "列挙は決定的"


def test_agent_adds_screens_and_the_shell_per_layer(app: Path, tmp_path_factory):
    """読んで足す入口は、層ごとに別の listed に書く (画面と、アプリ全体の枠)。"""
    repo = tmp_path_factory.mktemp("vue-repo")
    init_repo(repo, "ui-vue-router", targets="claude-code")
    ex = _profile()["extractors"][0]
    listed = lambda name, layer, entries: {"name": name, "run": "abatlas-extract listed", "layer": layer, "rationale": "test", "params": {"entries": entries}}
    path = _entry_list(repo, app, [
        {"name": ex["name"], "run": ex["run"], "layer": ex["layer"], "params": ex["params"], "rationale": "test"},
        listed("agent-listed-screen", "screen", [
            {"id": "orders", "path": "/orders", "name": "orders/list", "source": {"file": "src/orders/orderRoutes.ts", "line": 2}, "reason": "配列に ORDER_ROUTE として入っている"},
            {"id": "orders.id_d", "path": "/orders/:id", "name": "orders/view", "source": {"file": "src/router/index.ts", "line": 11}, "reason": "name を定数で書いている"},
        ]),
        listed("agent-listed-shell", "shell", [
            {"id": "shell_s.app", "path": "/(shell)/app", "name": "App.vue", "source": {"file": "src/App.vue", "line": 1}, "reason": "createApp に渡している根のコンポーネント。ログインの確認を読み込む"},
            {"id": "shell_s.part.TopBar", "path": "/(shell)/part/TopBar", "name": "TopBar.vue", "source": {"file": "src/layout/TopBar.vue", "line": 1}, "reason": "App.vue が描く共通の部品。通知を読み込む"},
        ]),
    ])
    out = enumerate_entries(path, PROFILE)
    assert validate_entry_list(out, _profile()) == []
    layers = {e["id"]: e["layer"] for e in out["entries"]}
    assert layers["orders"] == "screen" and layers["orders.id_d"] == "screen" and layers["shell_s.app"] == "shell" and len(layers) == 10
    assert layers["shell_s.part.TopBar"] == "shell", "枠が描く共通の部品は、部品ごとに別の入口"
    assert all("within" not in e for e in out["entries"])
    # 入口の層でない層に足そうとしたら、検査が落とす
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    doc["extractors"][2]["layer"] = "component"
    assert any("role: entry の層ではない" in f for f in validate_entry_list(doc, _profile()))
