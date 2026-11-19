# relay-gate-atlas (コマンドラインの道具を分析した見本)

RelayGate の、設定を検査するコマンド (シェルスクリプト) を、as-built-atlas の `cli` プロファイルで分析した状態の、分析リポジトリの資産です。プロファイルごとに 1 つ置いている見本の 1 つです ([見本の一覧](../../docs/architecture/examples.md))。

| | |
|---|---|
| 対象 | [github.com/suwa-sh/relay-gate](https://github.com/suwa-sh/relay-gate) (commit `aa69938`) |
| プロファイル | `cli` |
| 入口の一覧 | 4 件 (承認済み 3 件、候補のまま 1 件) |
| 分析結果とレビュー | 3 件ずつ (承認済みの入口だけ) |

対象のコードは入っていません。分析結果が持つのは、ファイルのパスと行番号、処理の要約、読み書きするデータの名前です。

## 入っている分析結果

| 入口の id | 何の入口か | 処理の段 | 読み書き |
|---|---|---|---|
| `facade.validate-config.feature-flag` | 機能フラグの設定を検査するコマンド | 25 | 22 |
| `facade.validate-config.job-map` | ジョブの対応表 (CSV) を検査するコマンド | 14 | 9 |
| `facade.validate-config.rapid-crosscheck` | 速報の突き合わせの設定を検査するコマンド | 15 | 10 |

見どころ:

- 1 つのスクリプトの、検査の種類を選ぶオプションごとに入口を分けている
- 終了コードと、標準出力に出す行の決まりを、要約に書いている

## 使い方

**このディレクトリを as-built-atlas の checkout の外へコピーし、隣に対象を clone する** (`abatlas init` が git リポジトリとして初期化し、設定を書き足すため)。

```bash
mkdir -p ~/abatlas-try && cp -r examples/relay-gate-atlas ~/abatlas-try/
cd ~/abatlas-try
git clone https://github.com/suwa-sh/relay-gate.git relay-gate
git -C relay-gate checkout aa6993823306a84935b99824059fa544779bc212   # 分析結果の根拠の行は、この版のもの
cd relay-gate-atlas

# 分析リポジトリとして初期化 (既にある .env と analysis/ は、そのまま)
docker run --rm -v "$PWD:/ws/analysis" -w /ws/analysis ghcr.io/suwa-sh/as-built-atlas:latest init . --profile cli

docker compose run --rm abatlas validate result analysis/results/facade.validate-config.feature-flag.yaml --work analysis/work-definition.yaml   # 根拠の行が、clone した対象に実在すること
docker compose run --rm abatlas build .        # ETL → dbt build
docker compose up -d api                        # 画面 http://localhost:8765  /  MCP http://localhost:8765/mcp
```

## 分析結果についての注意

- 分析結果は AI が書いたもので、人が 1 件ずつ読んで確かめてはいません。機械チェック (形式、根拠のファイルと行の実在) と、AI によるレビューは通っています。使ったモデルは、結果ごとの `analyzer.model` に書いてあります (`claude-opus-5-5`)
- レビューの指摘は、すべて直した印 (`resolved`) が付いています
- 分析したのは、入口の一部 (3 件) です。残りの 1 件は、抽出器が見つけた候補のままで、承認も分析もしていません。プロファイルの書き方を見せるための見本で、対象の全体の地図ではありません
- RelayGate は MIT License です。
- 対象の版が変わると、根拠の行番号はずれます。別の版を分析するときは、作業定義の `commit` を変えて分析し直します
