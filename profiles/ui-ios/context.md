# ui-ios プロファイル: エージェント向けの説明

対象は「iOS のアプリ」。SwiftUI (画面の行き先を enum で持つ作り) と UIKit (view controller) の両方を扱う。サーバーの API は、別のリポジトリか、分析の範囲の外にあるもの。端末の中の保存 (SwiftData / Core Data / SQLite、UserDefaults、Keychain、ファイル) は、アプリが持つ本物のデータとして扱う。入口の発見と入口ごとの分析で、このファイルと `profile.yaml` の両方を読む。

## アーキテクチャと層の連鎖

```text
screen (行き先の enum の case 1 つ = 画面 1 つ)
  → view (SwiftUI の View と modifier、UIKit の view)
    → view_model (ViewModel、@Observable / ObservableObject の状態の object)
      → repository (repository、service、manager。無いアプリもある)
        → client (HTTP、DB、端末の保存を包む自前の型)
          → external (URLSession、SwiftData、Keychain のライブラリ、OS の API。ここで終端)
                ⇢ サーバーの API (範囲の外。I/O の external_api として書く)
                ⇢ 端末の中の保存 (I/O の rdb / kvs / filesystem として書く)
```

- `screen`、`shell`、`system` が `role: entry`
  - `screen`: 行き先の enum の case 1 つ (UIKit では view controller 1 つ)
  - `shell`: アプリ全体の枠 (下の「アプリ全体の枠」)
  - `system`: アプリの画面を通らずに、OS から起動される入口 (下の「OS から起動される入口」)
- `shell` と `system` は、連鎖の先頭が替わるだけで、その先は同じ。画面と枠と OS の入口は**別々に分析する**
- `external` が `role: boundary`。ライブラリ、SDK、OS の API の呼び出しに達したら、コールスタックを閉じる
- 層は飛ばしてよい。View が view model を通さずに保存のライブラリを直接使う (`@Query`、`@AppStorage`、`modelContext.insert`) なら、`view → external` とつなぐ。層を行き来してもよい
- 層の当てはめに迷う型は、次で決める
  - HTTP の要求を組み立てて送る型、保存のライブラリを包む型、API の endpoint の定義 (`Endpoint` の enum の `path()`) → `client`
  - 画面をまたいで共有する状態の object (`CurrentAccount`、`UserPreferences` のような singleton) で、API や保存を呼ぶもの → `repository`。singleton でなくても、アカウントごとなど、画面をまたいで使う状態の object は `repository`
  - Keychain や UserDefaults を包む小さな型 (鍵の組を読み書きする struct) → `client`
  - OS が直接呼ぶ関数 (通知の delegate の `didReceive`) が、repository の型の中にあるときも、層はその型のまま (`repository`) にし、入口のフレームの直下に置く
  - 1 つの画面の状態を持つ object → `view_model`
  - それ以外の補助の関数 → 呼び出し元と同じ層
- フレームの `kind` は、次の語から選ぶ: `screen` (入口の画面)、`shell` (入口の枠)、`system` (OS から起動される入口)、`view`、`modifier`、`view_controller`、`view_model`、`function`、`service`、`client`、`library`、`os_api`
- サーバーの API は、フレームにしない。呼び出す行のフレームの `io` に、`external_api` として書く (下の「データの当てはめ」)

## 入口の判別 (抽出器のパラメータの決め方)

入口を列挙する主体は、エージェントである。抽出器は 2 つ。

| 抽出器 | 取るもの | 取れないもの (読んで足す) |
|---|---|---|
| `swiftui-destinations` (層 screen) | 名前の正規表現に合う enum の case | 正規表現から漏れた行き先の enum、UIKit の view controller、storyboard の scene、行き先の enum を通らない画面 |
| `os-entry-points` (層 system) | ウィジェット、App Intents、通知の拡張、アクションの拡張 (準拠するプロトコルで取る) | 共有の拡張、URL スキームとユニバーサルリンクの受け口、バックグラウンドのタスク |

1. 行き先を宣言した enum を見つける。`navigationDestination(for: X.self)`、`.sheet(item:)`、`.fullScreenCover(item:)`、`TabView(selection:)` に渡している型を辿る。`rule` の enum の名前の正規表現を、その名前に合わせる (名前だけで当てているので、行き先に使われていない enum を拾っていないかも確かめる)
2. 列挙を試す。出力の「読めなかった参照」を、1 件ずつ読む
3. 読めなかった場所と、Info.plist、entitlements から、入口を足す (`abatlas-extract listed`)。入口の層が 3 つあるので、`listed` を層ごとに分ける (`agent-listed-screen`、`agent-listed-shell`、`agent-listed-system`)

