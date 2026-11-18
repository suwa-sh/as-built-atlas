# ui-sveltekit プロファイル: エージェント向けの説明

対象は「SvelteKit で作った、画面を持つシステム」。画面と API とデータの読み書きが同じリポジトリにあるもの。ファイルの置き場 (`src/routes`) がルーティングになる型で、決まりの多くは `ui-nextjs` と同じ。入口の発見と入口ごとの分析で、このファイルと `profile.yaml` の両方を読む。

## アーキテクチャと層の連鎖

```text
shell (src/hooks.server.ts の handle。どの要求・どの画面でも、前に動く)
layout (+layout.svelte。画面を包む共通の枠)
page (+page.svelte。URL 1 つ = 画面 1 つ)
  → component (Svelte のコンポーネント、API を呼ぶ store と関数、+page.ts / +layout.ts の load)
    ⇢ api_route (ブラウザ側からサーバー側へ入る口。3 種類ある)
        ・+server.ts の GET / POST … (HTTP をはさむので、関数の呼び出しではなく URL でつながる)
        ・+page.server.ts / +layout.server.ts の load と、form の actions (画面を移るたびに、SvelteKit が HTTP 越しに呼ぶ)
        ・remote functions (`.remote.ts` の query / command / form)。import して呼ぶので、定義へそのまま辿れる
      → query (サーバー側の関数: 問い合わせ、認証・権限の検査、$lib/server の共通の関数)
        → external (DB クライアント・ORM・キャッシュ・メッセージ基盤。ここで終端)
```

- `page`、`layout`、`shell`、`part` が `role: entry`。`+page.svelte` 1 つ = 入口 1 件、`+layout.svelte` 1 つ = 入口 1 件、`hooks.server` 1 つ = 入口 1 件
- 層の名前は `ui-nextjs` と同じ。`ui-nextjs` に無いのは `shell` だけ (どの要求・どの画面でも動く処理の入口。`ui-vue-router`、`ui-nuxt` の `shell` と同じ名前)
- `layout` と `shell` は、連鎖の先頭が替わるだけで、その先は同じ (`layout → component ⇢ api_route → query → external`、`shell → query → external`)。画面と枠とフックは**別々に分析する** (下の「画面と、画面を包む枠とフック」)
- `external` が `role: boundary`。ライブラリ・SDK の呼び出しに達したらコールスタックを閉じる
- `+page.server.ts` の load や actions、`+server.ts` が、`$lib/server` の関数を通さずに DB を直接読み書きすることがある。そのときは `api_route` のフレームの `io` に書き、呼び出しが届くライブラリを `external` フレームにして閉じる

### load と actions を、どの層に書くか

| ファイル | 層 | 理由 |
|---|---|---|
| `+page.ts` / `+layout.ts` の `load` (universal load。サーバーでもブラウザでも動く) | `component` | 自分ではデータに触らず、`fetch` や API クライアントで API を呼ぶ。Next.js の、API を呼ぶフックと同じ役割 |
| `+page.server.ts` / `+layout.server.ts` の `load` | `api_route` | サーバーだけで動き、ブラウザ側で画面を移るときは、SvelteKit が HTTP 越しに呼ぶ (`__data.json`)。ブラウザ側からサーバー側へ入る口 |
| `+page.server.ts` の `actions` | `api_route` | form の送信を受ける口。Next.js の Server Function と同じ扱い。action ごとにフレームを分ける (`name` は `actions.save`、名前の無い action は `actions.default`) |
| `.remote.ts` の `query` / `command` / `form` / `prerender` | `api_route` | ブラウザから呼ぶと HTTP 越しになる、サーバーだけで動く関数。呼ばれる関数ごとにフレームを分ける |
| `+page.ts` / `+layout.ts` の `ssr`、`csr`、`prerender` などの設定の export | フレームにしない | 動きを変える設定なので、入口のフレームの `summary` に書く |

