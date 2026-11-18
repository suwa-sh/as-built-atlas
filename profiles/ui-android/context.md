# ui-android プロファイル: エージェント向けの説明

対象は「Android のアプリ」。Jetpack Compose (Navigation Compose、Navigation 3) か、Fragment と navigation graph の XML で画面を作り、端末の中の保存 (Room、DataStore、SharedPreferences、ファイル) と、サーバーの API を使うもの。入口の発見と入口ごとの分析で、このファイルと `profile.yaml` の両方を読む。

Web の画面のプロファイル (`ui-vue-router`、`ui-nextjs`) と違う所は、次の 3 つ。

| 違う所 | このプロファイル | 理由 |
|---|---|---|
| 入口の種類 | 画面の行き先のほかに、OS から起動される class (Activity、Application、Service、BroadcastReceiver、ContentProvider、WorkManager の Worker) も入口 | Android では、画面を通らずに動く処理 (同期、通知の受信) が、端末の中の保存を書く。書く側を入口にしないと、保存を介したつながりが消える |
| 端末の中の保存 | 読み書きに書く | 先に端末に貯めて、画面はそこを読む作り (offline-first) では、端末の中のデータベースが本物の保存先になる |
| interface の実装 | DI の宣言 (Hilt の `@Binds` / `@Provides`) を根拠に、実装の class へ辿る | Android のアプリは、層の間を interface と DI でつなぐのがふつう。呼び出しの行だけでは、実装が決まらない |

## アーキテクチャと層の連鎖

```text
screen (Navigation の destination 1 つ)       ┐
activity (AndroidManifest の activity 1 つ)   │ 入口
shell (枠が描く共通の composable 1 つ)         │
background (画面を持たない起点 1 つ)            ┘
  → ui (composable、Fragment、state holder)
    → viewmodel (Jetpack ViewModel)
      → usecase (domain の class。無いアプリもある)
        → repository (保存先と API を束ねる class)
          → datasource (Room の DAO、DataStore を包む class、Retrofit の service、SDK を包む class)
            → external (Room、DataStore、Retrofit、WorkManager、Firebase、Android の framework。ここで終端)
```

- `screen`、`activity`、`shell`、`background` が `role: entry`。`external` が `role: boundary`
- 層は、**役割**で分ける。モジュールの名前 (`core/data`、`feature/xxx/impl`) では分けない。ただし、Android の公式のアーキテクチャに沿うアプリでは、だいたい次の対応になる。対象のモジュールと層の対応は、分析リポジトリの `analysis-conventions.md` に書いてから分析する

| 層 | 当てはめるもの | 例 |
|---|---|---|
| `ui` | composable、Fragment や View の class、ViewModel でない state holder (`rememberXxxState()` が作る class) | `ForYouScreen`、`NiaAppState` |
| `viewmodel` | `ViewModel` を継承する class | `ForYouViewModel` |
| `usecase` | domain の class (`operator fun invoke` を持つことが多い) | `GetFollowableTopicsUseCase` |
| `repository` | 保存先と API を束ねて、上の層に Flow や suspend の関数を出す class | `OfflineFirstNewsRepository` |
| `datasource` | 保存先や通信を、1 つの仕組みだけで包む class。Room の DAO、Retrofit の service | `NewsResourceDao`、`NiaPreferencesDataSource`、`RetrofitNiaNetwork` |
| `external` | リポジトリに定義が無いもの | Room、DataStore、Retrofit、OkHttp、WorkManager、Firebase、`NotificationManagerCompat` |

- 層は飛ばしてよい (ViewModel が repository を直接呼ぶ、Worker が repository を呼ぶ)。層を行き来してもよい
- フレームの `kind` は、次の語から選ぶ: `destination` (入口の画面)、`activity`、`shell`、`application`、`service`、`receiver`、`provider`、`worker`、`composable`、`fragment`、`state_holder`、`viewmodel`、`usecase`、`repository`、`dao`、`datasource`、`function`、`sdk`、`library`

## 入口の判別 (抽出器のパラメータの決め方)

入口を列挙する主体は、エージェントである。抽出器は 6 つある。アプリに無い書き方の抽出器は、入口の一覧に書かない (外したことを、報告に書く)。

