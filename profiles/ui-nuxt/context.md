# ui-nuxt プロファイル: エージェント向けの説明

対象は「Nuxt で作った、画面を持つシステム」。ファイルの置き場 (`pages/`) がルーティングになる作り。サーバー側 (`server/`) を同じリポジトリに持つシステムにも、持たずに別のバックエンドの API を呼ぶシステムにも使う。入口の発見と入口ごとの分析で、このファイルと `profile.yaml` の両方を読む。

## アーキテクチャと層の連鎖

```text
page (pages/ の Vue ファイル 1 つ)
  → component (Vue コンポーネント、composable。import 文が無くても自動で読み込まれる)
    → store (Pinia。状態と、API を呼ぶ action)
      → api_client (HTTP を包む自前の関数。プラグインが provide した API の client も。無いシステムもある)
        → external (HTTP のライブラリ、生成された SDK。ここで終端)
              ⇢ 別のバックエンドの API (範囲の外。I/O の external_api として書く)
        ⇢ api_route (サーバー側を同じリポジトリに持つとき。server/api、server/routes の handler。URL でつながる)
          → query (サーバー側の関数: server/utils、問い合わせ、認証・権限の検査)
            → external (ORM・DB クライアント・キャッシュ・ストレージ。ここで終端)
```

- `page`、`layout`、`shell`、`part` が `role: entry`。page ファイル 1 つ = 入口 1 件、layout ファイル 1 つ = 入口 1 件。アプリ全体の枠 (`shell`) は、app.vue、error.vue、global の route middleware、server middleware、プラグイン、枠が描く共通の部品を、それぞれ 1 件
- `layout`、`shell`、`part` は、連鎖の先頭が替わるだけで、その先は同じ。画面と枠は**別々に分析する** (下の「画面と、画面を包むもの」)
- `external` が `role: boundary`。ライブラリや SDK の呼び出しに達したら、コールスタックを閉じる
- 層は飛ばしてよい。コンポーネントが store を通さずに SDK を直接呼ぶなら、`component → external` とつなぐ。層を行き来してもよい (例: store → 補助の関数 → store)
- 層の当てはめに迷う関数 (`utils/` などの、コンポーネントでも store でもない関数) は、次で決める: HTTP や外部のライブラリを包む関数 → `api_client`。それ以外 (store を呼ぶだけの補助の関数など) → `component`。`server/` の下の関数は、`api_route` (受け口の handler) か `query` (それ以外)
- フレームの `kind` は、次の語から選ぶ: `route` (入口の page)、`layout`、`shell`、`middleware`、`plugin`、`component`、`composable`、`function`、`store_action`、`handler`、`sdk`、`library`
  - `external` のフレームの `sdk` と `library` の分け方 (`ui-android` と同じ): ある外のサービスと話すために、そのサービスが配るか、そのサービス用に作ったクライアントの関数は `sdk` (例: 対象のバックエンドの API の SDK、`posthog-js` のような外のサービスの SDK)。どのサービスにも使える部品 (`fetch`、axios、socket.io のクライアント、router の関数) と、SDK の中の素の HTTP の口 (SDK が持つ axios のインスタンスで、パスを書いて呼ぶ所) は `library`。前に分析した結果の別の分け方は、誤りではない (レビューは、指摘しない)

### サーバー側を持つかどうか

| 作り | 見分け方 | 書き方 |
|---|---|---|
| サーバー側を同じリポジトリに持つ | scope の中に `server/api/`、`server/routes/` がある | 画面から、受け口の URL を呼ぶ段を `api_route` のフレームにつなぎ、`query` → `external` まで辿る (下の「画面からサーバー側の受け口への橋渡し」)。データの読み書きは、サーバー側のフレームに書く |
| サーバー側を持たない (別のバックエンドを呼ぶ) | `server/` が無い。または、呼んでいる URL に当たる受け口が scope に無い | `ui-vue-router` と同じ。バックエンドの API は、フレームにしない。呼び出す行のフレームの `io` に、`external_api` として書く (下の「データの当てはめ」) |