- 画面の入口は `+page.svelte` 1 つ。同じフォルダの `+page.ts` と `+page.server.ts` は、**その画面の入口の中で**分析する (抽出器は、隣のファイルの有無を出さない。入口を分析するときに、同じフォルダを見て確かめる)
- 入口のフレーム (`+page.svelte`) から、load のフレームを子として書く。`call` の evidence は、`+page.svelte` が load の結果を受け取る行 (`let { data } = $props()`、`export let data`) と、load の定義の行。`when` は `always`。`+page.svelte` が `data` を受け取らないときも、load は画面を開くたびに動くので書く (evidence は load の定義の行)
- `+page.server.ts` と `+page.ts` の両方があるときは、どちらも入口のフレームの子にする (サーバーの load が先に動き、その結果が `+page.ts` の load の `data` 引数に渡る。`+page.ts` から `+page.server.ts` を呼ぶのではない)。順は、サーバーの load、universal load の順
- 枠の load (`+layout.ts`、`+layout.server.ts`) も同じで、枠の入口のフレーム (`+layout.svelte`) の子にする

## 入口の判別 (抽出器のパラメータの決め方)

- routes の場所を確かめる (既定は `src/routes`。`svelte.config` の `kit.files.routes` で変えられる)。`files` と `segments.strip_prefix` を同じ場所にする。`hooks.server` の場所も同じく確かめる (`kit.files.hooks.server`)
- 階層パスは URL の形。`(group)` は URL に出ないので落とす。`[id]` (動的な段)、`[[lang]]` (省ける段)、`[...rest]` (残りすべての段)、`[id=integer]` (値の形を決める matcher 付きの段) は、そのまま残す
- 入口の id は階層パスから記号を除いたもの。段の種類は「`_` + 1 文字」の印で表す (印の意味は `ui-nextjs` と同じ): `[id]` → `id_d`、`[...rest]` → `rest_c`、`[[lang]]` → `lang_o`、src/routes 直下の page → `root_r`。名前の中の `_` は 2 つ重ねる
  - matcher (`=integer`) は id から外す (`[id=integer]` → `id_d`)。階層パスには残る。同じ置き場に `[id=integer]` と `[id]` が並ぶと (SvelteKit では許される。matcher 付きが先に当たる)、同じ id になって列挙が失敗する。黙って片方を捨てず、`id.replace` にそのリポジトリ向けの置換を足して区別する (例: `^\\[id=integer\\]$` → `id-integer_d` を、既定の置換より前に置く)
  - 記号を表す書き方 (`[x+3a]`、`[u+00e9]`) は値の入る段ではない。id では `x3a`、`u00e9` にする
  - 1 つの段に、固定の文字と値が混ざる書き方 (`photos-[id]`、`[a]-[b]`) も、値の入る部分に印を付ける (`photos-id_d`、`a_d-b_d`。`ui-nuxt` と同じ)