| 抽出器 | 層 | 取るもの |
|---|---|---|
| `compose-typed-destinations` | screen | 型で書いた destination: Navigation 3 の `entry<Key>`、Navigation Compose の `composable<Route>` / `dialog<Route>` |
| `compose-string-destinations` | screen | 文字で書いた destination: `composable("topic/{topicId}")`、`composable(route = "...")` |
| `navigation-xml-destinations` | screen | navigation graph の XML の `<fragment>` と `<dialog>` |
| `manifest-activities` | activity | AndroidManifest の `<activity>` |
| `manifest-background` | background | AndroidManifest の `<application>` (`android:name` があるときだけ)、`<service>`、`<receiver>`、`<provider>` |
| `workers` | background | `CoroutineWorker` / `Worker` / `ListenableWorker` / `RxWorker` を直に継承する class |

XML は、`ast` の `html` で読む。先頭の `<?xml ...?>` は読めないが、要素と属性は読める。

1. destination を書いている場所を見つける。Navigation 3 なら `entryProvider { ... }` と `EntryProviderScope<NavKey>` を受け手にする関数、Navigation Compose なら `NavHost { ... }` と `NavGraphBuilder` を受け手にする関数、Fragment なら `res/navigation/*.xml`
2. `files` と `exclude` を合わせる。**テストのソース** (`src/test*`、`src/androidTest*`) と、**範囲の外のアプリ** (部品の見本のアプリ、benchmark、テスト用の manifest だけを持つモジュール) は `exclude` に書き、外したモジュールを `rationale` に書く。テストにも destination の型や manifest が出てくるので、外さないと重複する
3. 列挙を試す。出力の「読めなかった参照」を、1 件ずつ読む
4. 読めなかった定義と、抽出器で取れない入口を、`abatlas-extract listed` で足す (層ごとに別の名前: `agent-listed-screen`、`agent-listed-activity`、`agent-listed-shell`、`agent-listed-background`)

| 読めなかった参照の形 | 読む場所 | どう足すか |
|---|---|---|
| route を定数で渡した destination (`composable(TOPIC_ROUTE)`、`composable(route = TOPIC_ROUTE)`) | 定数の定義 | 値が文字で読めれば、文字の route と同じ階層と id で足す。`source` は destination の行。`name` は定数の名前 |
| Navigation 3 の `when (key) { is X -> NavEntry(key) { ... } }` | `when` の枝 | 枝 1 つ = 画面 1 つ。型の route と同じ階層と id で足す (`is ProfileKey` → `/Profile`)。`source` は枝の行 |
| route の文字に `$` で値を埋め込んだ destination | 埋め込んだ値の定義 | 値が固定の文字で決まれば足す。実行時の値で決まるなら足さず、報告に場所と理由を書く |

- 階層と id は、`profile.yaml` の `hierarchy.derivation` と、抽出器の `id` のとおり。`listed` で足す入口も、同じ付け方にする
  - 型の route: 型の名前を 1 段 (末尾の `NavKey` / `Route` / `Destination` を落とす。入れ子の class は `.` でつないだまま)。`ForYouNavKey` → `/ForYou`、id `ForYou`。`Screen.Home` → `/Screen.Home`、id `Screen.Home`
  - 文字の route: `/` で区切って段にする。値が入る段 `{topicId}` → id では `topicId_d`。`?` から後ろの省ける引数は落とす
  - 名前の中の `_` は、id で 2 つ重ねる (ほかのプロファイルと同じ考え方)
  - 型の route と文字の route が同じ id になったら (例: `HomeRoute` と `"home"` は別の id なので、大文字と小文字まで同じとき)、列挙が止まる。そのリポジトリの抽出器の `id.replace` を足して分ける
- 入れ子の graph (`navigation<Graph>`、`navigation(route = ...)`、XML の `<navigation>`) は、入口にしない。中の destination だけが入口
- 同じ画面の composable を指す destination が 2 つ以上あっても、destination ごとに入口にする (渡る引数が違う)
- 1 つの destination の中で、list と detail を並べて描く作り (Navigation 3 の `ListDetailSceneStrategy` の `metadata`) も、destination 1 つ = 入口 1 件。並べる相手の destination は、別の入口のまま
- **型と文字が混ざるアプリ** (型の route へ移る途中のアプリ) では、両方の抽出器を書く