| 読めなかった参照・調べる場所 | どう足すか |
|---|---|
| `navigationDestination(for:)` / `(item:)`、`.sheet(item:)`、`.fullScreenCover(item:)` のうち、渡している型が、正規表現から漏れた enum | 正規表現を直して、抽出器で取る。enum の外の型 (1 つの画面の中だけの選択の値、写真を 1 枚開く値) なら、足さない (開く側の画面に含める) |
| UIKit の view controller を継いだクラス | 画面なら `/(uikit)/<クラスの名前>` で足す。`source` はクラスの宣言の行。別の View の中に埋めて使う部品 (`UIViewControllerRepresentable` で包む入力欄など) は、足さない (使う側の View の中で辿る) |
| 自前の基底クラスを継ぐ view controller | 基底クラスを `rg` で辿り、画面になるものを足す |
| storyboard (`*.storyboard`) | scene の `customClass` が、まだ入口に無い view controller なら、足す。storyboard の `storyboardIdentifier` は `reason` に書く |
| 行き先の enum を通らない画面 (`NavigationLink(destination:)`、`navigationDestination(isPresented:)` で push する View。enum が無いアプリでは、タブの根の View も) | 保存か API を使う View を `/(view)/<View の型の名前>` で足す (下の「画面の中で開くもの」)。`source` は View の型の宣言の行。`reason` に、どの画面のどの行で開くかを書く |
| 1 つの画面の中だけで使う行き先の enum (設定の画面の中の `navigationDestination(item:)` に渡す enum など) | 行き先の enum として、正規表現に足して抽出器で取る。同じ View を `NavigationLink(destination:)` でも開いているときも、enum の入口だけにする |

- 入口の id は、階層パスから記号を除いたもの。名前の中の `_` は 2 つ重ね、かっこの段は「名前 + `_` + 頭文字」にする (`/(uikit)/ShareViewController` → `uikit_u.ShareViewController`、`/(view)/FooView` → `view_v.FooView`)。抽出器の出す id (`RouterDestination.accountDetail`、`system_s.widget.LatestPostsWidget`) と同じ付け方
- 同じ View を描く case が 2 つ以上あっても、case ごとに入口にする (渡る値が違うと、読む API が違う。例: id だけを渡す case は、アカウントを取り直す)。固定の値で閉じた分岐は辿らないので (下の「フレームにするもの・しないもの」)、case ごとの分析は小さくなる
- 画面を持たない case (何も描かない `other`、別の画面を開くだけの case) も、抽出器は拾う。入口のままにし、分析で「何も描かない」「開くだけ」と書く (承認のときに、人が `rejected` にしてよい)
- タブの case が、保存された設定で並びを変えられても、case ごとに入口にする (タブの根の View が描くものは、case で決まる)
- 実行時の値から作る case (`anyTimelineFilter(filter:)` のように、関連値で中身が決まるもの) も入口にする。描く View が 1 つに決まるため
- 別の端末 (macOS、visionOS) だけで使う行き先の enum (`openWindow` に渡す window の enum など) は、入口にしない。iPhone と iPad で動くものだけを扱う。足さないことを `rationale` に書く

### 画面の中で開くもの (入れ子の画面)

行き先の enum を通らずに開く View は、開き方で分ける。

| 開き方 | 扱い | 理由 |
|---|---|---|
| push (`NavigationLink(destination:)`、`navigationDestination(isPresented:)`) で、保存か API を使う View | 入口にする (`/(view)/<View の型の名前>`) | 利用者には、別の画面に見える。開く側に含めると、設定の画面のように、1 件が十数画面ぶんになる |
| いまの画面に重ねるもの (`.sheet(isPresented:)`、`.fullScreenCover(isPresented:)`、`.alert`、`.confirmationDialog`、`.popover`)。1 つの画面からだけ開く | 入口にせず、開く側の画面に含める (`ui-vue-router` の入れ子の route と同じ) | ダイアログと同じ。開く側の操作の続き |
| いまの画面に重ねるもので、2 つ以上の画面から開く | 入口にする (`/(view)/<View の型の名前>`) | 同じ通り道を、開く画面の数だけ繰り返さない |
| 既にある入口 (enum の case) が描く View と同じ View | 新しい入口にしない。開く側は、その入口を `navigate` / `overlay` で指す | 同じ View を 2 回数えない |
| 保存も API も使わない View (見た目だけ、OS の設定を替えるだけ) | 入口にしない。確かめたことを `rationale` に書く | — |

