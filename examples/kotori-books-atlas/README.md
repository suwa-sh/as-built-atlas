# kotori-books-atlas (分析リポジトリの見本)

隣の `kotori-books/` (架空のオンライン書店のバッチ) を as-built-atlas で分析した状態の、分析リポジトリの資産です。

- `analysis/work-definition.yaml` 対象と範囲。`commit` は対象ディレクトリの内容ハッシュ (対象はこのリポジトリの一部で、独立した git 履歴を持たない)
- `analysis/entry-list.yaml` 入口 34 件 (すべて承認済み)。`abatlas enumerate` の出力そのもの
- `analysis/results/*.yaml` 入口ごとの分析結果 = **正解**。対象と同じ仕様から生成したので、自分のエージェントの分析結果を `abatlas evaluate` で突き合わせる基準になる
- `.env` `ABATLAS_TARGET=../kotori-books`

**使うときは、この 2 つのディレクトリを as-built-atlas の checkout の外へ並べてコピーする** (`abatlas init` が git リポジトリとして初期化し、
中ハーネスと製品別の設定を書き足すため)。手順は as-built-atlas の README。