### 製品の種類 (build variant) を 1 つに決める

Android のアプリは、product flavor (例: `demo` と `prod`) と build type で、入る class が変わる (`src/<flavor>/` の下のソースと manifest、flavor ごとの DI の module)。

- 分析する variant を 1 つ決めて、分析リポジトリの `analysis-conventions.md` に書く。既定は、利用者に配るもの (例: `prodRelease`)
- 入口の発見: 決めた variant に入らない source set (`src/demo/` など) の manifest は、抽出器の `exclude` に書く。決めた variant にしか無い入口 (例: `src/prod/` の manifest にだけある service) は、入口にする
- 分析: 決めた variant の DI の宣言で、実装を決める。ほかの variant の実装は辿らず、分かれ目のフレームの `summary` に、名前だけ書く

### アプリ全体の枠 (`activity` と `shell`)

`ui-vue-router` の `shell` と同じ考え方で、どの画面を開いても動く処理を、画面ごとに書かず、枠を入口として 1 回だけ分析する。

| 枠にするもの | 入口の層 | 見つけ方 | 階層パスと id |
|---|---|---|---|
| Activity | `activity` | 抽出器 `manifest-activities` | `/(activity)/<class 名>`、`activity_a.<class 名>` |
| 枠が描く共通の composable | `shell` | エージェントが読んで `listed` で足す | `/(shell)/<composable 名>`、`shell_s.<composable 名>` |

- **Navigation の host を置く Activity** (Activity が 1 つの作り) は、アプリ全体の枠である。Activity の入口では、Activity 自身の処理 (`onCreate`、ViewModel、splash、テーマや設定の読み込み、intent の解釈) と、`setContent` の root の composable (`NiaApp` など) 自身の処理 (上や下のバー、未読の印、通信の状態の表示など) を書く。host の中の destination は、画面の入口なので辿らない
  - Activity の入口のフレームの `source` は、Activity の class の定義の行 (結果の `entry.source` は、入口の一覧のまま manifest の行)
  - root の composable が使う state holder (`NiaAppState` など) の state は、ViewModel の state と同じに扱い、入口のフレームの真下に置く。メモリの中の状態しか持たない state holder (戻る先の履歴など) は、フレームにしない
  - 上や下のバーから画面を移るつながりは、`links` の `navigate` で、値が読める行き先を 1 件ずつ書く
- **host を置かず、1 つの画面を描く Activity** (Activity が画面ごとにある作り) は、その Activity が画面である。終端まで辿る
- **枠が描く共通の composable**: root の composable が直接描く composable (設定の dialog、上のバーの中の検索など) のうち、保存先を読み書きする・外へ送るもの。1 つ = 入口 1 件
  - `source` は、composable の定義の行。`reason` に、どの枠が、どの行で描いているかを書く
  - 枠の入口 (Activity) では、別の入口にした composable を辿らず、名前を `summary` に書く。描いているフレームの `links` に、その入口を書く: 利用者の操作で開く dialog は `overlay`、いつも描く composable は `embed`。どちらも `entry_id` を書く
  - 枠の中だけで動く小さな composable (保存先を読み書きしないもの) は、入口にしない
  - 保存先を読み書きする共通の composable は、枠の大きさによらず、いつも分ける (枠を 1 件にまとめると大きくなりすぎる。分けると、どの composable が何を読むかが、一覧で見える。`ui-vue-router` と同じ理由)
- **リポジトリに class が無い activity** (ライブラリの画面に、theme を当てるためだけに manifest に書いたもの。例: OSS のライセンス表示) も、抽出器は取る。入口のままにし、報告に「承認で外す候補」として書く
- どの画面がどの枠を通るかの関係 (`within`) は、このプロファイルでは持たない (画面と枠が別のモジュールにあり、置き場のフォルダでは決まらない)。枠の入口の `summary` に、host に並ぶ destination を書く

### 画面を持たない起点 (`background`)