- 開く側の画面を分析するとき、含める View は、利用者の操作で動く枝として辿る (`conditional`)。入口にした View は辿らず、つながりに書く
- 1 件が大きくなったとき (目安: フレームが 60 を超える) は、書き切ったうえで、報告に書く。分けるかは、人が決める

### アプリ全体の枠 (`shell`)

どの画面を開いても動く処理 (起動のときの読み込み、ログインの確認、通知の登録、サーバーとの接続を受け続ける処理) は、画面ごとに書かず、枠を入口として 1 回だけ分析する。抽出器は枠を拾わないので、**エージェントが `listed` で足す** (`ui-vue-router` の `shell` と同じ考え方)。

| 枠にするもの | 見つけ方 | 階層パスと id |
|---|---|---|
| アプリの根 | `@main` を付けた `App` の型 (scene の body、`scenePhase` の変化で動く処理、`.task` で動く起動の準備、environment に入れる共通の object の準備)。UIKit だけのアプリは、ここを持たない | `/(shell)/app`、`shell_s.app` |
| AppDelegate / SceneDelegate | `@UIApplicationDelegateAdaptor` で渡す型、`UIApplicationDelegate` / `UIWindowSceneDelegate` に準拠する型。起動、通知の token の登録、URL を開く callback のうち、データを読む・外へ送るもの。クラス 1 つ = 入口 1 件 | `/(shell)/delegate/<クラスの名前>`、`shell_s.delegate.<名前>` |
| ルートの View | アプリの根が最初に描く View で、タブのバーやサイドバーを持つもの (`TabView`、`NavigationSplitView`)。データを読むものだけ | `/(shell)/root/<View の型の名前>`、`shell_s.root.<名前>` |
| 枠が描く共通の view | ルートの View や、全部のタブに付く modifier (`withXxx()`) が描く view (ツールバーのアカウントの切り替え、通知の件数、トーストなど) のうち、データを読む・外へ送るもの。1 つ = 入口 1 件 | `/(shell)/part/<View の型の名前>`、`shell_s.part.<名前>` |

- 根、delegate、ルートの View の入口には、そのファイル自身 (と、そのファイルが呼ぶ `withXxx()` の modifier) が呼ぶものだけを書く。別の入口にした共通の view と、タブの中身は辿らない。共通の view の一覧と、どのタブを持つかを、入口の `summary` に書く
- タブの中身 (タブの case が描く View) と、navigation の行き先は、画面の入口なので辿らない
- 全部の画面に付ける modifier (例: `withAppRouter()`、`withSheetDestinations()`、`withEnvironments()`) のうち、case から View を作る switch だけのものは、枠にしない (画面の入口のフレームが、その case の行を根拠にする)
- データの読み書きにも外部への送信にも至らない枠は、入口にしない。確かめたことを `rationale` に書く
- どの画面がどの枠を通るかの関係 (`within`) は、このプロファイルでは持たない

### OS から起動される入口 (`system`)

アプリの画面を通らずに、OS が起動するもの。アプリと同じ保存の場所 (App Group) や、同じ API を使うことが多い。**画面と同じく、入口にする**。

| 種類 (2 段目) | 見つけ方 | 取り方 | 名前 (3 段目) |
|---|---|---|---|
| `widget` | `Widget`、`ControlWidget` に準拠する型 (`WidgetBundle` は並べるだけなので入口にしない) | 抽出器 | 型の名前 |
| `intent` | `AppIntent` とその仲間に準拠する型。設定の画面だけの intent (`WidgetConfigurationIntent`) と、選ぶ値を出すだけの型 (`AppEntity`、`EntityQuery`) は入口にしない (使う intent やウィジェットの中で辿る) | 抽出器 | 型の名前 |
| `notification` | `UNNotificationServiceExtension`、`UNNotificationContentExtension` を継ぐ型 | 抽出器 | 型の名前 |
| `extension` | 拡張の Info.plist の `NSExtensionPrincipalClass` (共有、アクションなど)。`NSExtensionRequestHandling` に準拠する型は抽出器が取る。view controller を principal class にする拡張 (共有の拡張に多い) は、読んで足す | 抽出器 / listed | 型の名前 |
| `link` | Info.plist の `CFBundleURLSchemes` (URL スキーム)、entitlements の `applinks:` (ユニバーサルリンク)。受け口のコード (`onOpenURL`、`application(_:open:options:)`、`scene(_:openURLContexts:)`、`onContinueUserActivity`) を探す | listed | URL スキームの名前。ユニバーサルリンクは `universal` |
| `background` | `BGTaskScheduler.shared.register(forTaskWithIdentifier:)`、`.backgroundTask(...)`、Info.plist の `BGTaskSchedulerPermittedIdentifiers` | listed | タスクの identifier (記号を除く) |

