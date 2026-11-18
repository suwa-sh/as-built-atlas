# api プロファイル: エージェント向けの説明

対象は「サーバー側で、操作を受けて処理するシステム」。ほかのシステムやアプリから呼ばれる API (HTTP の API、メッセージを受ける・送る API、ツールを提供するサーバー、RPC) と、サーバー側で画面を作って返す webapp (route → controller → model の作り)。入口の発見と、入口ごとの分析で、このファイルと `profile.yaml` の両方を読む。

画面と API が同じリポジトリにあり、画面から辿れるシステムは、`ui-*` のプロファイルを使う (API の受け口は、画面から辿った途中の段として現れる)。画面を通らない API も見たいときは、分析リポジトリを分けて、このプロファイルを使う (分析リポジトリ 1 つ = プロファイル 1 つ)。

## アーキテクチャと層の連鎖

```text
operation (API の操作 1 つ。入口)
  → handler  (その操作を受け持つ関数と、操作に掛かる middleware)
    → logic    (処理の手順と、業務の決まり)
      → adapter  (データや外部とのやり取りを受け持つコード)
        → external (ORM、DB のドライバ、HTTP のクライアント、SDK。ここで終端)
```

層は、**役割**で分ける。言語や、フォルダの名前では分けない。

| 層 | 当てはめるもの | 例 |
|---|---|---|
| `operation` | API の操作の定義 | 定義ファイルの操作 (OpenAPI の path + method)。定義ファイルが無ければ、コードの登録の行 |
| `handler` | 操作を受け持つ関数。操作に掛かる middleware | controller、resolver、tool の handler、認証や権限の middleware |
| `logic` | 処理の手順、業務の決まり、値の検査や変換 | service、usecase、domain |
| `adapter` | データの出し入れ、外部の呼び出しを包むコード | repository、gateway、問い合わせを実行する関数、HTTP のクライアントを包む関数 |
| `external` | リポジトリに定義が無いもの | ORM、DB のドライバ、キャッシュのクライアント、SDK |

- 対象が、層をフォルダで分けていれば、対応を、分析リポジトリの `analysis-conventions.md` の「層とフォルダの対応」に書いてから分析する (入口ごとに当てはめがぶれないように)
- サーバー側で画面を作る作りでは、画面のひな形 (template、view) は、フレームにしない。ひな形が呼ぶ補助の関数が、データを読む・外を呼ぶときだけ、その関数をフレームにする (`caller` は、ひな形を描く受け口のフレーム)
- 層を分けていない小さな API では、`logic` と `adapter` を無理に作らない。`handler` から、直接 `external` を呼んでよい
- **フレームにする関数の目安**: 読み書きをする、外部を呼ぶ、業務のルール (判定、計算、検証) を持つ、権限の確認をする、のどれかに当たる関数。どれにも当たらない小さな補助 (入力の取り出し、型の変換、応答の整形) は、フレームにしない。フレームにしない関数が行う読み書き・設定・ルールは、それを呼ぶフレームに書く
- 機械チェックは、誰も呼ばないフレーム (終端) に、次のどれかを求める: 外との境の層 (`external`) である、読み書きを持つ、業務のルールを持つ、権限の確認を持つ、行き先が入口の一覧にあるつながり (`trigger`) を持つ、不明の主張を持つ
- `external` が `role: boundary`。ライブラリや SDK の呼び出しに達したら、閉じる

## 入口の判別

入口 1 件 = **呼び出す側から見た操作 1 つ**。