| 起点 | 取り方 | 階層パス | 入口のフレームから辿るもの |
|---|---|---|---|
| Application の class | `manifest-background` (`<application android:name>`) | `/(background)/application/<class 名>` | `onCreate` が呼ぶ初期化 |
| Service (FCM の受信を含む) | `manifest-background` | `/(background)/service/<class 名>` | `onStartCommand`、`onMessageReceived`、`onNewToken` など |
| BroadcastReceiver | `manifest-background`。コードで登録する receiver (`registerReceiver`) のうち、画面と関係なく受け続けるもの (Application や Service が登録するもの) は、読んで `listed` で足す | `/(background)/receiver/<class 名>` | `onReceive` |
| ContentProvider | `manifest-background` | `/(background)/provider/<class 名>` | `query`、`insert`、`update`、`delete` |
| WorkManager の Worker | `workers` | `/(background)/worker/<class 名>` | `doWork` |

- id は、`(background)` を `background_b` にして、段を `.` でつなぐ (`background_b.worker.SyncWorker`)
- **ほかの Worker に仕事を渡すだけの Worker** (Hilt の都合で置く `DelegatingWorker` など。class の名前を受け取って、本物の Worker を作って呼ぶもの) も、抽出器は取る。入口のままにし、報告に「承認で外す候補」として書く。本物の Worker が、それぞれ入口になる
- `androidx.startup` の `Initializer` の実装は、ライブラリが manifest に足す provider から呼ばれる。Application の入口から呼ばれていれば、その中で辿る。どこからも呼ばれていなければ、`listed` で `background` の入口として足す (`/(background)/initializer/<class 名>`)
- ライブラリが manifest の合成で足す Service や receiver (リポジトリの manifest に無いもの) は、入口にしない
- `callbackFlow` などの中で登録して、Flow が購読されている間だけ受ける receiver や callback (時刻帯の変化、通信の状態の監視) は、入口にしない。購読する入口の中で、包む class を `datasource` のフレームにし、登録の呼び出し (`registerReceiver`、`registerNetworkCallback`) を `external` のフレームで閉じる (I/O は無し)
- **ディープリンクと、通知を押したときの起動**は、入口にしない。受ける Activity の入口で、intent を解釈して画面へ移る所を、`links` の `navigate` に書く。通知を出す側 (Worker など) は、通知の `PendingIntent` の行き先を `links` の `navigate` に書く

- **同じ短い名前の class が、別の package にあるとき** (`com.foo.MainActivity` と `com.bar.MainActivity`): 既定の抽出器は、package を落として class の名前だけを段にするので、同じ id になり、列挙が止まって知らせる。そのリポジトリでは、抽出器の `segments.replace` を、package の最後の段を残す形に直す (`profile.yaml` の注釈に例がある。`foo-MainActivity`)。manifest の activity だけでなく、service / receiver / provider / Worker も同じ

## 入口ごとの分析で見るもの

| 層 | 読む場所 | 拾うこと |
|---|---|---|
| screen | destination の宣言 (ラムダ) と、描く composable、Fragment の class | ViewModel の作り方 (`hiltViewModel()` と、route の引数の渡し方)、画面を移る呼び出し |
| activity | Activity の class と、`setContent` の root の composable | lifecycle の method が呼ぶ処理、ViewModel、intent の解釈、枠が描く composable |
| shell | 枠が描く共通の composable | その composable の ViewModel と、その先 |
| background | OS が呼ぶ method | 呼ぶ repository、data source、SDK、Worker の登録、通知 |
| ui | composable、Fragment | 子の composable、ViewModel の state の購読、利用者の操作で呼ぶ ViewModel の method |
| viewmodel | ViewModel の class | 注入した use case と repository の呼び出し、state を作る Flow |
| usecase / repository | class の本体 | 呼ぶ repository と data source |
| datasource | DAO の interface、DataStore を包む class、Retrofit の service と、それを包む class | 問い合わせ (`@Query`) の表と列、DataStore の項目、API の path |

### フレームにするもの・しないもの