- Next.js と違い、`_` で始まるフォルダも route になる。`exclude` を書かない。id では名前の `_` を重ねる (`/blog/_drafts` → `blog.__drafts`)。ただし、id は英数字で始まる決まりなので、routes 直下の `_` で始まるフォルダ (`/_drafts`) は、列挙が「契約違反」で止まる。そのリポジトリ向けに、id の置換を、`_` を重ねる置換のすぐ後に足す (例: `^_(.*)$` → `u_\\1`。`_drafts` → `__drafts` → `u___drafts`。名前の `_` は偶数個ずつなので、`_` が奇数個並ぶ名前は静的な段と重ならない)。routes の中の `+` で始まらないファイル (部品、テスト、`*.spec.ts`) は、SvelteKit が無視するので、入口にならない (抽出器も拾わない)
- `+layout.svelte` は、抽出器 `sveltekit-layouts` が画面とは別の入口として拾う。階層パスは `/(layout)` で始まり、後ろに枠の置き場のフォルダが続く (例: `src/routes/settings/(nav)/+layout.svelte` → `/(layout)/settings/(nav)`、routes 直下 → `/(layout)`)。どの入れ物の枠かが名前になるので、`(group)` は落とさない。id は `layout_l` で始まり、入れ物は `_g` の印で表す (例: `layout_l.settings.nav_g`)
- **`+layout.svelte` が無く、`+layout.ts` / `+layout.server.ts` だけがあるフォルダ**: その load は、配下のすべての画面で動くが、抽出器は拾わない。load がデータの読み書きや外部への送信に至るなら、`abatlas-extract listed` で枠の入口として足す (名前は `agent-listed-layout`、`layer: layout`。階層パスと id は抽出器と同じ付け方。`source` は load の定義の行)。設定の export (`ssr = false` など) だけなら、入口にしない。確かめたことを抽出器の `rationale` に書く
- `hooks.server` は、抽出器 `sveltekit-hooks` が 1 件の入口 (層 `shell`) として拾う (階層 `/(shell)/hooks.server`、id `shell_s.hooks-server`。id の点は `-` にする)。`attributes` の `handle`、`handle_fetch`、`init` は、それぞれの hook を export しているか
- どの画面がどの枠とフックを通るかは、列挙ツールがソースのフォルダの親子から決めて、入口の一覧の `within` (包む入口の id、外側から) に書く。エージェントは決めない・書き換えない。`hooks.server` は src にあるので、すべての入口を包む (`within` は `[shell_s.hooks-server, layout_l, …]` になる)
- **枠を抜ける page / layout** (`+page@.svelte`、`+page@(app).svelte`、`+layout@.svelte`): `@` の後ろの名前の枠まで戻り、それより内側の枠を通らない。列挙ツールの決め方 (`source_dir`) はこれを知らず、祖先の枠をすべて `within` に付ける。`within` は手で直さない。入口の `summary` に「`@` の後ろの枠より内側の枠 (id を並べる) は通らない」と書く
- `+error.svelte`、`hooks.ts` (universal hooks: `reroute`、`transport`)、`hooks.client.ts`、`src/params` の matcher は、既定の抽出器では拾わない。`hooks.client.ts` と `hooks.ts` がデータの読み書きや外部への送信に至るときは、抽出器 `sveltekit-hooks` の `files` に足す (層 `shell`。階層 `/(shell)/hooks.client`、`/(shell)/hooks`、id `shell_s.hooks-client`、`shell_s.hooks`)。**入口を発見するときに、これらのファイルの有無と中身を確かめる** (数は少ない)
  - データの読み書きにも外部への送信にも至らない (エラーの文言を出すだけ、値の写し替え、URL の書き換え) → 入口にしない。確かめたことを抽出器の `rationale` に書く
  - データの読み書きや外部への送信に至る → そのリポジトリの入口の一覧に、そのファイルを拾う抽出器を**必ず足す** (`abatlas-extract glob` か `listed`、`segments.prefix` で階層を分ける。例: `(error)`、`(hooks-client)`)
- 保存された設定で、描く部品が決まる画面 (名前から部品を引く登録表を持つ作り) があるときは、部品を別の入口に分けるかを決める。決まりは `ui-nextjs` の `context.md` の「登録表から選ばれて描かれる部品」と同じ (`part`、`/(part)/<登録表の名前>/<選ぶときの名前>`、`part_p.…`)
- `+server.ts` (API の受け口) は入口にしない。画面から辿った途中のフレームとして現れる。画面を通らない受け口 (外部向け API、ログインの戻り先、webhook、計測の受信、死活の確認) は、このプロファイルの既定では分析の対象にならない。それも見たいときは、`api` のプロファイルで、分析リポジトリを分ける。入口を発見したときの報告に、画面から届かない `+server.ts` の数と、主なもの (URL の第 1 段ごと) を書く

## 入口ごとの分析で見るもの

