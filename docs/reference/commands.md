# コマンド

[← 仕様の地図へ](README.md)

分析リポジトリで使うコマンドの一覧です。場面ごとの手順は、[手引き](../guide/README.md) にあります。

## 一覧

```bash
# 分析リポジトリを作る (最初の 1 回だけ docker run。以後は compose.yaml がある)
mkdir my-analysis && cd my-analysis
docker run --rm -v "$PWD:/ws/analysis" -w /ws/analysis ghcr.io/suwa-sh/as-built-atlas:latest init . --profile batch-kestra
```

`.env` の `ABATLAS_TARGET` と `analysis/work-definition.yaml` を埋めてから、次を使います。

| やること | コマンド |
|---|---|
| 作業定義を検査する | `docker compose run --rm abatlas validate work analysis/work-definition.yaml` |
| プロファイルを検査する | `docker compose run --rm abatlas validate profile <profile.yaml>` |
| 対象のコードマップを作る | `docker compose run --rm abatlas code-map .`。[定義ファイルと入口の照合](update-commands.md) |
| 入口の一覧を検査する | `docker compose run --rm abatlas validate entries analysis/entry-list.yaml` |
| 入口を列挙する | `docker compose run --rm abatlas enumerate analysis/entry-list.yaml`。`--dry-run` を付けると、一覧を書かずに候補を出す。対象の clone にいまあるファイルを読む (Git が無視するファイルも読む。`code-map` と承認の案は、作業定義のコミットから取り出したファイルを読み、コミットに無いファイルは読まない。コミットの中のシンボリックリンクが対象の範囲の外を指すときの扱いは、抽出器で違う。`structured-query` はリンク先のいまの内容を読み、`ast` と `listed` はエラーで止まる) |
| コア同梱の抽出器と、その `params` の全項目を見る | `docker compose run --rm abatlas extractors [<名前>]` ([profiles.md](profiles.md) の「抽出器の契約」) |
| 対象のコードを、構文で探す | `docker compose run --rm abatlas code-search analysis/work-definition.yaml --language <言語> --files <glob> --pattern '<コードの形>'` |
| 分析結果を検査する | `docker compose run --rm abatlas validate result analysis/results/<file> --work analysis/work-definition.yaml` |
| レビューの指摘のファイルを検査する | `docker compose run --rm abatlas validate review analysis/reviews/<file> --result analysis/results/<file>` |
| 今回の分析を進める | `abatlas-run-analysis` で入口一覧と作業案を作り、一度の承認後に入口ごとに分析する。手順は、手引きの [初めて分析する](../guide/first-analysis.md) |
| 入口と作業の案を作る、承認する、残りの作業を見る | `propose`、`approve`、`queue` ([update-commands.md](update-commands.md) の「入口と作業を一度で承認する」) |
| 対象の差分から作業の一覧を出す、入口ごとに再利用を確定する | `impact`、`reuse` ([update-commands.md](update-commands.md) の「作業一覧を出す」「今回の結果を確定する」「結果の状態と差分」) |
| 分析結果に出てきた列を、データの辞書に足す | `docker compose run --rm abatlas dictionary .` (区分は決めない。案は skill `abatlas-classify-data` が書き、人が承認する) |
| 集計する | `docker compose run --rm abatlas build .` |
| 前の分析結果と比べる | `docker compose run --rm abatlas diff . --from <git の版>` (下の「分析結果の差分」) |
| 分析結果を表 (CSV) にするだけで、集計表は作らない | `docker compose run --rm abatlas etl analysis --out <CSV を書く場所>` |
| 画面・API・MCP を起動する | `docker compose up -d api` (画面は <http://localhost:8765>、MCP は <http://localhost:8765/mcp>)。中で動くのは `abatlas serve <分析リポジトリ>` ([api.md](api.md)) |
| MCP を、標準入出力でつなぐ | `abatlas mcp --api <API の URL>`。別のプロセスで動いている API を呼ぶ ([api.md](api.md) の「MCP」)。`abatlas` はコンテナの中のコマンドなので、ホストからは直接は呼べない。分析リポジトリでは、ふつうは上の行の <http://localhost:8765/mcp> を使う |
| 配布物を更新する | `docker compose pull && docker compose run --rm abatlas upgrade . && docker compose run --rm abatlas build . && docker compose up -d --force-recreate api` (順番と、版ごとにほかにやることは、手引きの [配布物を新しくする](../guide/upgrade.md)。版ごとの一覧は、as-built-atlas のリポジトリの `CHANGELOG.md` の「更新の手順」) |
| 分析結果を、正解か別の分析結果と突き合わせる | `docker compose run --rm abatlas evaluate <results> --truth <truth> [--json]` ([examples.md](examples.md) の「突き合わせ」) |
| 前の形式のファイルを、いまの形式に移す | `docker compose run --rm abatlas migrate . --dry-run` で、書き換わるファイルを見てから、`docker compose run --rm abatlas migrate .` |

検査と列挙は、プロファイルを、作業定義の `profile.dir` から自動で読みます (集計と同じファイル)。`--profile <profile.yaml>` で渡すこともできますが、集計が読むものと違うときは警告が出ます ([profiles.md](profiles.md) の「ツールが読むプロファイル」)。

`migrate` は、形式の項目名が変わった配布物に更新したときに使います。書き換えるのは、分析する側が持つファイル (入口の一覧、分析結果、独自の集計表の宣言、自分用のプロファイル) の項目の名前だけです。値とコメントは変えません。例外は 1 つで、文 (値) の中で項目を指している「`(tier: <id>)`」という書き方は、「`(layer: <id>)`」に直します。書き換えるのは、形式で決まった場所の項目だけです (抽出器の `params` や、入口の `attributes` のような、自由に書ける対応表の中は触りません)。機械で安全に移せないファイル (文やコメントや、自由に書ける対応表の中に、項目と同じ形の行がある、アンカーなどの特殊な書き方、前の名前といまの名前が並んでいる、コメントの中にも「`(tier: <id>)`」がある) は、書き換えずに知らせます (終了コード 1)。分析リポジトリの外と、配布物のコピー (`.abatlas/`) にあるファイルには、リンクを辿った先も含めて、触りません。リンクになっているファイルも、書き換えずに知らせます。集計表の宣言で直すのは、`abatlas:` の直下の `tier` だけです。SQL は書き換えず、前の名前らしい語があるファイルを知らせます。書き換えた後は、検査と集計をやり直します。

更新する入口を選ぶときは[対象コードの差分](update-commands.md)を使います。

エージェントへの MCP の登録は URL 1 行です (streamable HTTP)。

```bash
claude mcp add --transport http abatlas http://localhost:8765/mcp
```

## 分析結果の差分 (`diff`)

対象が変わった後に分析し直したら、`diff` で、前の分析結果と比べられます。比べる相手は、分析リポジトリの git の版 (コミット、タグ、`HEAD~1` など) にある分析結果です。分析結果を commit していることが前提です。

| 出るもの | 内容 |
|---|---|
| 1 行目 | 分析結果が変わった入口、足された入口、消えた入口の数 |
| `~ <入口>` | 変わった入口。観点 (入口の階層パスと層、処理の段と呼び出し元、読み書き、列、呼び出しの条件、つながり、権限の確認、設定、業務のルール、テスト) ごとに、足されたもの (`+`) と消えたもの (`-`) |
| `+ <入口>` / `- <入口>` | 分析結果が足された入口、消えた入口 |

- 比べるのは中身 (何を呼ぶか、どのデータをどう使うか) で、根拠の行番号と説明の文は見ません。対象の行がずれただけ、言い回しが変わっただけの違いは、出ません。
- 呼び出しの条件は、いつ起きるか (いつも / 条件つき / 失敗のとき) の変化だけを出します。条件の文だけが変わっても、出ません (分析のたびに言い回しが変わるためです)。
- 業務のルールは、内容の文で比べます。言い回しが変わると、「消えて、足された」と出ます。
- 同じ読み書きが 1 か所増えた、のような増減は、その個数の分だけ出ます。
- 分析の skill の版が違う結果どうしを比べると、観点が増えた分も差分に出ます (その旨が、入口の行に出ます)。
- コンテナの中で git が使えるように、分析リポジトリの `.git` が見える場所で実行します (`docker compose run` は、分析リポジトリのルートをマウントしています)。