- listed で足すときの `source` は、受け口のコードの行 (URL スキームなら `onOpenURL` の行。Info.plist ではない)。`reason` に、Info.plist や entitlements の、どのキーで宣言しているかを書く
- 受け口のコードが見つからない宣言 (Info.plist に URL スキームはあるが、受け取るコードが無い) は、足さず、報告に書く
- intent や URL の受け口が、アプリを開いて画面へ移るだけなら、入口のフレームから、移る先の画面を `links` (`navigate`) に書いて閉じる (画面は辿らない)
- 通知の受け取り (`UNUserNotificationCenterDelegate` の `didReceive` / `willPresent`) は、アプリが動いているときの callback なので、delegate の枠 (`shell`) に含める。準拠する型が AppDelegate でなく、共有の service (通知の service が自分を delegate に入れる作り) でも、AppDelegate の入口の直下に置く (根拠は、delegate に入れている行)。AppDelegate が無いアプリでは、準拠する型を `/(shell)/delegate/<型の名前>` で足す。通知の拡張 (アプリが動いていないときに、OS が拡張を起動する) だけを `system` にする
- 通知の登録が入口をまたぐとき (OS への登録を求めるのは App、token を受けてサーバーへ登録するのは AppDelegate): それぞれの入口の `note` で、相手の入口を指す

### OS が呼ぶ関数が 2 つ以上ある入口

ウィジェット (provider の `timeline` / `snapshot` / `placeholder`)、設定の値を出す query (`AppEntity` の query の `entities(for:)` / `suggestedEntities()` / `defaultResult()`)、AppDelegate の callback は、OS が呼ぶ関数が 2 つ以上あり、コードの順が実際に動く順を表さない。

- OS が呼ぶ関数を持つ型 (provider、query、intent) は、拡張のための型なので、層を `system` にする (アプリと共有の service は、その型の層のまま)
- 読み書きに至る関数を、どれも入口のフレームの直下に置く。至らない関数は、フレームにせず、入口の `summary` に書く
- 同じ処理を 2 つ以上の関数が呼ぶときは、**主の関数**の下に 1 回だけ書き、ほかの関数の `summary` で「同じ経路」と指す。主の関数は、provider なら `timeline(for:in:)` (`getTimeline`)、query なら `entities(for:)`、AppDelegate なら `didFinishLaunching`、intent なら `perform()`
- ウィジェットや intent の `@Parameter` に選んだ値 (`AppEntity`) は、OS が query で取り直す。その query を、入口の中で辿る (`call` は `interpretation`。根拠に、`@Parameter` の行と query の行)
- ウィジェットの `Link` / `widgetURL` で開くアプリの URL は、URL の受け口の入口 (`/(system)/link/<スキーム>`) への `navigate` に書く。行き先が受け口のコードで決まるので `interpretation`
- 選べる値の候補がコードに固定で、どれを選ぶかが保存された設定や利用者の選択で決まるとき (ウィジェットのタイムラインの種類): 候補ごとに `conditional` で書く。固定の値で閉じた分岐の決まりには当てない (選ぶ値は、この入口の木のコードには書いていない)

### 共有の object の init

`AppAccountsManager.shared` のような singleton の init が、保存を読む (Keychain の全件を読む) ことがある。init は、プロセスで最初に触れたときだけ動く。

- 最初に触れる入口 (ふつうは App の `@State` を持つ `/(shell)/app`) に、`always` で書く
- ほかの入口では、その init を `conditional` (条件は「このプロセスで初めて触れたとき」) で書く。拡張とウィジェットは、アプリと別のプロセスで動くので、自分の入口に `always` で書く
- App の型と AppDelegate が同じファイルにあっても、AppDelegate の入口では、クラスの中の関数だけを辿る
- Siri の古い intent (`INExtension`) や、ウォッチのアプリは、見つけたら `extension` として足し、報告に書く

## 入口ごとの分析で見るもの