- **フレームにする**: 保存先の読み書きか、API の呼び出しに至る経路の上にある、composable、ViewModel、use case、repository、data source の method
- **フレームにしない**: 見た目だけの composable (ボタン、カード、アイコン、design system の部品)、theme、文言や日付の書式、型の定義、Hilt の module そのもの (根拠の行としては使う)
- **class は、呼ばれる method ごとに分ける**。ViewModel や repository の class 1 つに、多くの method がある。入口から呼ぶ method だけをフレームにし、`name` に `<class 名>.<method>` と書く
- **interface の呼び出し**: 呼び出しの行で、interface の method を呼んでいるときは、DI の宣言 (Hilt の `@Binds` の関数、`@Provides` の関数の戻り値) で実装の class を決め、実装の method をフレームにする。`call` の根拠に、呼び出しの行と、DI の宣言の行の両方を書く (両方あれば `fact`)。実装が 1 つしか無く、DI の宣言を探さなくても決まるときも、宣言の行を根拠に入れる
- **ViewModel の作り方**: `hiltViewModel()` / `viewModel()` / `by viewModels()` の行を、入口 (か ui) から ViewModel のフレームへの `call` の根拠にする。constructor の `init` で動く処理と、state を作る Flow (`stateIn`) は、画面が描かれれば動くので `always`
- **ViewModel のフレームの置き場**: state (`StateFlow`) を作るフレーム (`<ViewModel>.<state の名前>`) は、ViewModel を作るフレーム (入口か ui) の真下に置く。利用者の操作で動く method は、その操作が起きる composable のフレームの下に置く (分析者が違っても、同じ木になる)
- **関数を渡して、別の関数が呼ぶとき** (composable に `onTopicClick = navigator::navigateToTopic` を渡す、共通の手順の関数にラムダを渡す): 渡された関数をフレームにし、`caller` は渡している側のフレーム。`call` は `interpretation` にし、根拠に、渡している行と、呼んでいる行の両方を書く。composable に限らない
- **違う関数を渡されて、複数の呼び出し元から呼ばれる共通の手順の関数** (例: 話題とニュースの同期が、それぞれのラムダを渡して呼ぶ `changeListSync`): フレームにしない。呼び出し元ごとのフレームの中の処理として扱い、その手順の業務のルールは、呼び出し元のフレームごとに書く (フレームにすると、「同じ処理は 1 回だけ」の決まりで、2 つ目の呼び出し元の呼び先が、1 つ目の下に入ってしまう)
- **同じ class の中で、受け取った値をほかへ渡すだけの method** (Worker が自分を `Synchronizer` として渡し、版の読み書きを data source に渡すだけの method): フレームにせず、呼び出しの根拠に行を入れる
- **Flow の購読**: composable が `collectAsStateWithLifecycle()` などで state を購読し、その state が repository の Flow を `combine` で組み立てているとき、repository の読み込みは、画面が描かれている間は動くので `always`。`call` の根拠は、state を組み立てる行
- **利用者の操作で動く処理** (`onClick` などから呼ぶ ViewModel の method): その操作で最初に動く段を `conditional` にし、`condition` に操作を書く。`viewModelScope.launch` の中で動くことは、`summary` に書くだけでよい
- **I/O を書くフレーム**: 保存先 (Room、DataStore、SharedPreferences、ファイル) の読み書きも、サーバーの API の呼び出しも、**`external` のフレームに書く** (`ui-vue-router` の「API の呼び出しは、ライブラリを呼んでいる行の `external` のフレームに書く」と同じ向き。`ui-ios` とも同じ)。`datasource` のフレームは、I/O を持たずに、その `external` のフレームを呼ぶ
- **`Room` の DAO**: DAO の interface の method を `datasource` のフレームにする (`kind: dao`、`name: <DAO>.<method>`、`source` は method の宣言の行)。その子に `external` のフレームを 1 つ書き (`kind: library`、`name: Room`)、`source` は注釈 (`@Query`、`@Upsert`、`@Insert`、`@Delete`) の行にする (Room の生成コードはリポジトリに無いので、リポジトリの中で Room を使っている箇所は、注釈の行)。I/O は、この `external` のフレームに書く。注釈の行が違えば、別の `external` のフレーム
- **Retrofit の service**: service の interface の method を `datasource` のフレームにし (`source` は method の宣言の行)、その子の `external` のフレーム (`kind: library`、`name: Retrofit`、`source` は `@GET` などの注釈の行) に I/O を書く
  - Retrofit の service の interface を、別の class が包んで、上の層には自前の interface を出す作り (`NiaNetworkDataSource` を `RetrofitNiaNetwork` が実装し、中で private の `RetrofitNiaNetworkApi` を呼ぶ) では、`datasource` のフレームを 2 段にする: DI で決まる実装の method (`RetrofitNiaNetwork.getTopics`) と、注釈で中身が決まる service の method (`RetrofitNiaNetworkApi.getTopics`)。I/O は、その先の `external` のフレームに書く