| API の種類 | 入口 | 見つけ方 |
|---|---|---|
| HTTP (OpenAPI の定義ファイルがある) | path + method | 抽出器 `openapi-operations`。`files` を、実際の置き場に合わせる |
| HTTP (定義ファイルが無い) | route の登録 1 つ (path + method) | route を登録しているコードを、`ast` の抽出器で拾うか、読んで `listed` で足す |
| メッセージ (AsyncAPI の定義ファイルがある) | channel + 操作 | 抽出器 `asyncapi-operations` |
| ツールを提供するサーバー (MCP など) | ツール 1 つ (リソース、プロンプトも) | 登録しているコードを、`ast` の抽出器で拾うか、読んで `listed` で足す。下の「抽出器の書き方の例」 |
| RPC (gRPC) | サーバーに登録した service の method 1 つ | 範囲の中の生成したコードを `ast` で拾うか、登録の行を読んで `listed` で足す。下の「gRPC」 |
| GraphQL | `Query` / `Mutation` / `Subscription` の field 1 つ | スキーマの定義を読んで `listed` で足す |

- 階層パスと id の作り方は、`profile.yaml` の `hierarchy.derivation` と、抽出器 `openapi-operations` の `id` のとおり (`GET /users/{id}` → `/users/{id}/get`、`users.id_d.get`)。`listed` で足す入口も、同じ作り方にそろえる。値が入る段の書き方がコードで違うとき (`:id`、`<id>`) も、階層と id では `{id}` の形にそろえる
  - 抽出器を `ast` や `listed` で書くときも、id の加工は、`openapi-operations` の `id.replace` の並びを、そのまま写す (値が入る所の `_d`、`_` を 2 つ重ねる、`.` は `-`)。写さないと、`{name}` の段が `name` になり、後で直すと承認が candidate に戻る
  - HTTP の path でない操作 (ツール、RPC、GraphQL) は、先頭に、かっこで囲んだ種類の段を置く (`/(mcp)/tools/<名前>`、`/(grpc)/<package>.<Service>/<Method>`、`/(graphql)/<query | mutation | subscription>/<field>`)。id では、種類の段は `mcp_x`、`grpc_x`、`graphql_x` になる (例: `mcp_x.tools.query__mart`、`grpc_x.shop-CheckoutService.PlaceOrder`)。HTTP の操作と同じリポジトリにあっても、木が分かれる
  - 同じ資源を指す値の段は、名前を 1 つにそろえる (枠組みが、入れ子の登録で `:story_id`、そのものの登録で `:id` と名前を変えても、階層ではどちらも `{id}`)。コードでの名前は、`attributes.route` に残す。そろえないと、同じ資源の下の操作が、別の枝に割れる
  - 省略できる段 (Rails の `(...)`、`(.:format)`) は落とし、省略したときの path を段にする
  - 同じ path と method が、制約 (値の形) で別の関数に分かれるときは、どちらも入口にし、後の方の id の末尾に `-<関数の名前>` を付ける (階層パスは同じでよい)
- 定義ファイルは、名前に頼らずに探す (先頭のキーが `openapi:` か `swagger:` のファイル。AsyncAPI は `asyncapi:`)
- **定義ファイルと、コードの登録を突き合わせる**。route を登録しているコード (router の登録、handler の対応表) を見つけ、path と method の一覧を、定義ファイルの一覧と比べる
  - 突き合わせるとき、値が入る段は、名前を無視して比べる (定義の `/lists/{list_id}` と、コードの `/lists/:id` は、同じ操作)
  - コードにあって、定義ファイルに無い操作 → `listed` で足す (`source` は、登録の行。`reason` に、定義ファイルに無いことを書く)。登録の行は、構文で探せる (例: Go の echo / gin / chi なら、`code-search` に `--pattern '$G.$M($PATH, $$$ARGS)'`。一致には、登録でない呼び出しも混ざるので、読んで選ぶ)
  - 定義ファイルにある操作は、同じ関数に当たるものが 2 つあっても、どちらも入口のまま (path と method の組が、入口 1 件)
  - コードにだけある登録が、既に入口になっている操作と同じ関数を、別の path に登録しているだけのとき (別名。例: 定義にある `/api/health` と、コードにだけある `/health`) は、足さない。抽出器 `agent-listed` の `rationale` と報告に、別名と、同じ関数の入口を書く。コードにだけある登録どうしが同じ関数のときは、**利用者が使う形** (画面のリンクや、呼ぶ側の文書が使う path。枠組みが名前を付けていれば、名前の付いた方) を 1 つ足し、ほかを `reason` に書く (登録の順で決めない。ルーティングの都合で、利用者が見る path の方が後に書かれていることがある)。ページ送りの path (`/x/page/:page`) と、形式だけ違う path (`/rss`、`.json`) は、別名にする
  - 応答が、別の URL へ移すだけの登録 (redirect だけ) は、入口にしない
  - 設定が有効なときだけ登録される route (`if cfg.X { ... }`) も、入口にする。条件を `reason` に書く (分析では、入口のフレームの `settings` に書く)
  - 定義ファイルにあって、コードに無い操作 → 入口のまま残す (分析で、「実装が見つからない」ことが結果に残る)。報告に並べる
  - 定義ファイルの servers が持つ共通の接頭辞 (`/api` など) と、コードの route の接頭辞の対応を、抽出器の `rationale` に書く