| 層 | 読む場所 | 拾うこと |
|---|---|---|
| page | `+page.svelte` と、同じフォルダの `+page.ts` / `+page.server.ts` | 描画するコンポーネント、load と actions、URL のパラメータ (`params`)。祖先の `+layout` と `hooks.server` は読まない (別の入口) |
| layout | `+layout.svelte` と、同じフォルダの `+layout.ts` / `+layout.server.ts` | 枠が描画するコンポーネント、枠の load。`children` (`{@render children()}`、`<slot />`) の中身は読まない |
| shell | `hooks.server` と、そこから呼ぶ関数 | `handle` (ログインの確認、セッションの読み書き、要求の検査と書き換え)、`handleFetch`、`handleError`、`init`。`resolve(event)` の先は読まない |
| component | コンポーネント、store、関数、universal load のファイル | 子のコンポーネント、呼ぶ store と関数、呼ぶ API の URL と HTTP メソッド、form の送り先、書き込み (作成・更新・削除) を起こす操作 |
| api_route | URL に当たる `+server.ts` の、HTTP メソッドの名前の関数 (無ければ `fallback`)。`+page.server.ts` / `+layout.server.ts` の `load` と `actions` の関数。remote functions の定義 | 入力の解釈、認証・権限の検査 (`locals.user` の確認など)、呼ぶサーバー側の関数、直接の読み書き |
| query | サーバー側だけで動く関数のファイル (`$lib/server` の下に限らない。サーバー側の受け口やフックからだけ import される `$lib` の関数も query) | コレクション・テーブルと操作、キャッシュのキー、メッセージの送り先、外部 API の host / path |

### フレームにするもの・しないもの

フレームが際限なく増えないように、次の基準で選ぶ。

- **フレームにする**: データを読む・書く処理に至る経路の上にあるコンポーネント、store、関数。API を呼ぶ store や関数は 1 つずつフレームにする
- **フレームにしない**: 見た目だけの部品 (ボタン、表の枠、アイコン、UI ライブラリの部品)、翻訳・日付・書式の小道具、型定義。経路の上に無いものは `summary` で触れるだけでよい
- **store と、SvelteKit の状態**:
  - `$lib/stores` などの自前の store (`writable`、`.svelte.ts` の `$state` を持つクラスや関数) のうち、API を呼ぶもの (`fetch` や API クライアントを中で呼ぶ) は `component` のフレームにする (Next.js の、API を呼ぶフックと同じ)。状態を持つだけの store は、フレームにしない。画面の動きに効くなら、使うフレームの `summary` に書く
  - `$app/state` (`page`、`navigating`、`updated`) と `$app/stores` (前の書き方の `page` など) は、SvelteKit が持つ状態で、フレームにしない。`page.data` は load の結果 (画面と、包む枠の load が合わさったもの) なので、そこから読む値の出どころは辿らない。`page.params`、`page.url` から読む値は、フレームの `parameters` に書く
  - `$app/navigation` の `goto(...)` は画面の遷移なので、`links` の `navigate` に書く。`invalidate(...)` / `invalidateAll()` は、load をもう一度動かす (読み直す) ことを、そのフレームの `summary` に書く (load のフレームを、もう一度書かない)