| 層 | 読む場所 | 拾うこと |
|---|---|---|
| screen | case の定義の行と、case から View を作る行 (`navigationDestination` の switch、sheet の switch、タブの switch) | 描く View、渡す値 (関連値)、固定の値で渡す引数 (`.constant(.trending)`、`mode: .blocked`) |
| shell | 枠のファイル (App、delegate、ルートの View、共通の view) | そのファイル自身が呼ぶ view model、repository と、その先。別の入口にした共通の view と、タブの中身は読まない |
| system | OS が呼ぶ関数 (`perform()`、`getTimeline`、`didReceive`、`onOpenURL` の closure) | 呼ぶ repository と client、読む保存の場所 (App Group)、開く画面 |
| view | View の body と modifier | 子の View、`.task` / `.onAppear` / `.refreshable` / ボタンの action が呼ぶ関数、`@Query` / `@AppStorage` / `@Environment(\.modelContext)` の使い方 |
| view_model | view model の型 | 呼ぶ repository と client の関数、読み書きする保存 |
| repository | 共有の service、manager | 呼ぶ client、読み書きする保存 |
| client | HTTP や保存を包む型、endpoint の定義 | URL の形、HTTP メソッド、共通の接頭辞、保存の場所 (container の名前、スイートの名前、Keychain の service) |

### フレームにするもの・しないもの

- **フレームにする**: サーバーの API の呼び出しか、端末の保存の読み書きに至る経路の上にある、View、view model、repository、client
- **フレームにしない**: 見た目だけの View (文字、画像、アイコン、余白)、書式や日付の小道具、型の定義、アニメーションと触覚。経路の上に無いものは、`summary` で触れるだけでよい
- **同じファイルの中の、外に出していない補助の関数** (`private func`、`@ViewBuilder` の小さな関数) は、フレームにしない。呼び出し元のフレームの中の処理として扱う
- **同じファイルの中の、小さな View の型** (`private struct`): 保存や API に至る (`@Query`、`@AppStorage`、`modelContext`、注入した object の関数を呼ぶ) ものだけをフレームにする。至らないものはフレームにせず、その中の業務のルールは、描く側の View のフレームに書く
- **閉じる操作** (`dismiss()`、取消のボタン): 開いた画面へ戻るだけで、行き先の入口が決まらないので、`links` に書かない。必要なら `summary` で触れる
- **ほかの画面へ移る呼び出しは、辿らない。つながりに書く**
  - `routerPath.navigate(to: .x)`、`path.append(.x)`、`NavigationLink(value: .x)` → `links` に `kind: navigate`、`target` はコードのとおり (`.statusDetail(id: status.id)`)、`entry_id` は行き先の入口 (`RouterDestination.statusDetail`)
  - `presentedSheet = .x`、`.sheet(item:)` に入れる値の代入 → `kind: overlay`、`entry_id` は sheet の入口
  - タブの切り替え (`selectedTab = .x`) → `kind: navigate`、`entry_id` は タブの入口
  - UIKit の `pushViewController`、`present`、`performSegue` → 行き先が入口なら同じく `navigate` / `overlay`。入口でなければ (画面の中で開くもの)、辿る
  - 行き先が式で決まる (URL を解釈して移る) ときは、値が読める行き先を 1 件ずつ書き、読めない分は `unknown`
