# icecubes-atlas (iOS の画面を分析した見本)

Mastodon のクライアント Ice Cubes (Swift、SwiftUI) を、as-built-atlas の `ui-ios` プロファイルで分析した状態の、分析リポジトリの資産です。プロファイルごとに 1 つ置いている見本の 1 つです ([見本の一覧](../../docs/reference/examples.md))。

| | |
|---|---|
| 対象 | [github.com/Dimillian/IceCubesApp](https://github.com/Dimillian/IceCubesApp) (commit `98098b9`) |
| プロファイル | `ui-ios` |
| 入口の一覧 | 102 件 (承認済み 3 件、候補のまま 99 件) |
| 分析結果とレビュー | 3 件ずつ (承認済みの入口だけ) |

対象のコードは入っていません。分析結果が持つのは、ファイルのパスと行番号、処理の要約、読み書きするデータの名前です。

## 入っている分析結果

| 入口の id | 何の入口か | 処理の段 | 読み書き |
|---|---|---|---|
| `SheetDestination.addTagGroup` | タグのグループを足すシート | 5 | 2 |
| `shell_s.delegate.AppDelegate` | アプリの起動 | 34 | 14 |
| `system_s.widget.LatestPostsWidget` | ホーム画面のウィジェット | 16 | 7 |

見どころ:

- 画面、アプリの起動、OS から呼ばれる入口 (ウィジェットなど) を、別々の入口にしている

## 使い方

**このディレクトリを as-built-atlas の checkout の外へコピーし、隣に対象を clone する** (`abatlas init` が git リポジトリとして初期化し、設定を書き足すため)。

```bash
mkdir -p ~/abatlas-try && cp -r examples/icecubes-atlas ~/abatlas-try/
cd ~/abatlas-try
git clone https://github.com/Dimillian/IceCubesApp.git IceCubesApp
git -C IceCubesApp checkout 98098b9c4b5928f89f338203193c2bf40ab7f38c   # 分析結果の根拠の行は、この版のもの
cd icecubes-atlas

# 分析リポジトリとして初期化 (既にある .env と analysis/ は、そのまま)
docker run --rm -v "$PWD:/ws/analysis" -w /ws/analysis ghcr.io/suwa-sh/as-built-atlas:latest init . --profile ui-ios

docker compose run --rm abatlas validate result analysis/results/SheetDestination.addTagGroup.yaml --work analysis/work-definition.yaml   # 根拠の行が、clone した対象に実在すること
docker compose run --rm abatlas build .        # ETL → dbt build
docker compose up -d api                        # 画面 http://localhost:8765  /  MCP http://localhost:8765/mcp
```

## 分析結果についての注意

- 分析結果は AI が書いたもので、人が 1 件ずつ読んで確かめてはいません。機械チェック (形式、根拠のファイルと行の実在) と、AI によるレビューは通っています。使ったモデルは、結果ごとの `analyzer.model` に書いてあります (`claude-opus-5-5`)
- レビューの指摘は、すべて直した印 (`resolved`) が付いています。確かめられなかった読み書きが 1 件あります (理由付き)
- 分析したのは、入口の一部 (3 件) です。残りの 99 件は、抽出器が見つけた候補のままで、承認も分析もしていません。プロファイルの書き方を見せるための見本で、対象の全体の地図ではありません
- Ice Cubes は開発元の著作物で、GNU Affero General Public License v3.0 です。この見本は対象の公式の文書ではなく、対象の開発元とは関係ありません。
- 対象の版が変わると、根拠の行番号はずれます。別の版を分析するときは、作業定義の `commit` を変えて分析し直します