1 つのシステムに、両方が混ざってもよい (自分の受け口と、別のバックエンドの両方を呼ぶ)。呼び出しごとに、当たる受け口が scope にあるかで決める。

## 入口の判別 (抽出器のパラメータの決め方)

1. 置き場を確かめる。Nuxt 4 の既定は `app/` の下 (`app/pages`、`app/layouts`、`app/middleware`、`app/app.vue`)。Nuxt 3 の作り (`compatibilityVersion` や `srcDir` を見る) では scope の直下 (`pages`、`layouts`、`middleware`、`app.vue`)。`nuxt.config` の `srcDir` と `dir` を読んで、抽出器ごとに `files`・`exclude`・`segments.strip_prefix` を同じ場所にする
2. `nuxt.config` の `ignore` と `.nuxtignore`、`pages` の設定を読む。そこで外している page (本番では外す試しの画面など) は、抽出器の `exclude` に写し、`rationale` に書く
3. 列挙を試し、件数と階層を見る
4. 抽出器で取れない入口を、`listed` で足す (下の「アプリ全体の枠」と「登録表から選ばれて描かれる部品」)

### 画面 (page) の階層と id

- 階層パスは、**URL ではなく、置き場** (pages ディレクトリからの相対) を表す。拡張子を除いたファイル名が最後の段になり、`index` の段も落とさない (`pages/index.vue` → `/index`、`pages/account/index.vue` → `/account/index`)
  - 理由: 入れ子の親の page (`a.vue`) と、その子 (`a/index.vue`)、さらにその子 (`a/index/index.vue`) は、URL が同じになる。`index` を落とすと、別の入口が同じ id になり、列挙が止まる
  - URL は、入口の `summary` に書く (例: 「URL は `/:typeOrId/:baseId`。親の page `/index/[typeOrId]` の中に描かれる」)
- URL に出ない入れ物 `(group)` は落とす (`ui-nextjs` と同じ)
- 名前が `-` で始まるファイルとフォルダの下は、ルーティングの対象外なので拾わない (既定の `exclude`)。Nuxt の既定の無視の規則 (`**/-*.*`) は、点の無いフォルダ名 (`-components`) に当たらないことがあるが、そういうフォルダは部品の置き場として使われるので、安全側で外している。そのフォルダのファイルが本当に page として動くなら、`exclude` を直す
- 入口の id は、階層パスから記号を除いたもの。段の種類は「`_` + 1 文字」の印で表す (`ui-nextjs` にそろえる): `[id]` → `id_d`、`[[id]]` → `id_o`、`[...slug]` → `slug_c`、`[[...slug]]` → `slug_o`。値と静的な文字が混ざる段 (`users-[id]`) は `users-id_d`。名前の中の `_` は 2 つ重ねるので、同じ名前の静的な段 (`/users/id` と `/users/[id]`) が同居しても別の id になる
- 列挙が「id が 2 つのファイルから出た」で失敗したら、記号だけが違う名前の page が同居している。黙って片方を捨てず、`id.replace` にそのリポジトリ向けの置換を足して区別する
- 抽出器が付ける `attributes`: `nested` (`<NuxtPage>` を描く、入れ子の親)、`page_meta` (`definePageMeta` がある)、`layout` (`definePageMeta` で layout を名前で選んでいる)、`middleware` (`definePageMeta` で route middleware を指している)、`file_segments` (加工前の段)
- 別の画面へ転送するだけの page (`navigateTo` だけ、`definePageMeta` の `redirect` だけ) も、入口のままにし、分析で「転送するだけ」と書く (承認のときに、人が `rejected` にしてもよい)

### 入れ子の page (`a.vue` と `a/`)

同じ名前の page ファイルとフォルダが並ぶとき (`pages/a.vue` と `pages/a/b.vue`)、フォルダの中の page は、親の page が描く `<NuxtPage>` の中に描かれる。このプロファイルでは、**親も子も、それぞれ 1 件の入口**にする (どちらも抽出器が拾う)。