- **固定の値で閉じた分岐は辿らない**: case から View を作る行が、固定の値を渡しているとき (例: `TimelineView(timeline: .constant(.trending))`、`AccountsListView(mode: .blocked)`)、その View の中で、ほかの値のときだけ通る分岐は、フレームにしない。条件と書く場所は、分析の skill の「固定の値で閉じている呼び出しは、辿らない」に従う
- **ほかの端末だけで動くコード** (`#if os(macOS)`、`#if os(visionOS)`、`#if targetEnvironment(macCatalyst)`): iPhone と iPad のアプリには含まれないので、辿らない。入口の `notes` に、辿らなかったことを書く (`UIDevice.current.userInterfaceIdiom == .pad` のような実行時の判定は、`conditional` で辿る)
- **`@Environment(Type.self)`、`@EnvironmentObject`、`@Environment(\.modelContext)` で受け取る object** (key path で受け取る modelContext も同じ。注入の行は `.modelContainer(...)`): 呼び先の型は、注入している行 (`.environment(x)`、`withEnvironments()` など) で決まる。呼び先をフレームにし、`call` は `interpretation`。根拠に、注入している行と、使っている行の両方を書く。注入が枠 (`shell`) の中にあっても、使う側の入口で、呼び先の関数を辿ってよい (注入そのものは、枠の結果に書く)
- **画面が開いたときに動く処理** (`.task`、`.onAppear`、`viewDidLoad`、`init` の中の呼び出し): `always`。**利用者の操作で動く処理** (ボタン、引っぱって更新 `.refreshable`、スワイプ、メニュー): `conditional`。値の変化を見張る処理 (`.onChange(of:)`、`.task(id:)`、Combine の `sink`): API や保存に至るならフレームにし、`call` は `interpretation`、根拠に見張りを書いた行
- **非同期の処理** (`Task { }`、`async let`): 呼び出しと同じに扱う。呼び出し元の段の下に書く
- **関数を渡して、別の View が呼ぶとき** (closure を引数で渡す、`onSaved:` の callback): 渡された関数をフレームにし、`caller` は渡している側のフレーム。`call` は `interpretation`、根拠に、渡している行と、呼んでいる行の両方。描く側が callback を渡さず、既定の `nil` が効くときは、固定の値で閉じている呼び出しとして辿らない (同じ View を、新しく作る case と直す case で使う作りに多い)- **API に届かない画面** (固定の文言を出すだけ、別の画面を開くだけ): 入口のフレームから、最後に頼るライブラリ (`SwiftUI`) を `external` フレームとして 1 つ書いて閉じる。I/O は無し。「API も保存も使わない」ことを、入口の `summary` に書く
- **1 件が大きくなったとき** (目安: フレームが 60 を超える): 止めずに書き切る。入口の `notes` と報告に、フレームの数と、分ける候補 (画面の中で開く大きな sheet、共通の行の View) を書く
- **終端の決まり**: 機械チェックは、終端のフレームが「`external` の層」「I/O を持つ」「`unknown` の主張を持つ」「業務のルールを持つ」「権限の確認を持つ」「行き先の入口が分かっているつながりを持つ」のどれかであることを求める

### 同じ処理が何度も呼ばれるとき

1 つの入口の中で、同じ処理 (定義の行が同じ関数・View・view model の関数。`external` フレームなら、ライブラリを呼んでいる同じ行) が、複数の呼び出し元から呼ばれることがある。`ui-vue-router` と同じに書く。

- その処理と、そこから先の経路は、**呼び出し元 1 つの下に 1 回だけ**書く。入口のフレームから、呼び出しを、コードに書いてある順に深さ優先で辿り、最初にその処理に着いた呼び出し元の下に書く
- それ以外の呼び出し元では、フレームを足さない。呼び出し元の `summary` に「<処理の名前> も呼ぶ。経路はフレーム `<id>` と同じ」と書く
- フレームを足さないと呼び出し元が終端になり、終端の決まりを満たせないときだけ、終端の決まりを満たす最初のフレームまで、もう一度書く
- 共通の client の関数 (`client.get(endpoint:)`) を、2 つ目の呼び出し元が別の endpoint で呼ぶとき: client のフレームは最初の呼び出し元の下に 1 回だけ書き、2 つ目の endpoint の `external` フレームは、2 つ目の呼び出し元の直下に置く (最初の経路の下にぶら下げると、呼び出し元を誤って示す)
- 一覧の行の View (例: 投稿 1 件の行) のように、多くの画面が同じ View を描くときも、画面ごとに、その画面の中で 1 回だけ書く (行の View の中の操作も、画面の経路として書く)

## 事実・解釈・不明の付け方

- **fact**: コードにそのまま書いてある (型の名前と呼び出し、URL の文字列、保存のキーの文字列、`@Model` の型の名前)。根拠はその行
- **interpretation**: 読み取って要約したもの (フレームの summary、environment で注入した object の呼び先、何のための処理か)。根拠は読んだ範囲の代表行
- **unknown**: 次の典型例ではこの理由を使う
  - 描く View や呼ぶ API が、実行時の値で決まる (型を消した View、名前で引く処理) → `dynamic_dispatch`
  - サーバーの応答や設定から、画面の作りや要求の中身を組み立てる → `generated_at_runtime`
  - 送り先のホストや URL が、別の API の応答や、実行環境の設定で決まり、値がリポジトリに無い → `not_traceable_in_repo`
  - 呼び先が scope の外 (別のリポジトリの Swift Package)、またはソースの無い依存 → `out_of_scope`
  - 配布物だけでソースが無い (`.xcframework`、バイナリの SDK) → `binary_or_vendored`

## データの当てはめ