- **画面と、画面を包む枠とフック (`layout` / `shell`)**: 画面を開くと、祖先のフォルダの `+layout.svelte` (と、その load) と、`hooks.server` の `handle` も動く。これは画面ごとに書かず、**枠とフックを、それぞれ 1 件の入口として 1 回だけ分析する**。どの画面がどの枠とフックを通るかは、入口の一覧の `within` が持つ
  - **画面 (`page`) を分析するとき**: 祖先の layout と、その load と、そこから描かれる部品は**辿らない**。`hooks.server` も辿らない。load の中の `await parent()` は、枠の load の結果を受け取るだけなので、フレームにしない。`parent()` から読む値 (例: `parentData.user`) で処理が分かれるときは、その値を `parameters` に書き、分かれ道を `call.condition` や `rules` に書く
  - **枠 (`layout`) を分析するとき**: 入口のフレームは `+layout.svelte` (`layer: layout`)。枠が描画するコンポーネントと、枠の load を、画面と同じ基準で終端まで辿る。`children` の**中身は辿らない**。外側・内側の別の layout も辿らない
  - **フック (`shell`) を分析するとき**: 入口のフレームは `hooks.server` のファイル (`layer: shell`、`source` は `handle` の定義の行)。export されている hook を、それぞれ入口のフレームの子にする。子は、ファイルに書いてある順 (行の順) に辿る (下の並びの順ではない。「同じ処理が何度も呼ばれるとき」の置き場が、行の順で決まるため)
    - export が、ほかのファイルの関数に中身を任せるだけ (`export const handle = (input) => handleRequest(input)`) のときは、export をフレームにせず、任せる先の関数を入口のフレームの直接の子にする (`layer: query`、`call` の evidence は export の行)
    - `$app/environment` の `building` (ビルドと prerender の間だけ true) で先に返す経路は、要求を受けて動くときはいつも成り立たないので、無いものとして扱う (後ろの呼び出しを `always` にし、`note` に「building はビルドの間だけ true」と書く)
    - `handle`: `when` は `always` (すべての要求で動く)。`sequence(...)` で並べた hook は、並びの順に子にする
    - `handleFetch`: サーバー側の `fetch` (load の中の `fetch` など) のたびに動く。`when` は `conditional` (「サーバー側で fetch を呼ぶとき」)
    - `handleError`: `when` は `on_failure` (「要求の処理で、予期しないエラーが起きたとき」)
    - `init`: サーバーの起動のときに 1 回だけ動く。`when` は `conditional` (「サーバーの起動のとき 1 回」)。要求ごとに動くものではないことを、入口の `summary` に書く
      - 起動のときに 1 回で終わる処理 (移行、集計、後片付け) は、読み書きまで辿る
      - 起動のときに始まり、その後も動き続ける処理 (`setInterval` の定期の処理、キューの見張り、bot の常駐) は、始める呼び出しのフレームまで書き、その先は辿らない。そのフレームに `unknown` + `not_analyzed` を書き、`note` に「起動で始まり、動き続ける処理。<関数の名前> から先は読んでいない」と書く。入口の発見の報告に、こうした処理の名前と場所を挙げる (このプロファイルには、動き続ける処理を入口にする層が無い。分析したいときは、人が、`cli` や `api` などの分析リポジトリを分けるかを決める)
    - `resolve(event)` の先 (画面、枠、`+server.ts`) は辿らない。`handle` が URL や要求によって動きを変えるとき (例: ある URL の下ではログインを確かめない) は、その条件を `rules` (`decision`) か `call.condition` に書く
    - ログインの確認やセッションの読み込みは、ここで 1 回だけ書く。画面や `+server.ts` の側で `locals.user` を読むだけのときは、確認ではない (確認を行っているのはフック)。`locals.user` が無ければ止める処理が受け口にあれば、その受け口の `guards` に `authentication` を書く
  - 枠やフックの中で条件付きで動くものも辿る。条件は、そのフレームの `summary` か I/O の `note` に書く
  - 枠やフックが呼ぶ処理と同じ処理を、画面も自分で呼んでいるときは、画面の側にも書く。省くのは「枠やフックを経由してだけ動くもの」
  - データの読み書きにも外部への送信にも至らない枠 (見た目の設定だけ) は、「データに届かない画面」と同じ書き方で閉じる