- **HTML を返す route** (サーバー側で画面を作る): サーバー側でデータを読み書きする・外を呼ぶなら、入口にする (応答が JSON か HTML かは、問わない)。入口にしないのは、中身が決まっているものを返すだけの route (静的なファイル、ブラウザ側で動く画面の殻、設定の値を返すだけのもの)。どちらかは、受け口の関数を読んで決める。まとめて外した route は、抽出器の `rationale` と報告に書く
- 入口にしないもの: 上の、中身が決まっているものを返すだけの route、開発用の route、枠組みが自動で足す文書の route (`/openapi.json`、`/docs` など)、ほかのプロトコルの転送口 (MCP の `/mcp`、GraphQL の `/graphql`。転送口の上の操作 (ツール、問い合わせ) を入口にする)。サブアプリを差し込む行 (`mount`、`include_router` など) は、差し込まれた側の登録を辿って入口にする (差し込む行そのものは、入口にしない)。外した route は、抽出器の `rationale` に書く。迷ったら入口にして、`reason` に迷った点を書く (人が `rejected` にできる)
- 定義ファイルが、コードから生成されるもの (注釈から作る) で、リポジトリに無いときは、コードの登録を入口の出どころにする

### 抽出器の書き方の例 (定義ファイルが無いとき)

どれも、抽出器 `ast` で、実物で動いた設定。`rule` を、対象の枠組みの書き方に合わせて直す。一致には、登録でない呼び出しも混ざるので、`--dry-run` で読んで確かめる。`id` は、`openapi-operations` の `id.replace` の並びを写す。

| 作り | `rule` | `fields` と `segments` | 取れないもの (読んで `listed` で足す) |
|---|---|---|---|
| Python の FastAPI / Flask | `pattern: '@app.$M($PATH)'` | `path: "{PATH}/{M}"` | `unresolved` に、`$X.mount($$$A)`、`$X.include_router($$$A)`、`$X.add_api_route($$$A)` を書く |
| Go の echo / gin / chi | `pattern: '$G.$M($PATH, $$$ARGS)'` | `path: "{PATH}/{M}"`。`:id` は `segments.replace` で `{id}` に | group の入れ子で決まる接頭辞 |
| Ruby の Rails (`config/routes.rb`) | `$M $PATH => $TO` と `$M $PATH => $TO, $$$REST` (`constraints` で `M` を `get\|post\|patch\|put\|delete` に絞る) | `path: "{PATH}/{M}"`。`segments.replace` で、`(.:format)` を落とし、`:x` を `{x}` に | 1 行が複数の操作になる書き方 (`resources`、`member`、入れ子の `resources`)、method を値で渡す書き方 (`match … via:`)、`root`。枠組みの規約 (`only` / `except`、入れ子の `:<単数>_id`) を読んで足す。`resources` が作る PUT は、PATCH の別名なので足さない。`namespace` の中は、別の抽出器にして、`inside` と `segments.prefix` で接頭辞を付ける |
| MCP の Python の SDK | `@mcp.tool()` を付けた関数 (`pattern: "@mcp.tool()\nasync def $NAME($$$ARGS) -> $R:\n    $$$BODY"`) | `path: "{NAME}"`、`segments.prefix: ["(mcp)", tools]` | `unresolved` に、`$S.add_tool($$$A)`、`@mcp.resource($$$A)`、`@mcp.prompt($$$A)`。`name` の引数で名前を付けている登録 |
| gRPC の Go の生成したコード (`*_grpc.pb.go`) | `grpc.ServiceDesc` の中の、`MethodName` / `StreamName` の値 (`$M`) と、同じ `var_spec` の `ServiceName` の値 (`$S`)。`constraints` で、登録している service に絞る | `path: "{S}/{M}"`、`segments.prefix: "(grpc)"` | 生成したコードが範囲に無い service、ライブラリが用意する service |

