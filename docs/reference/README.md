# 仕様

as-built-atlas の正確な仕様です。
項目、コマンド、集計表、プロファイルごとの決まりを、引いて調べるための文書を置きます。

手順は [手引き](../guide/README.md) に、仕組みの理由は [仕組みの説明](../architecture/README.md) にあります。

## 知りたいことから、文書を選ぶ

| 知りたいこと | 文書 |
|---|---|
| 分析リポジトリで使うコマンドの一覧、分析結果の差分 (`diff`) に出るもの | [commands.md](commands.md) |
| 入口の定義ファイルとの照合 (`code-map`)、一括の承認 (`propose`、`approve`、`queue`)、対象の差分からの作業の一覧 (`impact`)、再利用の確定 (`reuse`) | [update-commands.md](update-commands.md) |
| 作業定義 (`analysis/work-definition.yaml`) の項目 | [work-definition.md](work-definition.md) |
| 分析結果の形式 (主張、処理の段、読み書き、根拠、来歴)、データの辞書 | [formats.md](formats.md) |
| 集計表の一覧、集計表の宣言、meta、画面に出す呼び名 | [marts.md](marts.md) |
| 集計表 API と MCP | [api.md](api.md) |
| プロファイルの中身、ツールが読むプロファイル、抽出器の契約、入口を包む入口 | [profiles.md](profiles.md) |
| プロファイルごとの、入口と層の決まり | [profiles.md](profiles.md) の「プロファイルごとの決まり」から選ぶ |
| 公開サンプルの一覧とライセンス、分析結果の突き合わせ (`evaluate`) の数え方 | [examples.md](examples.md) |

言葉の定義 (入口、層、区分、処理の段など) は、[仕組みの説明](../architecture/README.md) の「言葉」にあります。