このプロファイルの対象は、端末で動くアプリである。データの読み書きは、**サーバーの API の呼び出し**と、**端末の中の保存**の 2 つとして現れる。

### サーバーの API

- **I/O を書くフレーム**: HTTP のライブラリ (URLSession、Alamofire) や SDK を呼んでいる行の、`external` フレームに書く。共通の関数 (例: `client.get(endpoint:)`) を、呼び出し元ごとに違う endpoint で呼ぶときは、同じ行でも「同じ処理」として省かず、**endpoint ごとに `external` フレームを分ける** (`name` に URL を書く)
- アプリが繋ぐ自分のサーバーの API → `external_api` (`op: call`)。段は `host` と `path`
  - `host`: アプリが繋ぐ自分のサーバーなら、`(backend)` と書く。接続先が、利用者が選ぶサーバー (ログインした先) や、環境ごとの設定で決まることだけを理由に、`unknown` にしない。他社のサービスなら、そのホスト名
  - `path`: `<HTTP メソッド> <URL の形>` (例: `GET /api/v1/accounts/{id}`)。endpoint を enum で定義している作り (`Endpoint` の enum と `path()`、`method`) では、その定義から読んで書く (`fact`。根拠に、呼んでいる行と、endpoint の定義の行の両方)。共通の接頭辞 (`/api/v1`) は、付ける場所を 1 度読んで、付けた形で書く
  - 読むか書くかは、HTTP メソッドで分かるので、`note` に、何を読む・書くかを 1 文で書く
- **SDK のソースが範囲に無く、URL がリポジトリに無いとき** (Firebase などの SDK): `path` に `sdk:<モジュール>.<関数>` と書く。URL を推測で書かない
- サーバーからの通知を受け続ける接続 (WebSocket、Server-Sent Events) → `external_api` (`op: call`)。`note` に「受け続ける」と書く
- 計測、課金、要望の受け付けのための、SDK だけで呼ぶ他社のサービス → `external_api`。ホスト名がコードに無ければ、`host: (<SDK の名前を小文字で>)` (例: `(telemetrydeck)`、`(revenuecat)`)、`path: sdk:<型>.<関数>` (例: `sdk:TelemetryDeck.signal`)。`ui-android` と同じ書き方。設定するだけの呼び出し (`configure`、`initialize`) は、送るかどうかが SDK の中で読めないので、I/O の無い `external` フレームで閉じる
- コードに直接書いた API キーや app の ID: `settings` に書かない (環境で設定する値ではなく、値を与えるだけ)。送り先を示す値なら、その I/O の `note` に書く
- 通知の token をサーバーへ登録する呼び出し → 送り先の API を `external_api` に書く。OS への通知の登録 (`registerForRemoteNotifications`) そのものは、I/O に書かない (`external` フレームで閉じる)

### 端末の中の保存

**Web のプロファイル (`ui-vue-router`) と違い、端末の中の保存は、読み書きに書く。** モバイルのアプリでは、端末の DB や設定がアプリの持つ本物のデータで、アプリと拡張 (ウィジェット、通知の拡張) が、同じ保存の場所を介して受け渡すため。同じ保存の場所を書く入口と読む入口が、データを介したつながりに出る。

| 保存 | 種類 | 段 | 操作 |
|---|---|---|---|
| SwiftData、Core Data、SQLite (GRDB、FMDB)、Realm | `rdb` | `host: (device)`、`dbms`: 中で動くエンジン (SwiftData、Core Data、GRDB は `sqlite`、Realm は `realm`。ライブラリの名前は `note` に書く。`ui-android` の Room と同じ考え方)、`database`: container や store の名前 (既定の container なら書かない)、`table`: `@Model` の型、entity、表の名前 | 追加 (`insert`) → `create`、取得 (`@Query`、`fetch`) → `read`、値を変えて保存 → `update`、削除 → `delete` |
| UserDefaults、`@AppStorage` (`@SceneStorage` は除く) | `kvs` | `host: (device)`、`instance`: `UserDefaults` (standard) か、スイートの名前 (App Group の `group.xxx`)、`key_pattern`: キーの文字列 | 読む → `get`、書く → `set`、消す → `delete` |
| Keychain (`SecItem*`、KeychainAccess、KeychainSwift など) | `kvs` | `host: (device)`、`instance: Keychain`、`namespace`: service か access group (書いてあれば)、`key_pattern`: キー | `get` / `set` / `delete` |
| ファイル (`FileManager`、`Data.write(to:)`) | `filesystem` | `host: (device)`、`directory`: 置き場 (`Documents`、`Caches`、`tmp`、App Group の container の名前) と、その下のフォルダ、`file`: ファイルの名前 | `read` / `write` / `delete` / `list` |
| iCloud (CloudKit、`NSUbiquitousKeyValueStore`) | `external_api` | `host: (icloud)`、`path`: `sdk:CloudKit.<関数>` | `call` |