### gRPC

- 入口は、サーバーに**登録した** service の method 1 つ (`Register<Service>Server(srv, impl)` の行で確かめる)。生成したコードや `.proto` にあっても、登録していない service (ほかのサービスを呼ぶためのスタブ) は、入口にしない
- `.proto` が範囲の外にあるとき (サービスの間で共有するフォルダなど) は、根拠にできない。範囲の中に生成したコードがあれば、そのサーバー側の記述 (Go なら `grpc.ServiceDesc` の `MethodName` / `StreamName` の行) を入口の `source` にする。生成したコードも範囲に無ければ、登録の行を `source` にして `listed` で足す
- ライブラリが用意したサーバーを登録している service (標準のヘルスチェック、reflection) も、登録していれば入口の候補にする。中身はライブラリにあるので、`reason` に書き、承認で判断する。分析では、handler を作らず、入口の下に `external` のフレーム (`kind: library`) を 1 つ置く (`source` は登録の行。中身は `unknown` + `out_of_scope`)
- 入口から handler へ: `MethodName` (`StreamName`) の行、`Handler` の行、`Register<Service>Server` の行を根拠に並べ、登録に渡した値の型の、同じ名前のメソッドを handler にする (`interpretation`)。生成した仲介の関数は、フレームにしない。登録していない型に同じ名前のメソッドがあっても、handler にしない
- ストリーミングの method も、入口は method 1 つ。呼び出しの木は、1 回のやり取りの method と同じに書き、ストリームの中で繰り返し送る・受けることは `summary` に書く。種類は、入口の `attributes` (`rpc_kind`) に書く
- サーバーに掛ける interceptor は、middleware と同じ扱い (`handler` 層の `kind: middleware`)。サーバー全体に掛かるので、どの method の経路にも書く
- ほかのサービスを gRPC で呼ぶ所は、下の「データの当てはめ」

### MCP のツール

- 入口のフレームの `kind` は `mcp_tool`、`source` は登録の行 (飾りや、登録の関数の呼び出し)。ツールの説明 (docstring、`description`) を入口の `summary` に、引数 (名前、型、既定値) を `parameters` に書く (`value` に、型と既定値)。説明とコードが食い違うときは、コードを正として書き、食い違いを `summary` の `note` に書く
- 登録が飾る関数を `handler` にする (中身が 1 行で、別の関数を呼ぶだけでも、登録が指す関数なのでフレームにする。`call` の根拠は、登録の行)
- 同じツールを、別の転送 (標準入出力と HTTP) で出していても、入口は 1 つ
- 転送口で SDK が行う確認 (Host / Origin の許可) は、フレームにしない。許可の集合を、リポジトリのコードが作っていれば、入口のフレームの `summary` の `note` に、作っている行と一緒に書く
- ツールが、同じリポジトリの HTTP の操作を呼ぶだけのときは、下の「ほかの入口へのつながり」

### サーバー側で画面を作る webapp (route → controller → model → view)