- **DataStore、SharedPreferences、ファイル**: ライブラリを包む method (`NiaPreferencesDataSource.setFollowedTopicIds`) を `datasource` のフレームにし、ライブラリの関数を呼んでいる行 (`dataStore.data`、`dataStore.updateData`、`prefs.edit()`、`File.writeText`) を `source` にした `external` のフレーム (`kind: library`、`name: DataStore` / `SharedPreferences` / `java.io.File` など) に I/O を書く
- **SDK と Android の framework** (Firebase、WorkManager、通知、`ConnectivityManager` など): 呼んでいる行を `source` にした `external` のフレームで閉じる。import の行を `source` にしない
  - SDK を包む自前の class の method (`FirebaseAnalyticsHelper.logEvent`) は、`datasource` のフレーム (I/O なし) にし、その先の `external` のフレーム (`kind: sdk`、`name: FirebaseAnalytics.logEvent`) に I/O を書く
  - 同じ SDK の呼び出しの行を、入口の中の複数の所から呼ぶときも、`external` のフレームは 1 つ (「同じ処理が何度も呼ばれるとき」)。送る項目は、この入口から送るものを、まとめて `fields` に書く
- **アプリの外の画面を開く** (Chrome Custom Tab、`startActivity` でほかのアプリの画面): `external` のフレーム (`kind: library`) で閉じる。I/O は無し。同じアプリの Activity を開くときは、下の「画面を移る呼び出し」
- **Android の実行時の権限の確認** (`checkSelfPermission`、`ActivityCompat.shouldShowRequestPermissionRationale` で止める所): 確認している段の `guards` に、`kind: permission` で書く。`value` は、実行時に比べる権限の文字そのもの (`android.permission.POST_NOTIFICATIONS`。定数の名前 `Manifest.permission.POST_NOTIFICATIONS` は書かない)
- **WorkManager の登録** (`enqueue`、`enqueueUniqueWork`): `external` のフレーム (`kind: library`、`name: WorkManager.<method>`) を書き、そのフレームの `links` に、登録した Worker の入口を `trigger` で書く (`target` は Worker の class 名、`entry_id` は Worker の入口の id)。Worker の中は辿らない
- **画面を移る呼び出し** (`navigator.navigate(TopicNavKey(id))`、`navController.navigate("topic/$id")`、`startActivity(Intent(context, X::class.java))`): 呼んでいるフレームの `links` に `navigate` で書く。`target` はコードに書いてあるとおり (型の名前、route の文字、Activity の class 名)。行き先の入口が分かれば `entry_id` を書く。行き先の中は辿らない
  - 移る処理が入口のラムダの中にあり、それを関数として子の composable に渡すとき: 押される composable に近いフレームに書き、`status: interpretation` (根拠は、渡している行と、呼んでいる行)
  - 戻る (`navigator.goBack()`、`popBackStack()`): 行き先が履歴で決まるので、`links` に書かない。入口の `summary` に書く
  - 通知の `PendingIntent` と、ディープリンクの `Intent`: `target` は、intent に書いた行き先のとおり (component の class 名の文字、URI)。受ける Activity の入口を `entry_id` に書く。URI は、class 名を書いたときは `note` に書く
- **画面と、アプリ全体の枠**: 画面を分析するとき、枠 (Activity、root の composable、枠が描く共通の composable) は辿らない
- **実行時に通らない分岐**: 分析の skill の「固定の値で閉じている呼び出しは、辿らない」に従う
- **1 件が大きくなったとき** (目安: フレームが 60 を超える): 止めずに書き切る。入口の `notes` と報告に、フレームの数と、分ける候補 (枠が描く共通の composable、dialog の先の枝) を書く。分けるかは、人が決める
- **終端の決まり**: 機械チェックは、終端のフレームが「`external` の層」「I/O を持つ」「業務のルールを持つ」「権限の確認を持つ」「行き先の入口が分かっているつながりを持つ」「`unknown` の主張を持つ」のどれかであることを求める
- **保存先も API も使わない画面** (固定の文言を出すだけ): 入口のフレームから、最後に頼るライブラリ (`Jetpack Compose`) を `external` のフレームとして 1 つ書いて閉じる。保存先を使わないことは、入口の `summary` に書く