- 親の page は、子の数だけ繰り返さずに、1 回だけ分析する (`ui-nextjs` の layout と同じ考え方)
- どの子がどの親の中で動くかは、階層パスで分かる (子の階層パスは、親の階層パスで始まる)。入口の一覧の `within` は、このプロファイルでは付かない (包む側のファイル `a.vue` と、包まれる側のフォルダ `a/` が隣り合う形を、いまある決め方では表せないため)
- 親の page が、どの URL で単独で開けるかは、子に `index.vue` があるかで変わる。`summary` に書く
- 画面の移動 (`navigateTo('/')`、`<NuxtLink to>`) を `links` に書くとき、行き先の URL が、入れ子の親の page と、その子の葉の page の両方に当たる (例: `/` が `/index` と `/index/index` に当たる) ときは、`entry_id` を**実際に描かれる葉の page** にする。親は、葉を描くときに一緒に動く。当たる page が scope に無いとき (別のパッケージや有償版の page) は、`entry_id` を書かない

### layout

- layout ファイル 1 つ = 入口 1 件。抽出器 `nuxt-layouts` が拾う。階層パスは `/(layout)/<置き場>` (例: `layouts/shared-view.vue` → `/(layout)/shared-view`、id `layout_l.shared-view`)
- どの page がどの layout を使うかは、page の `definePageMeta({ layout })` か、`<NuxtLayout :name>` を描く側 (app.vue、別の layout) が決める。置き場からは決まらないので、一覧の `within` は付かない。layout の入口の `summary` に、どの page で使われるか (`definePageMeta` で選んでいる page、選ばない page に効く既定の `default`) を書く
- データの読み書きにも外部への送信にも至らない layout (見た目だけ) も、抽出器は拾う。分析で「データに届かない」と書いて閉じる (承認のときに、人が `rejected` にしてもよい)

### アプリ全体の枠 (`shell`)

どの画面を開いても動く処理は、画面ごとに書かず、枠を入口として 1 回だけ分析する。

| 枠にするもの | 見つけ方 | 階層パスと id | 拾い方 |
|---|---|---|---|
| アプリの根 | `app.vue` | `/(shell)/app`、`shell_s.app` | 抽出器 `nuxt-app-shell` |
| エラーの画面 | `error.vue` (エラーのとき、アプリ全体を置き換える) | `/(shell)/error`、`shell_s.error` | 抽出器 `nuxt-app-shell` |
| global の route middleware | `middleware/*.global.ts` (画面を移るたびに、ファイル名の順に動く) | `/(shell)/middleware/<ファイル名>`、`shell_s.middleware.<ファイル名の . を - にしたもの>` | 抽出器 `nuxt-global-middleware` |
| サーバー側の middleware | `server/middleware/*` (サーバーへのどの要求の前にも動く) | `/(shell)/server-middleware/<ファイル名>`、`shell_s.server-middleware.<ファイル名の . を - にしたもの>` | 抽出器 `nuxt-server-middleware` |
| プラグイン | `plugins/` の直下のファイルと、フォルダの中の `index` (アプリの起動のときに 1 回動く) のうち、データを読む・外へ送るもの | `/(shell)/plugin/<ファイル名>`、`shell_s.plugin.<ファイル名の . を - にしたもの>` | エージェントが `listed` で足す |
| 枠が描く共通の部品 | app.vue や layout が描くコンポーネントのうち、データを読む・外へ送るもの (枠を 1 件にまとめると大きくなりすぎるとき) | `/(shell)/part/<名前>`、`shell_s.part.<名前>` | エージェントが `listed` で足す |