- **I/O を書くフレーム**: サーバーの API と同じく、保存のライブラリを呼んでいる行の `external` フレームに書く。名前は `<ライブラリ>.<型>.<関数>` にそろえる (例: `SwiftData.ModelContext.insert`、`SwiftData.Query`、`KeychainSwift.getData`、`UserDefaults.set`)
- **SwiftData**: `insert` は `fields` に `name: "*"` (`write`)、書く列は `note` に。`context.save()` を呼ばず、自動の保存に任せているときは、`note` に書く。`database` は、`ModelConfiguration` に名前か置き場 (URL、App Group) を書いたときだけ書く。アプリと拡張が、どちらも既定の container を使うときは、どちらも書かない (同じ段になり、つながりが結べる)
- **値 1 つの読み書き** (UserDefaults のキー 1 つ、Keychain の項目 1 つ): `fields` に `name: "*"` を書く。値が JSON などで、中の項目がコードから読めれば、項目の名前を書く
- **キーの列挙** (KeychainSwift の `allKeys`、`dictionaryRepresentation()`): kvs の操作に list は無いので、`get` に含める (`key_pattern` は読むキーの形)
- **保存の形の移し替え** (SwiftData / Core Data の migration、古いキーからの移し替え): 入口の読み書きに書かない。どの入口が先に開くかで、動く入口が変わるため (`ui-android` と同じ)
- **読み直したものを書き戻す処理** (読めた値を、同じキーへ保存し直す): `set` も書く。拡張やウィジェットが保存へ書くことが、集計に出るように
- **書かないもの**: メモリの中だけの値 (`@State`、static の変数、`NSCache`)、ライブラリが自分で持つキャッシュ (`URLCache`、画像のキャッシュのライブラリ)、画面の復元のための `@SceneStorage`。アプリのコードが、キーや表を決めて書き、後で読み戻すキャッシュ (例: タイムラインを SQLite に保存して、次の起動で出す) は、書く
- **共有の設定の object** (`UserPreferences` のように、`@AppStorage` を数十持つ singleton): その入口の経路で読み書きするキーだけを書く。起動のときに全部を読み込む処理は、枠 (`shell`) の結果に書く。画面ごとに、全部のキーを並べない
- **`@AppStorage` の読み**: その値で、処理の流れや、読み書きの相手 (どのアカウント、どのタイムライン) が変わるときだけ `get` を書く。設定の画面の既定値を決める読み (OS が呼ぶ `defaultResult()` が、保存された今のアカウントを読む) も含める。表示の色や文字の大きさだけに効く値は書かない。**書き** (`set`) は、いつも書く
- **App Group**: アプリと拡張が共有する保存の場所は、`instance` (UserDefaults)、`namespace` (Keychain の access group)、`directory` (container) に、スイートや group の名前を書く。名前は entitlements と、コードの文字列 (`UserDefaults(suiteName:)`) で確かめる。同じ名前に揃えないと、アプリと拡張のつながりが結べない
  - entitlements の値に `$(...)` の変数があるときは、`*.xcconfig` で展開して書く。リポジトリで展開できない変数 (`$(AppIdentifierPrefix)` など、署名で決まるもの) は、コードの文字の値を書き、分析リポジトリの conventions に、そろえる値を書く
  - `#if DEBUG`、`#if targetEnvironment(simulator)` で、保存の場所 (group) を変えるときは、リリースのビルドの値を書き、その分かれを `settings` (`kind: other`) に書く
- **`settings` には書かない**: 利用者が選んだ設定 (保存された値) は、データとして I/O に書く。`settings` に書くのは、ビルドの設定 (`Info.plist` の値、`xcconfig`、`#if DEBUG`)、機能の切り替え、リモートの設定 (Remote Config)
- **アプリの外の、端末の中のデータ** (写真、連絡先、カレンダー、位置): OS の API を `external_api` として書く。`host: (os)`、`path`: `<フレームワーク>.<関数>` (例: `Photos.PHPhotoLibrary.performChanges`)。利用者の許可を求める呼び出しは、`guards` (`kind: other`、`value` は求める許可の名前) に書く