### 同じ処理が何度も呼ばれるとき

1 つの入口の中で、同じ処理 (定義の行が同じ method や composable) が、複数の呼び出し元から呼ばれることがある (例: 2 つの ViewModel の state が、同じ repository の Flow を読む)。フレームは木 (`caller` は 1 つ) なので、`ui-vue-router` と同じに書く。

- その処理と、そこから先の経路は、**呼び出し元 1 つの下に 1 回だけ**書く。どの呼び出し元の下に書くかは、入口のフレームから、呼び出しを、コードに書いてある順 (同じ関数の中では行の順、同じ行なら左から) に深さ優先で辿り、最初にその処理に着いた呼び出し元
- それ以外の呼び出し元では、フレームを足さない。呼び出し元の `summary` に「<処理の名前> も呼ぶ。経路はフレーム `<id>` と同じ」と書く
- フレームを足さないと呼び出し元が終端になり、終端の決まりを満たせないときだけ、終端の決まりを満たす最初のフレームまで、もう一度書く。もう一度書いたフレームには、権限の確認・設定・業務のルールを繰り返さない

## 事実・解釈・不明の付け方

- **fact**: コードにそのまま書いてある (呼び出しの行、DI の宣言の行、`@Query` の SQL、`@GET` の path、DataStore の項目の名前)。根拠はその行
- **interpretation**: 読み取って要約したもの (フレームの summary、何のための処理か)。関数を渡して、別の関数が呼ぶもの (`onTopicClick = navigator::navigateToTopic` を渡し、子が押されたときに呼ぶ) の `call` と `links`。根拠は、渡している行と、呼んでいる行
- **unknown**: 次の典型例ではこの理由を使う
  - 呼ぶ実装が、実行時の値で決まる (class の名前を文字で受け取って作る、`when` の外の値で選ぶ) → `dynamic_dispatch`
  - 送り先のホストが、build の設定 (`local.properties`、secrets の plugin) で決まり、値がリポジトリに無い → host は `(backend)` と書き、それだけでは `unknown` にしない (下の「データの当てはめ」)
  - 呼び先が、決めた variant に入らない、または scope の外のモジュール → `out_of_scope`
  - 配布物 (AAR、JAR) だけでソースが無い → `binary_or_vendored`

## データの当てはめ

端末の中の保存は、**サーバーのデータと同じく、読み書きに書く**。Web の画面のプロファイルが「ブラウザの中の保存は書かない」とするのと反対。どの入口でも同じ綴りになるように、段を次のとおりに書く (Worker が書く表と、画面が読む表が、保存を介したつながりで結ばれる)。

| 保存の仕組み | 種類 | 段 | 操作 |
|---|---|---|---|
| Room (SQLite) | `rdb` | `host: (device)`、`dbms: sqlite`、`database`: `Room.databaseBuilder` に渡したファイル名、`table`: `@Entity(tableName = ...)` (無ければ class 名) | `@Query` の SQL で決める。`@Insert` → create、`@Upsert` → create と update、`@Update` → update、`@Delete` → delete |
| Preferences DataStore | `kvs` | `host: (device)`、`instance`: `preferencesDataStore(name = ...)` の名前、`key_pattern`: key の名前 | `data` を読む → get、`edit` → set |
| Proto DataStore | `kvs` | `host: (device)`、`instance`: `dataStoreFile(...)` のファイル名、`key_pattern`: message の型の名前 (例: `UserPreferences`)。触る項目は `fields` に書く | `data` を読む → get、`updateData` → set |
| SharedPreferences | `kvs` | `host: (device)`、`instance`: `getSharedPreferences` に渡した名前 (既定のものは `(default)`)、`key_pattern`: key の名前 | `getXxx` → get、`edit().putXxx` → set、`remove` → delete |
| アプリが書くファイル | `filesystem` | `host: (device)`、`directory`: 置き場の API (`filesDir`、`cacheDir`、`getExternalFilesDir`) と、その下のフォルダ、`file`: ファイル名 | read / write / append / delete / list |
| 自分のサーバーの API (Retrofit、Ktor、OkHttp) | `external_api` | `host: (backend)`、`path`: `<HTTP メソッド> <base URL の path を付けた形>` (例: `GET /topics`)。組み立て式の値の部分は `{名前}` | call |
| 他社のサービス (URL がコードにある) | `external_api` | `host`: ホスト名、`path`: 上と同じ形 | call |
| SDK だけで呼ぶ他社のサービス (Firebase Analytics、Crashlytics、FCM) | `external_api` | `host`: `(<SDK の名前>)` (例: `(firebase-analytics)`、`(firebase-messaging)`)、`path`: `sdk:<class>.<method>` (例: `sdk:FirebaseAnalytics.logEvent`、`sdk:FirebaseMessaging.subscribeToTopic`)。送り先を推測で書かない | call |