- **global の middleware は、ファイル 1 つ = 入口 1 件** (`ui-vue-router` では共通の guard を 1 件にまとめるが、Nuxt ではファイルの置き場から決定論で取れ、1 つずつが大きいことがあるため)。どの順に動くかは、各入口の `summary` に書く
- **名前付きの route middleware** (`.global` の無いファイル。page の `definePageMeta({ middleware: [...] })` で指す) は、入口にしない。指している page の経路に、`kind: middleware` のフレームとして書く (`ui-vue-router` の route ごとの guard と同じ)。page の `definePageMeta` に、その場で書いた関数も同じ
- **page の `definePageMeta` の自前の印** (`public: true`、`requiresAuth: false` など、global の middleware が読んで動きを変える値): page の結果の権限の確認 (`guards`) には書かない (確かめるのは middleware の入口)。page の入口の `summary` に、印と値を 1 文で書く。middleware の入口では、印ごとの動きを `rules` に書く
- **middleware の中の画面の移動**: route middleware の中で、同じアプリの中への `navigateTo(...)` は、ブラウザ側では移動せずに行き先を返すだけで、middleware がそれを戻り値として返したときに移動になる。引数なしの `abortNavigation()` も `false` を返すだけで、返したときに中止になる (引数にエラーを渡したときは、投げるので、返さなくても止まる)。外部の URL への `navigateTo(..., { external: true })` は、返さなくても移る。戻り値を捨てている呼び出し (返していない、別の関数の中で呼んで結果を返さない) は、`links` に書いたうえで、`note` に「戻り値を返していないので、移動しない」と書き、`interpretation` にする (Nuxt のソースは scope に無いため)
- **global の middleware が中で呼ぶ、同じファイルの補助の関数**は、ほかの層と同じく、フレームにしない (入口のフレームの中の処理として書く)。補助の関数が呼ぶ API は、入口のフレームのすぐ下に置く
- **プラグイン**: 入口にするのは、起動のときにデータを読む・外へ送るもの (設定やユーザーの読み込み、計測やエラーの送信の初期化、通知を受け続ける接続)。入口にしないのは、ライブラリを登録するだけのもの、値や関数を `provide` するだけのもの (例: `$api` を作って `provide` するプラグイン。呼ぶ側から辿ったとき、`api_client` のフレームになる)。確かめたことを、`listed` の `rationale` に書く。名前の `.client` / `.server` は、動く場所の印なので、`summary` に書く
- 入口の層が 2 つ以上あるので、`listed` を層ごとに分ける (`agent-listed-shell`、`agent-listed-part`)
- 枠が描く共通の部品を分けるときの決まりは、`ui-vue-router` の「アプリ全体の枠」と同じ (部品の `source` はファイルの 1 行目、`reason` にどの枠がどの行で描くか、同じ部品を 2 つ以上の枠が描いても 1 件)

### サーバー側 (`server/`)

- `server/api/**` と `server/routes/**` の受け口は、入口にしない。画面から辿った途中のフレーム (`api_route`) として現れる (`ui-nextjs` の `route` ファイルと同じ)。画面を通らない受け口 (外部向けの API、Webhook の受信) は、このプロファイルの既定では分析の対象にならない。それも見たいときは、`api` プロファイルで分析リポジトリを分ける
- `server/middleware/*` (サーバーへのどの要求の前にも、ファイル名の順に動く。page をサーバー側で描く要求も含む) は、ファイル 1 つ = `shell` の入口 1 件。抽出器 `nuxt-server-middleware` が拾う (`/(shell)/server-middleware/<ファイル名>`)。global の route middleware と同じく、どの要求でも動く処理を、受け口の数だけ繰り返さないため (`ui-sveltekit` の hooks.server と同じ考え方)。受け口 (`api_route`) を分析するときは、server middleware を辿らない。権限の確認を server middleware がしているときは、受け口のフレームの `summary` に「権限の確認は server middleware `<名前>` が行う」と書く
- `server/plugins/**` (サーバーの起動のときに動く) は、データを読む・外へ送るものだけ、`shell` の入口として `listed` で足す (`/(shell)/server-plugin/<ファイル名>`)

## 入口ごとの分析で見るもの

