# kestra-ui-atlas (Vue Router の画面を分析した見本)

ワークフロー基盤 Kestra の画面 (Vue 3、`ui/`) を、as-built-atlas の `ui-vue-router` プロファイルで分析した状態の、分析リポジトリの資産です。プロファイルごとに 1 つ置いている見本の 1 つです ([見本の一覧](../../docs/architecture/examples.md))。

| | |
|---|---|
| 対象 | [github.com/kestra-io/kestra](https://github.com/kestra-io/kestra) (commit `28867c6`、範囲は `ui`) |
| プロファイル | `ui-vue-router` |
| 入口の一覧 | 62 件 (承認済み 7 件、候補のまま 55 件) |
| 分析結果とレビュー | 7 件ずつ (承認済みの入口だけ) |

対象のコードは入っていません。分析結果が持つのは、ファイルのパスと行番号、処理の要約、読み書きするデータの名前です。

## 入っている分析結果

| 入口の id | 何の入口か | 処理の段 | 読み書き |
|---|---|---|---|
| `shell_s.app` | 全部の画面を包む枠 (アプリの起動) | 40 | 9 |
| `login` | ログインの画面 | 32 | 12 |
| `flows` | Flow の一覧の画面 | 76 | 35 |
| `kv` | キーと値の保管の画面 | 38 | 14 |
| `dashboards.dashboard_o` | ダッシュボードの画面 | 29 | 10 |
| `part_p.dashboard-types.iokestraplugincoredashboardchartMarkdown` | ダッシュボードに描く部品 (Markdown) | 6 | 2 |
| `part_p.dashboard-types.iokestraplugincoredashboardchartTable` | ダッシュボードに描く部品 (表) | 6 | 2 |

見どころ:

- コードの中で定義したルーティングから、画面の入口を取っている
- ダッシュボードが、登録表から選んで描く部品を、別の入口 (`part`) に分けている。画面の側は、部品へのつながりを持つ

## 使い方

**このディレクトリを as-built-atlas の checkout の外へコピーし、隣に対象を clone する** (`abatlas init` が git リポジトリとして初期化し、設定を書き足すため)。

```bash
mkdir -p ~/abatlas-try && cp -r examples/kestra-ui-atlas ~/abatlas-try/
cd ~/abatlas-try
git clone https://github.com/kestra-io/kestra.git kestra
git -C kestra checkout 28867c6f0ef22f14610c8230406c24bcb35ec13a   # 分析結果の根拠の行は、この版のもの
cd kestra-ui-atlas

# 分析リポジトリとして初期化 (既にある .env と analysis/ は、そのまま)
docker run --rm -v "$PWD:/ws/analysis" -w /ws/analysis ghcr.io/suwa-sh/as-built-atlas:latest init . --profile ui-vue-router

docker compose run --rm abatlas validate result analysis/results/shell_s.app.yaml --work analysis/work-definition.yaml   # 根拠の行が、clone した対象に実在すること
docker compose run --rm abatlas build .        # ETL → dbt build
docker compose up -d api                        # 画面 http://localhost:8765  /  MCP http://localhost:8765/mcp
```

## 分析結果についての注意

- 分析結果は AI が書いたもので、人が 1 件ずつ読んで確かめてはいません。機械チェック (形式、根拠のファイルと行の実在) と、AI によるレビューは通っています。使ったモデルは、結果ごとの `analyzer.model` に書いてあります (`claude-opus-5-5`)
- レビューの指摘のうち、直した印 (`resolved`) が付いていないものが 1 件あります (重さは、どれも低いものです)。確かめられなかった読み書きが 13 件あります (理由付き)
- 分析したのは、入口の一部 (7 件) です。残りの 55 件は、抽出器が見つけた候補のままで、承認も分析もしていません。プロファイルの書き方を見せるための見本で、対象の全体の地図ではありません
- Kestra は開発元の著作物で、Apache License 2.0 です。この見本は対象の公式の文書ではなく、対象の開発元とは関係ありません。
- 対象の版が変わると、根拠の行番号はずれます。別の版を分析するときは、作業定義の `commit` を変えて分析し直します