- **`external` フレームの場所 (`source`)**: ライブラリのソースはリポジトリに無いので、`source` には**ライブラリの関数・メソッドを実際に呼んでいる行**を書く (例: `collections.users.findOne(…)` の行、`client.get(key)` の行)。クライアントを作る・設定するだけの共通ファイルの行 (`new MongoClient(...)`、`db.collection("users")`) や、import の行を `source` にしない
- **`external` フレームの数**: 読み書きの相手とメソッドの組ごとに 1 つ (`sessions.findOne` と `users.findOne` は別のフレーム。別の SDK のメソッド `users.info` と `conversations.info` も別)。1 つの関数の中で、同じ相手の同じメソッドを何度も呼ぶときだけ、最初の行の 1 つにまとめる
- **画面の遷移のライブラリ** (`goto`、`redirect`): 遷移は `links` の `navigate` に書く (フレームにしない)。遷移の先が `+server.ts` (例: `/login`、ログインの戻り先) で、画面の入口ではないときも、`navigate` に URL の形を書き、`entry_id` は書かない。遷移しか持たない枠や画面を閉じるための `external` フレームは、最初の遷移の行に 1 つだけ書く (遷移の行ごとに増やさない)
- **終端の決まり**: 機械チェックは、終端のフレーム (誰からも呼ばれないフレーム) が「`external` の層」「I/O を持つ」「業務のルールを持つ」「行き先の入口が分かっているつながり (`links` の `embed` / `trigger` と `entry_id`) を持つ」「権限の確認を持つ」「`unknown` の主張を持つ」のどれかであることを求める。だから、経路は必ずデータの I/O か `external` のライブラリまで書き切る
- **データに届かない画面・枠** (別の画面へ転送するだけ、固定の文言を出すだけ): 入口のフレームから、それが最後に頼るライブラリ (転送なら `@sveltejs/kit` の `redirect` や `$app/navigation` の `goto`) を `external` フレームとして 1 つ書いて閉じる。I/O は無し。「データを読まない」ことは入口の `summary` に書く
- **同じファイルに複数の関数**: フレームはファイル単位を基本にする。`+server.ts` は HTTP メソッドごとにフレームを分ける (`name` に `GET /api/…` のように書く)。`+page.server.ts` は `load` と、action ごとに分ける。remote functions のファイルも、呼ばれる関数ごとに分ける
  - 正解との突き合わせ (`abatlas evaluate`) は、フレームを「層と `source.file`」で照合するので、同じファイルの別の関数は 1 つに数えられる。フレームを分けるのは、画面と図で呼び出しの関係を正しく見せるため

### 同じ処理が何度も呼ばれるとき

`ui-nextjs` の `context.md` の「同じ処理が何度も呼ばれるとき」と同じ。同じ関数とその先の経路は、入口から、コードに書いてある順に深さ優先で辿って、最初にその処理に着いた呼び出し元の下に 1 回だけ書く。他の呼び出し元は、`summary` で「<処理の名前> も呼ぶ。経路はフレーム `<id>` と同じ」と書く。そうすると呼び出し元が終端になって機械チェックに落ちるときだけ、呼び先のいちばん早い 1 つを、終端の決まりを満たす最初のフレームまで、もう一度書く。引数で読み書き先が変わる関数は、届く先ごとに書く。

### component から api_route への橋渡し (このプロファイルの要)

ブラウザ側からサーバー側へ入る口は 4 種類あり、辿り方が違う。まずどれかを見分ける。

| 入り方 | 見分け方 | 辿り方 |
|---|---|---|
| URL で呼ぶ (`+server.ts`) | `fetch` や API クライアントに URL の文字列がある | 下の 1〜6 の手順で `+server.ts` に対応付ける |
| 画面の load (`+page.server.ts` / `+layout.server.ts`) | 入口と同じフォルダにファイルがある | 入口のフレームの子として、`load` の関数をフレームにする (上の「load と actions を、どの層に書くか」) |
| form の action | `<form method="POST">` の `action` 属性 (`?/save`、無ければ同じ route の `default`)、`use:enhance`、`fetch` の URL に `?/name` | 送り先の route の `+page.server.ts` の `actions.<name>` を `api_route` フレームにし、`caller` は form を描くコンポーネント。`call` の evidence は `action=` の行 (または `<form` の行)。`when` は `conditional` (「form を送信したとき」) |
| remote functions | 呼んでいる関数の定義が `.remote.ts` (または `.remote.js`) にあり、`$app/server` の `query` / `command` / `form` / `prerender` で作られている | 関数の**定義**まで辿り、その関数を `api_route` フレームにする。URL を探さない |