| 層 | 読む場所 | 拾うこと |
|---|---|---|
| page | page ファイル | 描画するコンポーネント、呼ぶ composable と store、URL のパラメータ (`route.params`)、`definePageMeta` の `middleware` (名前付きとその場で書いたもの)、データの読み込み (`useFetch`、`useAsyncData`、`$fetch`) |
| layout | layout ファイル | 描画するコンポーネントと、呼ぶ composable と store。`<slot />` の中身と、`<NuxtLayout>` で入れ子にした別の layout は読まない |
| shell | app.vue、error.vue、middleware、プラグインのファイル | そのファイル自身が呼ぶ composable と store と API。`<NuxtLayout>` と `<NuxtPage>` の中身と、別の入口にした共通の部品は読まない |
| component | コンポーネントと composable のファイル | 子のコンポーネント、呼ぶ composable と store の関数、書き込み (作成・更新・削除) を起こす操作 |
| store | store のファイル | action が呼ぶ API の関数、別の store の呼び出し |
| api_client | HTTP を包む自前の関数、プラグインが provide した API の client | URL の形、HTTP メソッド、共通の接頭辞 |
| api_route | `server/api/**`、`server/routes/**` の handler | 入力の解釈、認証・権限の検査、呼ぶサーバー側の関数。server middleware は読まない (別の入口) |
| query | `server/utils/**` などのサーバー側の関数 | テーブルと操作、キャッシュのキー、ストレージの置き場、外部 API の host / path |

### 自動で読み込まれるものの辿り方 (このプロファイルの要)

Nuxt は、コンポーネント、composable、utils、(設定によっては) store を、import 文なしで使える。import を辿るだけでは、呼び先の定義に着かない。

1. 名前から定義を探す場所を、最初に 1 度確かめる
   - コンポーネント: `components/` (`nuxt.config` の `components.dirs` で足した場所も)。名前は、フォルダの名前を前に付けた PascalCase (例: `components/nc/Button.vue` → `<NcButton>`。`pathPrefix: false` の設定では、ファイル名だけ)。頭の `Lazy` は、後から読み込む印なので外して探す
   - composable と utils: `composables/` と `utils/` の直下 (`nuxt.config` の `imports.dirs` で足した場所も。`store/**` のように store を足していることもある)
   - サーバー側: `server/utils/` (サーバー側だけで自動で読み込まれる)
   - 生成された型の定義 (`components.d.ts`、`.nuxt/components.d.ts`、`.nuxt/imports.d.ts`) がリポジトリにあれば、名前 → ファイルの対応表として読む
2. 呼び出しの名前で、定義を探す (`rg "export (const|function|async function) useXxx"`、コンポーネントはファイル名で探す)
3. `call` の根拠には、呼んでいる行を書く。定義の行は、呼び先のフレームの `source` に書く
4. 状態の付け方: 名前の規則で、定義が 1 つに決まる → `fact`。同じ名前の定義が scope に 2 つ以上あり、どれが使われるかを設定から決められない → 候補をそれぞれフレームにして `interpretation`。見つからない → `unknown` + `out_of_scope` (依存のパッケージやモジュールが入れるもの)
   - `nuxt.config` の `extends` で、scope の外の layer (有償版、別のパッケージ) を重ねる作りでは、同じ名前の composable やコンポーネントが、その layer で上書きされうる。上書きの中身は読めないので、scope の中の定義を辿り、`unknown` にしない。入口の `notes` に「`extends` の layer で上書きされうる」と 1 文だけ書く
5. `useNuxtApp().$xxx` や、自動で注入された `$xxx` は、プラグインの `provide` を探す (`rg "provide:\s*\{|nuxtApp.provide\("`)。プラグインそのものは辿らず、provide した値の定義 (client を作る関数や、その中のメソッド) をフレームにする

### フレームにするもの・しないもの

