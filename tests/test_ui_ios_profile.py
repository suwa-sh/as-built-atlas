"""ui-ios プロファイル (SwiftUI の行き先の enum と、OS から起動される入口) を、小さな見本の Swift で確かめる。

抽出器の既定の規則が取るもの・取らないものと、エージェントが足す入口 (UIKit の画面、アプリ全体の枠、Info.plist だけで決まる入口) が、
同じ手順で一覧に並ぶこと。
"""

from pathlib import Path

import pytest
import yaml

from abatlas.enumerate import enumerate_entries
from abatlas.layout import init_repo
from abatlas.validate import validate_entry_list, validate_profile

REPO_ROOT = Path(__file__).resolve().parent.parent
PROFILE = REPO_ROOT / "profiles" / "ui-ios" / "profile.yaml"

# 架空の題材。値は (ファイル, 中身)
ROUTER = """\
import SwiftUI

public enum RouterDestination: Hashable {
  case bookDetail(id: String)
  case bookDetailWithBook(book: Book)
  case shelf_list
}

public enum SheetDestination: Identifiable {
  case newReview(bookId: String), settings
  public var id: String { "x" }
}

enum AppTab: Hashable, CaseIterable {
  case home, search
  case other
}

enum SortOrder { case title, date }
"""
REGISTRY = """\
import SwiftUI

extension View {
  func withAppRouter() -> some View {
    navigationDestination(for: RouterDestination.self) { destination in
      switch destination {
      case .bookDetail(let id): BookDetailView(bookId: id)
      case .bookDetailWithBook(let book): BookDetailView(book: book)
      case .shelf_list: ShelfListView()
      }
    }
  }
}

struct PhotoView: View {
  @State var picked: Photo?
  var body: some View {
    Text("x").fullScreenCover(item: $picked) { p in PhotoViewer(photo: p) }
  }
}
"""
FILES = {
    "App/Router.swift": ROUTER,
    "App/AppRegistry.swift": REGISTRY,
    "App/ScannerViewController.swift": "import UIKit\n\nfinal class ScannerViewController: UIViewController {}\n",
    "App/ShelfApp.swift": "import SwiftUI\n\n@main\nstruct ShelfApp: App {\n  var body: some Scene { WindowGroup { RootView() } }\n}\n",
    "Widgets/RecentBooksWidget.swift": "import WidgetKit\n\nstruct RecentBooksWidget: Widget {\n  var body: some WidgetConfiguration { fatalError() }\n}\n",
    "Widgets/ShelfConfigIntent.swift": "import AppIntents\n\nstruct ShelfConfigIntent: WidgetConfigurationIntent {}\n",
    "Intents/AddBookIntent.swift": "import AppIntents\n\nstruct AddBookIntent: AppIntent {\n  func perform() async throws -> some IntentResult { .result() }\n}\n",
    "Notifications/NotificationService.swift": "import UserNotifications\n\nclass NotificationService: UNNotificationServiceExtension {}\n",
    "Share/ShareViewController.swift": "import UIKit\n\nclass ShareViewController: UIViewController {}\n",
    "App/Tests/RouterTests.swift": "enum FakeDestination { case leaked }\n",
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


def _extractor(name: str) -> dict:
    ex = next(x for x in _profile()["extractors"] if x["name"] == name)
    return {
        "name": ex["name"],
        "run": ex["run"],
        "layer": ex["layer"],
        "params": ex["params"],
        "rationale": "test",
    }


def test_ui_ios_profile_is_valid():
    profile = _profile()
    assert validate_profile(profile) == []
    assert (PROFILE.parent / "context.md").is_file()
    roles = {t["id"]: t.get("role", "intermediate") for t in profile["layers"]}
    assert roles == {
        "screen": "entry",
        "shell": "entry",
        "system": "entry",
        "view": "intermediate",
        "view_model": "intermediate",
        "repository": "intermediate",
        "client": "intermediate",
        "external": "boundary",
    }
    # 端末の中の保存も、本物のデータとして読み書きに書く (ブラウザの中の保存を書かない ui-vue-router と違う所)
    assert all(
        {"rdb", "kvs", "filesystem", "external_api"} <= set(t["io"])
        for t in profile["layers"]
    )
    assert "within" not in profile, "画面と枠の関係は、このプロファイルでは持たない"
    labels = profile["hierarchy"]["entry_labels"]

    def name(path):
        return next(
            (x["label"] for x in labels if x["contains"] in path),
            profile["hierarchy"]["level_labels"][-1],
        )

    assert (
        name("/(shell)/app") == "shell"
        and name("/(system)/widget/X") == "system"
        and name("/RouterDestination/a") == "screen"
    )
    notes = profile["hierarchy"]["notes"]

    def hit(path):
        return [n["text"] for n in notes if n["contains"] in path]

    assert (
        len(hit("/RouterDestination/bookDetail")) == 1
        and len(hit("/(system)/intent/X")) == 1
    )


def _entry_list(repo: Path, app: Path, extractors: list[dict]) -> Path:
    profile = _profile()
    path = repo / "analysis" / "entry-list.yaml"
    doc = {
        "format_version": 1,
        "target": {
            "repo": "github.example/acme/shelf-ios",
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


def test_default_rules_take_destination_cases_and_os_entry_points(
    app: Path, tmp_path_factory, capsys
):
    """行き先の enum の case 1 つ = 画面 1 つ。OS から起動される型は、準拠するプロトコルで種類を決める。取れない所は知らせる。"""
    repo = tmp_path_factory.mktemp("ios-repo")
    init_repo(repo, "ui-ios", targets="claude-code")
    assert (repo / ".abatlas" / "profiles" / "ui-ios" / "context.md").is_file()
    path = _entry_list(
        repo, app, [_extractor("swiftui-destinations"), _extractor("os-entry-points")]
    )
    capsys.readouterr()
    out = enumerate_entries(path, PROFILE)
    assert validate_entry_list(out, _profile()) == []
    got = {e["id"]: (e["path"], e["layer"]) for e in out["entries"]}
    assert got == {
        "RouterDestination.bookDetail": ("/RouterDestination/bookDetail", "screen"),
        "RouterDestination.bookDetailWithBook": (
            "/RouterDestination/bookDetailWithBook",
            "screen",
        ),  # 同じ View でも case ごと
        "RouterDestination.shelf__list": (
            "/RouterDestination/shelf_list",
            "screen",
        ),  # 名前の中の _ は重ねる
        "SheetDestination.newReview": (
            "/SheetDestination/newReview",
            "screen",
        ),  # 1 行に 2 つの case
        "SheetDestination.settings": ("/SheetDestination/settings", "screen"),
        "AppTab.home": ("/AppTab/home", "screen"),
        "AppTab.search": ("/AppTab/search", "screen"),
        "AppTab.other": ("/AppTab/other", "screen"),
        "system_s.widget.RecentBooksWidget": (
            "/(system)/widget/RecentBooksWidget",
            "system",
        ),
        "system_s.intent.AddBookIntent": ("/(system)/intent/AddBookIntent", "system"),
        "system_s.notification.NotificationService": (
            "/(system)/notification/NotificationService",
            "system",
        ),
    }
    # 行き先でない enum (SortOrder)、関連値の名前 (id、book)、設定の画面だけの intent、テストのコードは拾わない
    by = {e["id"]: e for e in out["entries"]}
    assert by["RouterDestination.bookDetail"]["attributes"] == {
        "destination_enum": "RouterDestination",
        "destination_case": "bookDetail",
    }
    assert by["RouterDestination.bookDetail"]["source"] == {
        "file": "App/Router.swift",
        "line": 4,
    }
    assert by["system_s.widget.RecentBooksWidget"]["attributes"] == {
        "conforms_to": "Widget"
    }
    err = capsys.readouterr().err
    for where in [
        "App/AppRegistry.swift:5: (for: RouterDestination.self)",  # self を省いた navigationDestination
        "App/AppRegistry.swift:18: (item: $picked)",  # 画面の中で開くもの (足さない判断は、読んで行う)
        "App/ScannerViewController.swift:3: final class ScannerViewController: UIViewController",
        "Share/ShareViewController.swift:3: class ShareViewController: UIViewController",
    ]:
        assert f"読めなかった参照: {where}" in err, (where, err)
    again = enumerate_entries(path, PROFILE)
    assert (
        again["entries"] == out["entries"]
        and again["enumerated_at"] == out["enumerated_at"]
    ), "列挙は決定的"


def test_agent_adds_uikit_shell_and_plist_entries_per_layer(
    app: Path, tmp_path_factory
):
    """読んで足す入口は、層ごとに別の listed に書く (UIKit の画面、アプリ全体の枠、Info.plist だけで決まる OS の入口)。"""
    repo = tmp_path_factory.mktemp("ios-repo")
    init_repo(repo, "ui-ios", targets="claude-code")

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
            _extractor("swiftui-destinations"),
            _extractor("os-entry-points"),
            listed(
                "agent-listed-screen",
                "screen",
                [
                    {
                        "id": "uikit_u.ScannerViewController",
                        "path": "/(uikit)/ScannerViewController",
                        "source": {
                            "file": "App/ScannerViewController.swift",
                            "line": 3,
                        },
                        "reason": "バーコードを読む画面。sheet から present している",
                    },
                    {
                        "id": "view_v.PhotoView",
                        "path": "/(view)/PhotoView",
                        "source": {"file": "App/AppRegistry.swift", "line": 15},
                        "reason": "行き先の enum を通らずに、NavigationLink(destination:) で push して開く。写真を読む",
                    },
                ],
            ),
            listed(
                "agent-listed-shell",
                "shell",
                [
                    {
                        "id": "shell_s.app",
                        "path": "/(shell)/app",
                        "name": "ShelfApp",
                        "source": {"file": "App/ShelfApp.swift", "line": 4},
                        "reason": "@main の App。起動のときに本棚を読み込む",
                    },
                ],
            ),
            listed(
                "agent-listed-system",
                "system",
                [
                    {
                        "id": "system_s.extension.ShareViewController",
                        "path": "/(system)/extension/ShareViewController",
                        "source": {
                            "file": "Share/ShareViewController.swift",
                            "line": 3,
                        },
                        "reason": "共有の拡張の NSExtensionPrincipalClass。view controller なので抽出器では取れない",
                    },
                ],
            ),
        ],
    )
    out = enumerate_entries(path, PROFILE)
    assert validate_entry_list(out, _profile()) == []
    layers = {e["id"]: e["layer"] for e in out["entries"]}
    assert (
        layers["uikit_u.ScannerViewController"] == "screen"
        and layers["view_v.PhotoView"] == "screen"
        and layers["shell_s.app"] == "shell"
    )
    assert (
        layers["system_s.extension.ShareViewController"] == "system"
        and len(layers) == 15
    )
    assert all("within" not in e for e in out["entries"])
    # 入口の層でない層に足そうとしたら、検査が落とす
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    doc["extractors"][3]["layer"] = "view"
    assert any(
        "role: entry の層ではない" in f for f in validate_entry_list(doc, _profile())
    )