URL で呼ぶ場合、関数の呼び出しを追うだけでは辿れないので、次の手順で対応付ける。

1. `fetch` や API クライアントの呼び出しから、URL の形と HTTP メソッドを読む (例: ``fetch(`${base}/conversation/${id}`, { method: "POST" })`` → `POST /conversation/<動的>`)
2. 共通の接頭辞を確かめる (`$app/paths` の `base`、API クライアントが前に付ける `/api/v2` など。付ける場所を 1 度読んで evidence にする)。API クライアントが、プロパティの連なりから URL を組み立てる作り (例: `client.user.settings.get()` → `GET /api/v2/user/settings`) は、組み立てる関数を 1 度読んで、その対応を evidence にする
3. routes の下で、その形に当たる `+server.ts` を探す (`${…}` の部分が `[id]` の段に当たる。`(group)` は URL に出ないので飛ばして探す)
4. その `+server.ts` の、HTTP メソッドと同じ名前の関数 (`export const GET`、`export async function POST`) を `api_route` フレームにし、`caller` で呼び出し側を指す。同じ名前の関数が無く、`fallback` があれば、それを指す
5. 同じフォルダに `+page.svelte` と `+server.ts` の両方があるとき: `PUT` / `PATCH` / `DELETE` / `OPTIONS` は、いつも `+server.ts`。`GET` / `POST` / `HEAD` は、`accept` が `text/html` を先に求めれば画面、そうでなければ `+server.ts` に届く。`fetch` で JSON を受け取る呼び出しは `+server.ts` に当てる
6. `call` の evidence は **呼び出し側の URL の行**。受け口の関数の行はフレームの `source` に書く

状態の付け方:

- URL の形が文字列としてそのまま読め、当たる `+server.ts` が 1 つに決まる → `fact`
- API クライアントの組み立てを読んで当てた → `interpretation` (組み立ての行と、呼び出しの行を evidence に)
- URL が変数や引数で組み立てられ、候補が複数ある → 候補が有限で全部読めるなら、それぞれフレームにして `interpretation` (`note` に「引数で切り替わる」)。決められないなら `unknown` + `dynamic_dispatch`
- 当たる `+server.ts` が scope に無い (別のサービスの API) → フレームにせず、呼び出し側の `io` に `external_api` として書く

サーバー側の load の中の `fetch` で、自分の `+server.ts` を呼ぶとき (SvelteKit は HTTP を通さず、受け口を直接動かす) も、同じ手順で `+server.ts` に当てる。

## 事実・解釈・不明の付け方

- **fact**: コードにそのまま書いてある (import と呼び出し、URL の文字列、DB クライアントのメソッドとコレクション、SQL の `from orders`)。根拠はその行
- **interpretation**: 読み取って要約したもの (フレームの summary、何のための処理か)。根拠は読んだ範囲の代表行
- **unknown**: 次の典型例ではこの理由を使う
  - URL やコレクション名が実行時の値で決まり、静的に読めない → `dynamic_dispatch`
  - 設定や DB に保存された定義から問い合わせを組み立てる → `generated_at_runtime`
  - 呼び先が scope の外、または別のパッケージ → `out_of_scope`
  - 配布物だけでソースが無い → `binary_or_vendored`

### 接続先 (host / database) の扱い

`ui-nextjs` と同じ。DB やキャッシュの接続先は、実行環境の設定 (`MONGODB_URL`、`DATABASE_URL` などの環境変数) で決まり、どの画面でも同じになる。

- 接続先の段 (`host`、`database`、`instance`、`broker`) は**書かない**。値をリポジトリから読めないため
- コレクション・テーブル・キー・トピックの名前がコードから読めれば、その I/O は `fact` にする (接続先が環境変数であることだけを理由に `unknown` にしない)
- 接続先がコードに直接書いてあるとき (固定の外部サービスなど) は、その段を書く
- 他社のサービスの SDK (例: `@slack/web-api`) が、既定で送る先が公開の文書で決まっているとき: `external_api` の `host` と `path` (SDK のメソッドに当たる API の path) を書き、状態は `interpretation` (根拠は、呼び出しの行と、クライアントを作る行)。送り先を設定で変えられる SDK で、設定の値がリポジトリに無いときは、`host` を書かずに `unknown` + `not_traceable_in_repo`