- Room の `@Query` で、列を選ばずに行を取るとき (`SELECT *`) と、`@Upsert` で行をまるごと書くときは、`fields` に `name: "*"` を 1 つ書く。`WHERE` と `JOIN` の列は `filter`
- `@Relation` や `@Transaction` で、関連の表も読む DAO の method (例: 記事と、記事に付いた話題を一緒に読む) は、関連の表ごとに I/O を書く (`interpretation`。根拠は、`@Relation` の行と、関連の class の `@Entity` の行)
- 全文検索の表 (`@Fts4`) も、表として書く
- 外部キーの `onDelete = ForeignKey.CASCADE` で、行を消すと別の表の行も消えるときは、消す DAO の `external` のフレーム (Room) に、消える表の `delete` の I/O を足す (`interpretation`。根拠は、消す DAO の注釈の行と、`@ForeignKey` の行)
- DataStore の項目の名前は、データの側の名前で書く: Proto DataStore なら `.proto` の定義の項目名を、書いてあるとおりに (`followed_topic_ids`。Kotlin の生成コードの名前 `followedTopicIdsMap` は使わない)、Preferences DataStore なら key の値 (`stringPreferencesKey("theme")` の `theme`)
- Proto DataStore の `data` を読むときは、読んだ message から取り出す項目 (写す関数が読む項目) を `read` で書く。`updateData` で書くときは、書き換える項目を `write`、書く値を決めるために読む項目を `read` で書く
- 自分のサーバーの API の `fields`: 送る引数 (query、path、body) は `write`、応答の項目は `read`。項目の名前は、通信用の model (`NetworkTopic` など) の、通信で使う名前 (`@SerialName` があればその値)
- DataStore や Room の migration (初めて開くときに動く書き換え。`DataStoreFactory.create(migrations = ...)`、`Room.databaseBuilder(...).addMigrations(...)`) は、どの入口が先に開くかで動く入口が変わるので、入口の読み書きに書かない。保存先を読む `datasource` のフレームの `summary` に、migration があることを書く
- **書かないもの**: メモリの中だけの状態 (`StateFlow`、`MutableStateFlow`、`SavedStateHandle`、`remember`)、画像のキャッシュ (Coil、Glide が自分で持つもの)、WorkManager や Firebase が自分の中に持つ保存。どれも、アプリのコードが表や項目を決めていない
- **アプリに同梱したファイル** (`assets`、`res/raw`): 見た目のために読むもの (文言、画像、フォント) は書かない。保存先や API の代わりに読むもの (見本の JSON を、API の応答の代わりに読む) だけ、`filesystem` の read として書く (`directory: (assets)`)
- **base URL**: Retrofit の `baseUrl(...)` に渡す値が、`BuildConfig` などの build の設定から来て、値がリポジトリに無いときは、`host: (backend)` と書く。base URL に path (例: `/api/v1/`) が書いてあれば、`path` の前に付ける
- 通知を出すこと (`NotificationManagerCompat.notify`) は、読み書きに書かない。`external` のフレームで閉じ、通知を押したときの行き先を `links` に書く
- 端末の状態を読む framework の API (通信の状態、時刻帯の変化) は、読み書きに書かない。`external` のフレーム (`kind: library`) で閉じる