- 入口は、route 1 つ (path + method)。別名の扱いは、上の「入口の判別」
- route から action へ: 登録の行に、path と行き先が書いてあれば `fact`。枠組みの規約で操作が決まる登録 (Rails の `resources`) は `interpretation` にし、根拠に、登録の行と、規約を絞る行 (`only` / `except`、入れ子の外側の行) を並べる
- **層の当てはめ**: controller の action と callback は `handler`。model の判定と callback は `logic`。model の問い合わせ (scope を含む)、helper、mailer は `adapter`。ORM の読み書きは、呼ぶ段の `io` に書き、`external` のフレームは作らなくてよい。テーブルは、model の名前と、スキーマの定義 (`db/schema.rb` など) で確かめる
- **callback** (`before_action` / `around_action` / `after_action`): 基底の controller や concern のものも含め、`only:` / `except:` / `if:` で、その action に掛かるかを確かめ、掛かるものだけを `handler` のフレームにする (`kind` は callback の種類)。読み書きか、止める確認をするものだけをフレームにする。CSRF の確認は、フレームにしない
- **権限の確認**: ログインしていれば利用者を決めるだけで、止めない callback は、`guards` に書かず `rules` に書く。止めるものは `kind: authentication`。`guards[].value` は、受け手 (`@user.`、`user&.`) を付けず、判定する関数の名前だけを書く。action の中で判定して止める分かれ道は、判定する関数の段に `kind: permission`。役割の判定は `kind: role`
- **view** (テンプレート、partial、layout) は、フレームにしない。view が呼ぶ、データを読む model の関数と helper をフレームにし、`caller` は action。view が関連を直接たどる読み取りは、action の `io` に書く。layout が読むものは、HTML を描く入口では、どの入口でも同じ綴りで書く (redirect や、部分の HTML だけを返す入口では書かない)。読み切れない partial は、`not_analyzed` を 1 件にまとめ、`note` に並べる。ブラウザ側の JavaScript は、フレームにしない
- **保存が動かす処理**: `save` / `create` / `update` が動かす model の callback は、`logic` のフレーム (`kind: callback`) にし、`caller` は保存を呼ぶ段。`call` は `interpretation` で、根拠に、保存の行と、callback の宣言の行を並べる。読み書きをしない callback は、フレームにしない。関連の宣言が足す書き込み (`touch: true`、`counter_cache`) と、読み書きをする検証 (`uniqueness`、必須の `belongs_to`) は、保存を呼ぶ段の `io` に `interpretation` で書く (根拠は、宣言の行)
- **ジョブとメール**: ジョブ (`perform_later`) は、入口の一覧に無ければ `queue` の `publish` (キューの名前) にし、`note` に、ジョブのクラスと、後で何をするかを書く。メールは、`<Mailer>#<関数>` を `adapter` のフレーム (`kind: mailer`) にし、すぐ送る (`deliver_now`) なら `external_api` の `call`、後で送る (`deliver_later`) なら `queue` の `publish`
- **transaction** は、フレームにせず、中の書き込みが 1 つの単位で戻ることを、書いた段の `rules` に書く
- **応答の返し分け** (`respond_to`、`request.xhr?`): 分かれ道の先の段を `conditional` にし、条件に形式を書く。route が形式を絞っているときは、`note` に書く
- **ページのキャッシュ** (`caches_page`): after_action のフレームにし、書き込みは `filesystem` の `write`
- **共通の段の綴りは、先に決める**: どの action にも掛かる callback や、layout が読むものは、どの入口の結果にも出る。1 件目を分析する前に、綴り (フレームの名前、`guards` の `value`) を、分析リポジトリの `analysis-conventions.md` に書く

## 入口ごとの分析で見るもの