- **フレームにする**: データの読み書きか、API の呼び出しに至る経路の上にある、コンポーネント、composable、store、API を包む関数、route middleware、サーバー側の受け口と関数
- **フレームにしない**: 見た目だけの部品 (ボタン、表の枠、アイコン、UI ライブラリの部品)、翻訳・日付・書式の小道具、型定義。経路の上に無いものは、`summary` で触れるだけでよい
- **同じファイルの中の、外に出していない補助の関数**は、フレームにしない。呼び出し元のフレームの中の処理として扱う
- **store は、呼ばれる関数ごとに分ける**。画面が呼ぶ action だけをフレームにし、`name` に `<store の名前>.<action>` と書く
- **画面と、画面を包むもの**: 画面を開くと、app.vue、layout、global の middleware、入れ子の親の page も動く。これは画面ごとに書かず、それぞれを 1 件の入口として 1 回だけ分析する
  - **page を分析するとき**: layout、app.vue、global の middleware、プラグイン、入れ子の親の page (階層パスの祖先にあり、`nested` が true の page) は**辿らない**。フレームにも I/O にも書かない。どの親の中で、どの layout で描かれるかは、入口の `summary` に 1 文で書く。`definePageMeta` で指した名前付きの middleware は、**この page の経路として辿る** (この page のときだけ動くため)
  - **入れ子の親の page を分析するとき**: `<NuxtPage>` の中身 (子の page) は**辿らない**。親自身が描く部品 (タブ、横のメニュー、親の対象の読み込み) を辿る。子の一覧 (階層パス) を、入口の `summary` に書く
  - **layout と shell を分析するとき**: `<slot />`、`<NuxtLayout>`、`<NuxtPage>` の中身は**辿らない**。別の layout を `<NuxtLayout name="...">` で入れ子にしているときも、その layout は辿らない (別の入口)。`summary` に、どの layout を入れ子にしているかを書く
  - 包む側が描く部品と同じ部品を、画面も自分で描いているときは、画面の側にも書く。省くのは「包む側を経由してだけ動くもの」
- **`external` フレームの場所 (`source`)**: **ライブラリや SDK の関数を実際に呼んでいる行**を書く。クライアントを作る・設定するだけの共通のファイルの行や、import の行を `source` にしない
- **SDK のソースが、範囲 (scope) の中にあるとき**: それでも、生成された SDK の関数は `external` フレームで閉じる (`source` は呼んでいる行)。URL は、SDK のソースを読んで書く (下の「データの当てはめ」)
- **関数を渡して、別の部品が呼ぶとき** (props、`provide` / `inject`、設定に入れた関数): 渡された関数をフレームにし、`caller` は渡している側のフレーム。`call` は `interpretation` にし、根拠に、渡している行と、呼んでいる行 (読めれば) の両方を書く
- **値の変化を見張って動く処理** (`watch`、`watchEffect`): API に至るならフレームにする。`caller` は、見張っている値を変える側のフレーム。`call` は `interpretation` にし、根拠に、見張りを書いた行を書く
- **条件付きで通る枝** (ダイアログを開いたとき、特定の URL のパラメータが付いたとき): 辿る。条件を、枝の最初のフレームの `summary` に書く
- **1 件が大きくなったとき** (目安: フレームが 60 を超える): 止めずに書き切る。入口の `notes` と報告に、フレームの数と、分ける候補 (ダイアログの先の枝、枠が描く共通の部品) を書く。分けるかは、人が決める
- **終端の決まり**: 機械チェックは、終端のフレーム (誰からも呼ばれないフレーム) が「`external` の層」「I/O を持つ」「業務のルールを持つ」「行き先の入口が分かっているつながり (`links` の `embed` / `trigger` と `entry_id`) を持つ」「権限の確認を持つ」「`unknown` の主張を持つ」のどれかであることを求める。どれにも当たらない経路は、データの I/O か `external` のライブラリまで書き切る (確認だけをする段や、業務のルールだけの段の先に、無い呼び出しを足さない)
- **データに届かない画面・枠** (別の画面へ転送するだけ、固定の文言を出すだけ、見た目だけ): 入口のフレームから、それが最後に頼るライブラリ (転送なら `navigateTo` / `vue-router`) を `external` フレームとして 1 つ書いて閉じる。I/O は無し。「データを読まない」ことは、入口の `summary` に書く

