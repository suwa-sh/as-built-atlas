# 作業定義に書くこと

[← 仕様の地図へ](README.md)

作業定義 (`analysis/work-definition.yaml`) の項目です。形式の正本は `schema/work-definition.schema.json` です。

| 項目 | 必須 | 内容 |
|---|---|---|
| `format_version` | ○ | 形式の版。`1` を書く |
| `target.repo` | ○ | 対象の識別 (URL か名前) |
| `target.name` | | 画面の見出しとタブに出す名前。省略すると、`repo` の最後の区切りより後ろ |
| `target.clone_path` | | 対象の clone の場所。相対なら分析リポジトリのルートから |
| `target.scope` | | clone の中で分析する範囲 (モノレポの一部だけを対象にするとき)。既定は `.` |
| `target.commit` | ○ | 対象のコミット。列挙と分析は、このコミットで行う |
| `profile.id` | ○ | プロファイルの id |
| `profile.dir` | | プロファイルの置き場所。[profiles.md](profiles.md) の「ツールが読むプロファイル」 |
| `analysis.tests` | | `true` にすると、処理の段を通るテストも分析する。範囲 (`target.scope`) にテストのコードが入っているときだけ使う。既定は `false` |
| `analysis.entry_file_patterns` | | 入口を定義するファイルの規則。`target.scope` からの相対パス全体に照合する、Python の正規表現の並び。書くと、入口の列挙を、定義ファイルと照合できる ([update-commands.md](update-commands.md) の「入口の定義ファイルを先に確かめる」) |
| `analysis.models.analyze` | | 入口を分析するサブエージェントのモデル。書いてなければ、起動する側の既定 (多くの製品では、起動した側と同じモデル) で動く |
| `analysis.models.review` | | 分析結果をレビューするサブエージェントのモデル。同上 |

入口が多いときは、`analysis.models` を書いておきます。書かなかった役のサブエージェントは、使っているコーディングエージェントの既定のモデルで動きます。多くの製品では、起動した側と同じ (いちばん高いことが多い) モデルになり、費用がかさみ、利用の上限にも当たりやすくなります。分析のモデル (`analyze`) を書いていないと、複数の入口を分析する前に、エージェントが今回使うモデルを人に確かめます。値は、使っているコーディングエージェントが受け付けるモデルの名前です。実際に使ったモデルは、結果ごとの `analyzer.model` に残ります。
