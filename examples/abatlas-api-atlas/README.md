# abatlas-api-atlas (API を分析した見本)

as-built-atlas 自身の API と MCP (Python、FastAPI) を、as-built-atlas の `api` プロファイルで分析した状態の、分析リポジトリの資産です。プロファイルごとに 1 つ置いている見本の 1 つです ([見本の一覧](../../docs/architecture/examples.md))。

| | |
|---|---|
| 対象 | [github.com/suwa-sh/as-built-atlas](https://github.com/suwa-sh/as-built-atlas) (commit `aa48c00`、範囲は `abatlas`) |
| プロファイル | `api` |
| 入口の一覧 | 15 件 (承認済み 3 件、候補のまま 12 件) |
| 分析結果とレビュー | 3 件ずつ (承認済みの入口だけ) |

対象のコードは入っていません。分析結果が持つのは、ファイルのパスと行番号、処理の要約、読み書きするデータの名前です。

## 入っている分析結果

| 入口の id | 何の入口か | 処理の段 | 読み書き |
|---|---|---|---|
| `marts.name_d.rows.get` | 集計表の行を返す API | 9 | 3 |
| `mcp.query__mart` | MCP の道具 (集計表を引く) | 4 | 0 |
| `recompute.post` | 集計し直す API | 15 | 26 |

見どころ:

- HTTP の受け口と、MCP の道具を、同じ `operation` の入口として並べている
- 集計し直す API は、ETL と dbt の実行までを辿り、読み書きを 26 件挙げている

## 使い方

**このディレクトリを as-built-atlas の checkout の外へコピーし、隣に対象を clone する** (`abatlas init` が git リポジトリとして初期化し、設定を書き足すため)。

```bash
mkdir -p ~/abatlas-try && cp -r examples/abatlas-api-atlas ~/abatlas-try/
cd ~/abatlas-try
git clone https://github.com/suwa-sh/as-built-atlas.git as-built-atlas
git -C as-built-atlas checkout aa48c0046e528ce4c04b1e778b5cd38ebc94b069   # 分析結果の根拠の行は、この版のもの
cd abatlas-api-atlas

# 分析リポジトリとして初期化 (既にある .env と analysis/ は、そのまま)
docker run --rm -v "$PWD:/ws/analysis" -w /ws/analysis ghcr.io/suwa-sh/as-built-atlas:latest init . --profile api

docker compose run --rm abatlas validate result analysis/results/marts.name_d.rows.get.yaml --work analysis/work-definition.yaml   # 根拠の行が、clone した対象に実在すること
docker compose run --rm abatlas build .        # ETL → dbt build
docker compose up -d api                        # 画面 http://localhost:8765  /  MCP http://localhost:8765/mcp
```

## 分析結果についての注意

- 分析結果は AI が書いたもので、人が 1 件ずつ読んで確かめてはいません。機械チェック (形式、根拠のファイルと行の実在) と、AI によるレビューは通っています。使ったモデルは、結果ごとの `analyzer.model` に書いてあります (`claude-opus-5-5`)
- レビューの指摘は、すべて直した印 (`resolved`) が付いています。確かめられなかった読み書きが 1 件あります (理由付き)
- 分析したのは、入口の一部 (3 件) です。残りの 12 件は、抽出器が見つけた候補のままで、承認も分析もしていません。プロファイルの書き方を見せるための見本で、対象の全体の地図ではありません
- as-built-atlas は MIT License です。
- 対象の版が変わると、根拠の行番号はずれます。別の版を分析するときは、作業定義の `commit` を変えて分析し直します
