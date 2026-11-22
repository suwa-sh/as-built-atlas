# docs

人とコーディングエージェントが共有する knowledge の索引です。ここから各カテゴリの README を経由して、すべての共有文書へ辿れる状態を保ちます。

| カテゴリ | 内容 |
|---|---|
| [brand.md](brand.md) | コンセプト (一言・価値提案・5 つのメッセージ)、名前の由来、声と見た目 |
| [guide/](guide/README.md) | 使う人の手引き。人が何をすると何が手に入るか、その途中でどの skill とコマンドが動くか。場面ごとの手順 (初めて分析する、結果を読む、対象が進んだら更新する、プロファイルを合わせる、個人情報の列を洗い出す、配布物を新しくする、精度を測る) |
| [reference/](reference/README.md) | 仕様。コマンド、作業定義、分析結果の形式、集計表、API と MCP、プロファイル、公開サンプル |
| [architecture/](architecture/README.md) | 仕組みの説明 (いま動くものの期待状態)。全体像、登場人物、設計の考え方、残るものと作り直すもの、仕組みに入れていないもの。主題ごとの文書: 分析リポジトリと配布物、データの流れ、webapp |
| [../DESIGN.md](../DESIGN.md) | webapp の見た目の決まり |
| [../examples/kotori-books/](../examples/kotori-books/README.md) | 公開サンプル (架空の書店のバッチ) の構成と、正解 YAML に入れてある「不明」の見どころ |
| [rules/](rules/README.md) | 開発で守ること。共通のルール (進め方、品質ゲート、レビュー、知識の残し方) と、部分ごとのルール (形式、ツール、集計表、画面、プロファイル、見本、文書) |
| [adr/](adr/README.md) | 決定の経緯 (背景、決定、捨てた案、結果)。いま守ることは、guide、architecture、reference、rules のうち、読み手の問いに合う置き場に書く (分け方は [rules/docs.md](rules/docs.md)) |
| [troubleshooting/](troubleshooting/README.md) | 障害対応、診断、復旧、再発防止 |

| 置き場 | 書くこと | 読み手 |
|---|---|---|
| `docs/adr/` | 決定の経緯 | 人とエージェント |
| `docs/` の ADR 以外 | 守るべき最新の状態 | 人とエージェント |
| `.agents/memory/` | 作業中に得た、今後の作業でも理解しておくべきこと | エージェントだけ |

エージェント専用の knowledge (`.agents/memory/`) はこの索引に含めません (一方向参照)。
