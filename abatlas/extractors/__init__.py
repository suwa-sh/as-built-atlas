"""コア同梱の汎用抽出器。

契約 (どの抽出器も同じ):
- 引数: --scope <分析範囲のディレクトリ> --params <JSON 文字列 or @ファイル> --layer <層 id>
- 標準出力: schema/entry-candidate.schema.json に従う JSON を 1 行 1 件 (JSON Lines)
- 標準エラー: ログ (自由形式)
- 終了コード: 0 = 成功 / それ以外 = 失敗 (列挙ツールは止める)
"""