| 層 | 読む場所 | 拾うこと |
|---|---|---|
| operation | 定義ファイルの操作 (無ければ、登録の行) | 入力 (`parameters`: path・query・header の項目、本文)。定義が求める認証 (`security`) |
| handler | 登録の行が指す関数と、その route に掛かる middleware | 入力の解釈、権限の確認、呼ぶ処理 |
| logic | 処理の関数 | 呼び出しの順と条件、業務のルール、設定による切り替え |
| adapter | やり取りを包むコード | テーブルと操作、読み書きする列、キャッシュのキー、相手のホストと path |
| external | ライブラリを呼んでいる行 | `source` は、その行 |

### operation から handler への橋渡し (このプロファイルの要)

入口のフレーム (`layer: operation`) の `source` は、入口の一覧の `source` と同じ (定義ファイルの操作の行)。そこから、コードの handler へは、関数の呼び出しでは辿れないので、次の手順で対応付ける。

1. 定義ファイルの path と method を読む (servers の共通の接頭辞も)
2. route を登録しているコードで、その path と method に当たる登録の行を探す (path の値が入る所の書き方は、枠組みで違う。`{id}` と `:id` など)
3. 登録の行が指す関数を `handler` フレームにし、`caller` で入口のフレームを指す。`call` の根拠は、**登録の行**。関数の定義の行は、フレームの `source` に書く

状態の付け方:

- 登録の行に、path と method がそのまま書いてあり、当たる登録が 1 つに決まる → `fact`
- path が、変数や、入れ子の登録 (group) の組み合わせで決まる → 組み合わせを辿って決められれば `interpretation` (根拠に、辿った行を並べる)
- 当たる登録が見つからない → `handler` フレームを作らず、入口のフレームの `summary` に「実装が見つからない」と書いて `unknown` + `not_traceable_in_repo` にする (`note` に、探した場所を書く)
- 入口の `source` がコードの登録の行のとき (定義ファイルに無い操作) は、入口のフレームの `source` もその行。橋渡しは、登録の行が指す関数へ辿るだけでよい

定義ファイルとコードが食い違うとき (定義にある入力をコードが読まない、定義が認証を求めるのにコードに確認が無い、など) は、**コードを正として書き**、食い違いを、入口のフレームの `summary` の `note` に書く。

### middleware (操作に掛かる共通の処理)

認証、権限の確認、利用の制限、記録など、handler の前後で動く処理。

- その操作に**実際に掛かる** middleware だけを辿る (登録の行、group の設定、handler を包む関数から確かめる)
- 権限の確認をする middleware、データを読み書きする middleware、外部を呼ぶ middleware を、`handler` 層のフレーム (`kind: middleware`) にする。`caller` は入口のフレーム。handler より前に動くものは、handler より前に書く (入口から辿る順が、動く順になる)
- 記録や、応答の圧縮のように、読み書きにも確認にも当たらない middleware は、フレームにしない
- 確認だけをして、読み書きを持たない middleware は、`guards` を持つフレームとして終端にできる (機械チェックは、権限の確認を持つ終端を認める)
- 呼び出し元の場所の確認 (Host、Origin、IP の許可) は、`guards` の `kind: other` にし、`value` に、許可の集合を作る式を書く
- 権限の確認は、確認を実際に行っている段に `guards` で書く。判定する関数と、判定の結果を受けて止める関数が分かれているときは、判定する側に書く。求める権限の名前が、登録の行で渡されているとき (例: `perm("users:manage")`) は、その行も根拠に入れる
  - `value` は、権限の値そのもの (実行時に比べる文字列。例: `users:manage`)。定数の名前で書かれていれば、定義を読んで、値を書く
  - どれか 1 つを持てば通る確認 (`perm(h, A, B)`) は、権限ごとに 1 件ずつ書き、それぞれの `note` に「どれか 1 つで通る」と書く
  - ある権限を持てば、後ろの確認 (持ち主や所属の確認) を飛ばす作りでは、飛ばす権限も `guards` に書く (`kind: permission`。`note` に「これを持てば、所属の確認をしない」)。後ろの確認は、別の 1 件 (`kind: ownership`) にする
  - id の形だけの検査 (数字か、空でないか) は、権限の確認にも、業務のルールにも書かない