### 登録表から選ばれて描かれる部品 (`part`)

`ui-vue-router` の「登録表から選ばれて描かれる部品」と同じ決まりで、部品を、部品ごとに別の入口 (`part`) に分けられる。

- 登録表 (種類の名前 → コンポーネントの対応表) のうち、**保存された値** (サーバーに保存した構成、保存の前に利用者が選んでいる最中の値) で引くもの。URL の段や、画面の中の切り替え (タブ) で引く対応表は、登録表に当たらない
- 候補のうち、データを読む・外へ送る部品が **3 つ以上**あれば分ける。登録表の項目 1 つ = 入口 1 件。`agent-listed-part` (`layer: part`) で足す。階層パスは `/(part)/<登録表の名前>/<選ぶときの名前>`、id は `part_p.<登録表の名前>.<選ぶときの名前>`
- 画面は、登録表を引くフレームで止め、`links` に `kind: embed`、`entry_id` で部品の入口を書く。部品の入口は、描く側を辿らない
- 枠が描く共通の部品 (`/(shell)/part/<名前>`) は、この節の部品ではない (いつも描かれる)

### 同じ処理が何度も呼ばれるとき

`ui-nextjs` と同じ。1 つの入口の中で、同じ処理 (定義の行が同じ関数・コンポーネント・composable・store の action・受け口の handler。`external` フレームなら、ライブラリを呼んでいる同じ行) が、複数の呼び出し元から呼ばれるときは、入口から、コードに書いてある順に深さ優先で辿って、最初にその処理に着いた呼び出し元の下に、1 回だけ書く。ほかの呼び出し元の `summary` に「<処理の名前> も呼ぶ。経路はフレーム `<id>` と同じ」と書く。そうすると呼び出し元が終端になって終端の決まりを満たせないときだけ、もう一度書く (終端の決まりを満たす最初のフレームまで)。

### 画面からサーバー側の受け口への橋渡し

サーバー側を同じリポジトリに持つときだけ。`useFetch('/api/...')`、`$fetch('/api/...')`、`useAsyncData(() => $fetch(...))` は、関数の呼び出しではなく URL でつながる。

1. 呼び出しから、URL の形と HTTP メソッドを読む (`method` の指定が無ければ `GET`)
2. `server/api/` の下は URL の `/api/...`、`server/routes/` の下は接頭辞なしの URL に当たる。ファイル名の `[id]` が、URL の値の部分に当たる。ファイル名の後ろの `.get` / `.post` などは、HTTP メソッドの印 (例: `server/api/books/[id].get.ts` は `GET /api/books/:id`)。印の無いファイルは、どのメソッドでも受ける
3. 当たる受け口の handler (`defineEventHandler` の関数) を `api_route` フレームにし、`caller` で呼び出し側を指す。`call` の根拠は、**呼び出し側の URL の行**。受け口の handler の行は、フレームの `source` に書く
4. 同じファイルに、メソッドの印が別のファイルとして並ぶとき (`[id].get.ts` と `[id].put.ts`) は、別のフレーム

状態の付け方は、`ui-nextjs` の「component から api_route への橋渡し」と同じ (URL がそのまま読めて受け口が 1 つ → `fact`、候補が有限 → それぞれ `interpretation`、決められない → `unknown` + `dynamic_dispatch`、受け口が scope に無い → フレームにせず `external_api`)。

### 多くの入口が描く、大きな部品

- 多くの入口が自分で描く、大きな部品 (3 件以上の入口が描き、下に 10 以上の段を持つコンポーネント) も、別の入口 (`part`。階層パスは `/(part)/_shared/<コンポーネントの名前>`、id は `part_p.shared_a.<名前>`) に分けられる。候補は、数件を分析した後に、集計表「別の入口に分ける候補」から選ぶ。決まりは、`ui-nextjs` の `context.md` の「多くの入口が描く、大きな部品 (共有の部品)」と同じ