### 設定 (`settings`) の種類

- `$env/static/private` / `$env/static/public` (ビルドのときに値が埋め込まれる) も、`$env/dynamic/*` (実行のときに読む) も、`kind: env`。ビルドのときに決まる値 (`$env/static/*`、vite の `define` で埋め込む値) は、`note` に「ビルドのときに決まる」と書く

## データの当てはめ

- **MongoDB** (文書の DB) → `rdb`。段は `dbms: mongodb` と `table` (コレクションの名前)。データの種類の語彙に文書の DB は無いので、表とコレクションを同じ「行の集まり」として扱う
  - コレクションの名前は、`db.collection("…")` に渡している**文字**で確かめる (変数の名前やプロパティの名前ではない。例: `const tokenCaches = db.collection("tokens")` → `tokens`)。定数を渡しているときは、定数の値。ORM の `@@map` と同じ考え方
  - メソッド: `find` / `findOne` / `countDocuments` / `estimatedDocumentCount` / `distinct` / `aggregate` → `read`、`insertOne` / `insertMany` → `create`、`updateOne` / `updateMany` / `replaceOne` / `findOneAndUpdate` / `findOneAndReplace` → `update`、`deleteOne` / `deleteMany` / `findOneAndDelete` → `delete`。`upsert: true` を付けた更新は `create` と `update` の 2 件。`bulkWrite` は、中の操作の種類ごとに書く
  - `aggregate` の `$lookup` で引く別のコレクションは、そのコレクションの `read` も書く。`$merge` / `$out` で書き出す先は `create` と `update` (`$out` は置き換えなので `create` と `delete`)
  - `fields` の `name` は、文書の項目の名前 (入れ子は `a.b` のように点でつなぐ)。条件 (`{ userId: … }`) の項目は `filter`、`$set` の項目は `write`、`projection` で選ぶ項目は `read`。項目を選ばずに文書をまるごと取る呼び出しは `name: "*"`
- **GridFS** (MongoDB の中のファイル置き場) → `object_storage`。段は `bucket` (`bucketName`。既定は `fs`) と、分かれば `object` (ファイル名)。`openUploadStream` → `put`、`openDownloadStream` / `openDownloadStreamByName` → `get`、`delete` → `delete`、`find` → `list`
- ORM (Prisma、Drizzle) のモデル → `rdb`。テーブル名はモデルの定義で確かめる。メソッドの当てはめは `ui-nextjs` の `context.md` の「データの当てはめ」と同じ
- 生の SQL: `select … from` と `join` の表 → `read`、`insert into` → `create`、`update` → `update`、`delete from` → `delete`
- Redis などのキャッシュ → `kvs` (`namespace` / `key_pattern`。キーが組み立て式なら変数の部分を `*` にする。操作は get / set / delete / expire)
- Kafka などのメッセージ基盤 → `queue` (`topic`。操作は publish / consume)
- サーバーから他社のサービスを呼ぶ HTTP → `external_api` (`op: call`、host / path)
- ブラウザが他社のサービスから画像などを直接取る所 (`<img src="https://…">`) は、`external_api` (`op: call`、host / path) として、描くコンポーネントのフレームに書く。URL が祖先の load の値で決まり、この入口から読めないときは `unknown` + `dynamic_dispatch`
- ブラウザの中の保存 (localStorage、sessionStorage、cookie の読み書き) は、サーバーのデータではないので **I/O に書かない**。画面の動きに効くなら、そのフレームの `summary` に書く。サーバー側の `cookies.set` / `cookies.get` も同じ (セッションの id を cookie に置くだけなら書かない。セッションの中身を DB に読み書きするなら、その DB の I/O を書く)