- ログインの確認の経路 (セッションやトークンから利用者を引く) は、利用者を読む最初の読み書きまでを書く。どの操作でも同じなので、綴りと木の形を、入口をまたいでそろえる
- どの操作にも同じ middleware が掛かるので、同じ経路を操作の数だけ書くことになる。middleware の先は、**読み書きを持つ最初のフレームまで**書けばよい (`external` までは書かない)。分析リポジトリの `analysis-conventions.md` が、省いてよい範囲を決めていれば、それに従う

### フレームの名前と、層の当てはめで迷う所

- **枠組みやライブラリの関数を、リポジトリの中で定義し直しているとき** (monkeypatch): `external` にせず、役割の層 (多くは `adapter`) にする
- **深い処理を、途中で打ち切るとき** (読み書きを持つ最初の段で閉じる、と分析リポジトリで決めたとき): 打ち切った段の下で行う読み書きは、打ち切った段の `io` にまとめて書き、辿らなかった関数の名前を `summary` に書く (`not_analyzed` は使わない)
- **範囲の外のライブラリのコード**は、根拠にしない。読んで分かったことは、版と一緒に `note` に書いてよい
- **中身の無い包む関数** (引数をそのまま渡して、別の関数を呼ぶだけ): フレームにしない。実体の関数をフレームにし、`name` は実体の名前にする (`call` の根拠に、包む関数を呼んでいる行と、包む関数が実体を呼ぶ行を並べる)
- **起動のときに渡された関数を呼ぶとき** (処理の層が、受け口の層で定義した関数を、フックとして呼ぶ): 層は、置き場ではなく、役割で決める (データを読み書きするなら `adapter`、手順なら `logic`)。`call` は `interpretation` にし、根拠に、渡している行と、呼んでいる行を並べる
- **同じプロセスの中で、裏で動く処理に合図を送るとき** (止める印を付ける、内部の待ち行列に積む): 裏で動く処理が、入口の一覧にあれば `links` (`kind: trigger`)。無ければ、合図を送る段の `summary` と `note` に、「裏の処理が、後で何をするか」を書いて閉じる (裏の処理の中は、辿らない)

### 同じ処理が何度も呼ばれるとき

1 つの入口の中で、同じ関数が複数の所から呼ばれるときは、入口から、コードに書いてある順に深さ優先で辿って、最初に着いた呼び出し元の下に 1 回だけ書く。ほかの呼び出し元は、`summary` に「<関数> も呼ぶ。経路はフレーム `<id>` と同じ」と書く。そうすると呼び出し元が終端になり、終端の決まり (機械チェック) を満たせないときだけ、読み書きを持つ最初のフレームまで、もう一度書く。

### ほかの入口へのつながり

- 処理の中で、ジョブや別の操作を起動する (キューに積む、内部の API を呼ぶ) とき、相手が入口の一覧にあれば `links` (`kind: trigger`) に書く。無ければ、読み書き (`queue` の publish、`external_api`) に書く
- 応答で、別の URL へ移す (redirect) だけの操作は、`links` (`kind: navigate`) に書く
- MCP のツールや、画面のための API (BFF) が、同じリポジトリの HTTP の操作を、HTTP のクライアントで呼ぶだけのとき (同じプロセスへの直結を含む): クライアントを包む段 (`adapter`) に `links` (`kind: trigger`、`target` はコードの path の書き方、`entry_id` は呼ぶ操作の入口) を書き、呼ばれる操作の中は、辿り直さない。`io` (`external_api`) には書かない。HTTP のクライアントの呼び出しを `external` にして閉じる
- ほかのサービスを gRPC で呼ぶとき、相手のサービスが、同じ分析リポジトリの入口にあれば、`links` (`kind: trigger`、`entry_id`) も書く (読み書きの `path` は、実際に通る path のまま)

