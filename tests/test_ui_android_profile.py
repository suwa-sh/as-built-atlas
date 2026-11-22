"""ui-android プロファイル (Android のアプリ) を、小さな見本のアプリで確かめる。

抽出器の既定の規則が取るもの・取らないもの (画面の行き先、manifest の Activity と画面を持たない起点、Worker) と、
エージェントが足す入口 (アプリ全体の枠が描く共通の composable、取れない destination) が、同じ手順で一覧に並ぶこと。
"""

from pathlib import Path

import pytest
import yaml

from abatlas.enumerate import enumerate_entries
from abatlas.layout import init_repo
from abatlas.validate import validate_entry_list, validate_profile

REPO_ROOT = Path(__file__).resolve().parent.parent
PROFILE = REPO_ROOT / "profiles" / "ui-android" / "profile.yaml"

# 架空の題材。値は (ファイル, 中身)
NAV3_KT = """\
package com.example.shop.feature.books

fun EntryProviderScope<NavKey>.booksEntry(navigator: Navigator) {
    entry<BooksNavKey> { key ->
        BooksScreen(viewModel = hiltViewModel())
    }
    entry<BookNavKey>(metadata = ListDetailSceneStrategy.detailPane()) { key ->
        BookScreen(key.id)
    }
}
"""
NAV2_KT = """\
package com.example.shop.feature.orders

const val ORDER_HELP_ROUTE = "orders/help"

fun NavGraphBuilder.ordersGraph() {
    navigation<OrdersGraph>(startDestination = Screen.OrderList) {
        composable<Screen.OrderList> { OrderListScreen() }
        dialog<CancelOrderRoute> { CancelDialog() }
    }
    composable("orders/{orderId}") { OrderScreen() }
    composable(route = "search?query={query}", arguments = listOf()) { SearchScreen() }
    composable(route = "carts/cart_id") { CartScreen() }
    composable(ORDER_HELP_ROUTE) { HelpScreen() }
    composable("orders/$ORDER_HELP_ROUTE/{id}") { Text("Hi $name") }
}

fun notNavigation() {
    val entry = map.entry<String>()
    composable("not/a/route")
}
"""
APP_KT = """\
package com.example.shop

@Composable
fun ShopApp() {
    NavDisplay(
        entries = entryProvider {
            booksEntry(navigator)
        },
    )
    val provider = { key: NavKey ->
        when (key) {
            is ProfileKey -> NavEntry(key) { ProfileScreen() }
            else -> error("unknown")
        }
    }
}
"""
WORKER_KT = """\
package com.example.shop.sync

class SyncWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result = Result.success()
}

class CleanupWorker(context: Context, params: WorkerParameters) : Worker(context, params), Loggable {
    override fun doWork(): Result = Result.success()
}

class NotAWorker : BaseThing()
"""
MANIFEST = """\
<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android">
    <application
        android:name=".ShopApplication"
        android:label="@string/app_name">
        <activity
            android:name=".MainActivity"
            android:exported="true">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
            </intent-filter>
        </activity>
        <activity android:name="com.example.shop.legacy.ReceiptActivity" />
        <activity-alias android:name=".Launcher" android:targetActivity=".MainActivity" />
        <service android:name=".push.PushService" android:exported="false" />
        <receiver android:name=".BootReceiver" />
    </application>
</manifest>
"""
NAV_XML = """\
<?xml version="1.0" encoding="utf-8"?>
<navigation xmlns:android="http://schemas.android.com/apk/res/android"
    android:id="@+id/settings_graph"
    app:startDestination="@id/settingsFragment">
    <fragment
        android:id="@+id/settingsFragment"
        android:name="com.example.shop.settings.SettingsFragment" />
    <dialog android:id="@+id/logout_dialog" android:name="com.example.shop.settings.LogoutDialog">
        <argument android:name="reason" />
    </dialog>
    <activity android:id="@+id/helpActivity" android:name="com.example.shop.HelpActivity" />
</navigation>
"""
FILES = {
    "feature/books/src/main/kotlin/com/example/shop/feature/books/navigation/BooksEntryProvider.kt": NAV3_KT,
    "feature/orders/src/main/kotlin/com/example/shop/feature/orders/navigation/OrdersNavigation.kt": NAV2_KT,
    "app/src/main/kotlin/com/example/shop/ui/ShopApp.kt": APP_KT,
    "sync/src/main/kotlin/com/example/shop/sync/SyncWorker.kt": WORKER_KT,
    "app/src/main/AndroidManifest.xml": MANIFEST,
    "feature/settings/src/main/res/navigation/settings_nav.xml": NAV_XML,
    # テストのソースは拾わない
    "feature/books/src/test/kotlin/com/example/shop/feature/books/BooksTest.kt": "fun EntryProviderScope<NavKey>.t() { entry<FakeNavKey> { } }\n",
    "app/src/androidTest/AndroidManifest.xml": '<manifest><application><activity android:name=".TestActivity" /></application></manifest>\n',
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
            "repo": "github.example/acme/shop-android",
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


def test_ui_android_profile_is_valid():
    profile = _profile()
    assert validate_profile(profile) == []
    assert (PROFILE.parent / "context.md").is_file()
    roles = {t["id"]: t.get("role", "intermediate") for t in profile["layers"]}
    assert roles == {
        "screen": "entry",
        "activity": "entry",
        "shell": "entry",
        "background": "entry",
        "ui": "intermediate",
        "viewmodel": "intermediate",
        "usecase": "intermediate",
        "repository": "intermediate",
        "datasource": "intermediate",
        "external": "boundary",
    }
    # 端末の中の保存 (Room、DataStore、ファイル) も、API の呼び出しも、どの層にも書ける
    assert all(
        t["io"] == ["rdb", "kvs", "filesystem", "external_api"]
        for t in profile["layers"]
    )
    assert "within" not in profile, (
        "画面と枠はモジュールをまたぐので、置き場のフォルダでは包む関係が決まらない"
    )
    # 保存先の読み書きも API の呼び出しも、external のフレームに書く (ui-vue-router、ui-ios と同じ向き)。Room の DAO も、注釈の行を source にした external で閉じる
    datasource = next(t for t in profile["layers"] if t["id"] == "datasource")
    assert "external のフレームに書く" in datasource["invokes_next"]
    context = (PROFILE.parent / "context.md").read_text(encoding="utf-8")
    assert (
        "**`external` のフレームに書く**" in context
        and "external` のフレームを足さずに閉じる" not in context
        and "`external` のフレームは足さない" not in context
    )
    assert "`dbms: sqlite`" in context, (
        "dbms の綴りは、既にあるプロファイルと同じ小文字の sqlite"
    )
    labels = profile["hierarchy"]["entry_labels"]

    def name(path):
        return next(
            (x["label"] for x in labels if x["contains"] in path),
            profile["hierarchy"]["level_labels"][-1],
        )

    assert (
        name("/(activity)/MainActivity") == "activity"
        and name("/(shell)/SettingsDialog") == "shell"
    )
    assert (
        name("/(background)/worker/SyncWorker") == "background"
        and name("/orders/{orderId}") == "screen"
    )
    notes = profile["hierarchy"]["notes"]

    def hit(path):
        return [n["text"] for n in notes if n["contains"] in path]

    assert (
        len(hit("/orders/{orderId}")) == 1
        and "波かっこ" in hit("/orders/{orderId}")[0]
        and hit("/ForYou") == []
    )


def test_extractors_take_destinations_and_os_components(
    app: Path, tmp_path_factory, capsys
):
    """既定の規則で、画面の行き先 (型の route、文字の route、XML の graph)、manifest の Activity と画面を持たない起点、Worker を取る。"""
    repo = tmp_path_factory.mktemp("android-repo")
    init_repo(repo, "ui-android", targets="claude-code")
    assert (repo / ".abatlas" / "profiles" / "ui-android" / "context.md").is_file()
    path = _entry_list(
        repo,
        app,
        _extractors(
            "compose-typed-destinations",
            "compose-string-destinations",
            "navigation-xml-destinations",
            "manifest-activities",
            "manifest-background",
            "workers",
        ),
    )
    capsys.readouterr()
    out = enumerate_entries(path, PROFILE)
    assert validate_entry_list(out, _profile()) == []
    got = {e["id"]: (e["path"], e["layer"]) for e in out["entries"]}
    assert got == {
        # 型の route: 型の名前を 1 段にし、末尾の NavKey / Route を落とす。入れ子の class は . でつないだまま
        "Books": ("/Books", "screen"),
        "Book": ("/Book", "screen"),
        "Screen.OrderList": ("/Screen.OrderList", "screen"),
        "CancelOrder": ("/CancelOrder", "screen"),
        # 文字の route: / で区切って段にする。値が入る段は _d、? から後ろの省ける引数は落とす。名前の中の _ は重ねる
        "orders.orderId_d": ("/orders/{orderId}", "screen"),
        "search": ("/search", "screen"),
        "carts.cart__id": ("/carts/cart_id", "screen"),
        # navigation graph の XML: fragment と dialog。activity の destination は取らない
        "settings__nav.settingsFragment": ("/settings_nav/settingsFragment", "screen"),
        "settings__nav.logout__dialog": ("/settings_nav/logout_dialog", "screen"),
        # manifest: activity は activity の層、application / service / receiver は background の層。activity-alias は取らない
        "activity_a.MainActivity": ("/(activity)/MainActivity", "activity"),
        "activity_a.ReceiptActivity": ("/(activity)/ReceiptActivity", "activity"),
        "background_b.application.ShopApplication": (
            "/(background)/application/ShopApplication",
            "background",
        ),
        "background_b.service.PushService": (
            "/(background)/service/PushService",
            "background",
        ),
        "background_b.receiver.BootReceiver": (
            "/(background)/receiver/BootReceiver",
            "background",
        ),
        # Worker は manifest に無いので、コードの継承から取る
        "background_b.worker.SyncWorker": (
            "/(background)/worker/SyncWorker",
            "background",
        ),
        "background_b.worker.CleanupWorker": (
            "/(background)/worker/CleanupWorker",
            "background",
        ),
    }
    assert "OrdersGraph" not in got, "入れ子の graph は画面にしない"
    by = {e["id"]: e for e in out["entries"]}
    assert by["Books"]["attributes"] == {"route_type": "BooksNavKey"}
    assert (
        by["activity_a.MainActivity"]["attributes"]["component_class"]
        == ".MainActivity"
    )
    assert by["background_b.service.PushService"]["source"] == {
        "file": "app/src/main/AndroidManifest.xml",
        "line": 15,
    }
    err = capsys.readouterr().err
    nav2 = "feature/orders/src/main/kotlin/com/example/shop/feature/orders/navigation/OrdersNavigation.kt"
    assert f"読めなかった参照: {nav2}:13: composable(ORDER_HELP_ROUTE)" in err, err
    assert (
        "読めなかった参照: app/src/main/kotlin/com/example/shop/ui/ShopApp.kt:12: NavEntry(key)"
        in err
    ), err
    # route の文字に $ で値を埋め込んだ destination は取らずに知らせる。ラムダの中の文字は見ない
    assert f'読めなかった参照: {nav2}:14: "orders/$ORDER_HELP_ROUTE/{{id}}"' in err, err
    assert "Hi $name" not in err
    again = enumerate_entries(path, PROFILE)
    assert (
        again["entries"] == out["entries"]
        and again["enumerated_at"] == out["enumerated_at"]
    ), "列挙は決定的"


def test_agent_adds_shell_and_unread_destinations_per_layer(
    app: Path, tmp_path_factory
):
    """読んで足す入口は、層ごとに別の listed に書く (取れない destination と、アプリ全体の枠が描く共通の composable)。"""
    repo = tmp_path_factory.mktemp("android-repo")
    init_repo(repo, "ui-android", targets="claude-code")

    def listed(name, layer, entries):
        return {
            "name": name,
            "run": "abatlas-extract listed",
            "layer": layer,
            "rationale": "test",
            "params": {"entries": entries},
        }

    path = _entry_list(
        repo,
        app,
        [
            *_extractors("compose-typed-destinations", "manifest-activities"),
            listed(
                "agent-listed-screen",
                "screen",
                [
                    {
                        "id": "orders.help",
                        "path": "/orders/help",
                        "name": "ORDER_HELP_ROUTE",
                        "source": {
                            "file": "feature/orders/src/main/kotlin/com/example/shop/feature/orders/navigation/OrdersNavigation.kt",
                            "line": 13,
                        },
                        "reason": "route を定数で渡している。値は 3 行目",
                    },
                    {
                        "id": "Profile",
                        "path": "/Profile",
                        "name": "ProfileKey",
                        "source": {
                            "file": "app/src/main/kotlin/com/example/shop/ui/ShopApp.kt",
                            "line": 12,
                        },
                        "reason": "when で書いた entryProvider の NavEntry",
                    },
                ],
            ),
            listed(
                "agent-listed-shell",
                "shell",
                [
                    {
                        "id": "shell_s.SettingsDialog",
                        "path": "/(shell)/SettingsDialog",
                        "name": "SettingsDialog",
                        "source": {
                            "file": "app/src/main/kotlin/com/example/shop/ui/ShopApp.kt",
                            "line": 4,
                        },
                        "reason": "枠が描く設定の dialog。DataStore を読み書きする",
                    },
                ],
            ),
        ],
    )
    out = enumerate_entries(path, PROFILE)
    assert validate_entry_list(out, _profile()) == []
    layers = {e["id"]: e["layer"] for e in out["entries"]}
    assert (
        layers["orders.help"] == "screen"
        and layers["Profile"] == "screen"
        and layers["shell_s.SettingsDialog"] == "shell"
    )
    assert len(layers) == 9 and all("within" not in e for e in out["entries"])
    # 入口の層でない層に足そうとしたら、検査が落とす
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    doc["extractors"][3]["layer"] = "viewmodel"
    assert any(
        "role: entry の層ではない" in f for f in validate_entry_list(doc, _profile())
    )
