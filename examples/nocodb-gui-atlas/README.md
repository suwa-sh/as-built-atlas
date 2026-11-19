# nocodb-gui-atlas (Nuxt の画面を分析した見本)

表計算の形のデータベース NocoDB の画面 (Nuxt、`packages/nc-gui/`) を、as-built-atlas の `ui-nuxt` プロファイルで分析した状態の、分析リポジトリの資産です。プロファイルごとに 1 つ置いている見本の 1 つです ([見本の一覧](../../docs/architecture/examples.md))。

| | |
|---|---|
| 対象 | [github.com/nocodb/nocodb](https://github.com/nocodb/nocodb) (commit `657eb60`、範囲は `packages/nc-gui`) |
| プロファイル | `ui-nuxt` |
| 入口の一覧 | 69 件 (承認済み 3 件、候補のまま 66 件) |
| 分析結果とレビュー | 3 件ずつ (承認済みの入口だけ) |

対象のコードは入っていません。分析結果が持つのは、ファイルのパスと行番号、処理の要約、読み書きするデータの名前です。

## 入っている分析結果

| 入口の id | 何の入口か | 処理の段 | 読み書き |
|---|---|---|---|
| `signin` | サインインの画面 | 21 | 6 |
| `index.typeOrId_d.form.viewId_d` | 共有したフォームを開く画面 | 10 | 4 |
| `shell_s.middleware.03-auth-global` | どの画面の前にも動く、認証の確認 | 10 | 5 |

見どころ:

- `pages/` のファイルから画面の入口を取り、どの画面の前にも動く処理 (middleware) を別の入口にしている

## 使い方

**このディレクトリを as-built-atlas の checkout の外へコピーし、隣に対象を clone する** (`abatlas init` が git リポジトリとして初期化し、設定を書き足すため)。

```bash
mkdir -p ~/abatlas-try && cp -r examples/nocodb-gui-atlas ~/abatlas-try/
cd ~/abatlas-try
git clone https://github.com/nocodb/nocodb.git nocodb
git -C nocodb checkout 657eb609d038355d4c489ba70b9fcf1d96295e07   # 分析結果の根拠の行は、この版のもの
cd nocodb-gui-atlas

# 分析リポジトリとして初期化 (既にある .env と analysis/ は、そのまま)
docker run --rm -v "$PWD:/ws/analysis" -w /ws/analysis ghcr.io/suwa-sh/as-built-atlas:latest init . --profile ui-nuxt

docker compose run --rm abatlas validate result analysis/results/signin.yaml --work analysis/work-definition.yaml   # 根拠の行が、clone した対象に実在すること
docker compose run --rm abatlas build .        # ETL → dbt build
docker compose up -d api                        # 画面 http://localhost:8765  /  MCP http://localhost:8765/mcp
```

## 分析結果についての注意

- 分析結果は AI が書いたもので、人が 1 件ずつ読んで確かめてはいません。機械チェック (形式、根拠のファイルと行の実在) と、AI によるレビューは通っています。使ったモデルは、結果ごとの `analyzer.model` に書いてあります (`claude-opus-5-5`)
- レビューの指摘のうち、直した印 (`resolved`) が付いていないものが 1 件あります (重さは、どれも低いものです)
- 分析したのは、入口の一部 (3 件) です。残りの 66 件は、抽出器が見つけた候補のままで、承認も分析もしていません。プロファイルの書き方を見せるための見本で、対象の全体の地図ではありません
- NocoDB は開発元の著作物で、Sustainable Use License 1.0 です (オープンソースのライセンスではありません。使い方に制限があるので、clone する前に NocoDB の `LICENSE.md` を読んでください)。この見本は対象の公式の文書ではなく、対象の開発元とは関係ありません。
- 対象の版が変わると、根拠の行番号はずれます。別の版を分析するときは、作業定義の `commit` を変えて分析し直します