## 事実・解釈・不明の付け方

- **fact**: コードにそのまま書いてある (import と呼び出し、自動で読み込まれる名前の呼び出しで、定義が 1 つに決まるもの、URL の文字列、SDK の関数の名前、ORM のメソッドとモデル)。根拠はその行
- **interpretation**: 読み取って要約したもの (フレームの summary、何のための処理か)。根拠は読んだ範囲の代表行
- **unknown**: 次の典型例ではこの理由を使う
  - 描くコンポーネントや、呼ぶ API が、実行時の値で決まる (`<component :is>`、名前で引く処理) → `dynamic_dispatch`
  - サーバーの応答や設定から、画面の作りや問い合わせの中身を組み立てる → `generated_at_runtime`
  - 送り先のホストや URL が、別の API の応答や、実行環境の設定で決まり、値がリポジトリに無い → `not_traceable_in_repo`
  - 呼び先が scope の外、または別のパッケージ (Nuxt のモジュールが入れる composable を含む) → `out_of_scope`
  - 配布物だけでソースが無い → `binary_or_vendored`

## データの当てはめ

### 別のバックエンドの API を呼ぶとき (サーバー側を持たない作り)

`ui-vue-router` の「データの当てはめ」と同じ。

- **I/O を書くフレーム**: HTTP のライブラリや SDK を呼んでいる行の、`external` フレームに書く。共通の関数を、呼び出し元ごとに違う URL で呼ぶときは、**URL ごとに `external` フレームを分ける** (`name` に URL を書く)
- バックエンドの API の呼び出し → `external_api` (`op: call`)。段は `host` と `path`
  - `host`: 画面と同じ配信元のバックエンドなら、`(backend)` と書く。接続先が環境変数 (`runtimeConfig` を含む) で決まることだけを理由に、`unknown` にしない。他社のサービスなら、そのホスト名
  - `path`: `<HTTP メソッド> <URL の形>` (例: `GET /api/v1/books/{id}`)。組み立て式の変数の部分は、`{名前}` にする。共通の接頭辞 (`baseURL` など) は、付ける場所を 1 度読んで、付けた形で書く
  - `note` に、何を読む・書くかを 1 文で書く
- **生成された SDK の関数を呼ぶとき**: SDK のソースが範囲の中にあれば、そこから URL を読んで、上の形で書く (`fact`。根拠に、呼んでいる行と、SDK の中で URL を書いた行の両方)
- **SDK のソースが範囲に無く、URL がリポジトリに無いとき**: `path` に `sdk:<モジュール>.<関数>` と書く (例: `sdk:auth.signin`)。SDK の関数を呼んでいることはコードにあるので、`fact`。URL を推測で書かない
- サーバーからの通知を受け続ける接続 (Server-Sent Events、WebSocket) → `external_api` (`op: call`)。`note` に「受け続ける」と書く
- 計測や分析、エラーの送信のための、他社のサービスへの送信 → `external_api`。ホスト名がコードにあれば書く

### サーバー側を持つとき

`ui-nextjs` の「データの当てはめ」と「接続先 (host / database) の扱い」と同じ。

- ORM のモデル → `rdb` (段は `dbms` と `table`)。メソッドの読み書きの区分も `ui-nextjs` と同じ
- Nitro のストレージ (`useStorage()`) → 設定した置き場の種類で決める (Redis なら `kvs`、ファイルなら `filesystem`)。置き場の種類が設定から読めなければ、`kvs` にし、`note` に「置き場の種類は設定で決まる」と書く
- 接続先の段 (`host`、`database`) は、環境変数で決まるなら書かない。テーブルやキーがコードから読めれば `fact`

### どちらにも当てはまること

- ブラウザの中の保存 (localStorage、sessionStorage、cookie の読み書き。`useCookie`、`useState` を含む) は、サーバーのデータではないので、**I/O に書かない**。画面の動きに効くなら、そのフレームの `summary` に書く