## 事実・解釈・不明の付け方

- **fact**: コードや定義にそのまま書いてある (登録の行の path と method、SQL の `from subscribers`、ORM のメソッドとモデル)。根拠はその行
- **interpretation**: 読み取って要約したもの (フレームの `summary`)
- 名前で引く問い合わせ (SQL を別のファイルに置き、名前で読み込む作り): 名前がコードにそのまま書いてあり、当たる SQL が 1 つに決まるなら、読み書きも、SQL の中の業務のルールも `fact` (根拠に、名前を使う行と、SQL の行の両方を書く)。名前が変数で決まるときは `interpretation` か `unknown`
- **unknown**: 次の典型例では、この理由を使う
  - 定義ファイルの操作に当たる実装が、リポジトリに見つからない → `not_traceable_in_repo`
  - 呼ぶ関数や、実行する SQL が、実行時の値で決まる → `dynamic_dispatch`
  - 設定や DB に保存された定義から、問い合わせを組み立てる → `generated_at_runtime`
  - 呼び先が、範囲の外か、別のリポジトリ → `out_of_scope`
  - 配布物だけでソースが無い → `binary_or_vendored`

### 接続先 (host / database) の扱い

DB やキャッシュの接続先は、実行環境の設定で決まり、どの操作でも同じになる。

- 接続先の段 (`host`、`database`、`instance`、`broker`) は書かない。値をリポジトリから読めないため
- テーブル・キー・トピックの名前がコードから読めれば、その読み書きは `fact` にする (接続先が設定であることだけを理由に `unknown` にしない)
- 接続先がコードに直接書いてあるとき (固定の外部サービスなど) は、その段を書く

## データの当てはめ

- RDB (ORM、SQL、ドライバ) → `rdb`。段は `dbms` と `table` (分かれば `schema`)。SQL の `select … from` と `join` の表は `read`、`insert into` は `create`、`update` は `update`、`delete from` は `delete`。1 つの SQL が複数の表に触れるときは、表ごとに 1 件
- SQL を別のファイルに置き、名前で読み込む作りでは、読み書きは、その SQL を**実行している段**に書く。根拠に、実行の行と、SQL の行の両方を書く
- キャッシュ (Redis など) → `kvs`。キーが組み立て式なら、変わる部分を `*` にする
- メッセージ基盤 → `queue` (publish / consume)
- ファイル、オブジェクトストレージ → `filesystem`、`object_storage`
- ほかのサービスを呼ぶ HTTP、メールの送信、通知 → `external_api` (`op: call`、host / path。相手が設定で決まるときは、分かる段だけ書く)
- ほかのサービスを gRPC で呼ぶ → `external_api`、`op: call`。段は `path` だけにし、値は、呼ぶ method の完全な名前 (`/<package>.<Service>/<Method>`)。host は、環境変数などで決まるなら書かない (`path` が読めれば `fact`)。生成したクライアントは `external` のフレーム (`kind: library`) にし、中を辿らない。`io` は、それを呼ぶ段 (`adapter`) に書き、`external` のフレームには重ねない。`fields` は、送る項目が `write`、受け取るメッセージは `*` で `read`
- 埋め込みの DB (SQLite、DuckDB) も `rdb` (`dbms` に、製品名を小文字で)。DB のファイルそのものを入れ替える・消す操作は `filesystem`。別のプロセスで起動する CLI は、`external` にして閉じ、その CLI が行う読み書きは、`call` の `note` に書く
- **データベースに保存された設定** (設定の表を読んで、動きを変える): 表の読み取りは、読み書きに書く。動きを変える設定は、`settings` に書く (`kind: other`、`name` は、設定のキー。`note` に、どの表にあるかを書く)
- 応答 (返す値) は、読み書きに書かない。応答の形が決まりを持つとき (状態で返す値が変わる、など) は、決めている段の `rules` に書く
