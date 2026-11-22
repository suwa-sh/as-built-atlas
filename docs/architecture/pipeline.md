# データの流れと集計表

[← architecture の地図へ](README.md)

対象のコードから、画面と MCP が読む集計表 (mart) ができるまでの流れです。

## 流れ

```mermaid
flowchart TB
  T[対象の clone] --> I
  I["init<br>配布物と、エージェントの設定を置く"] --> M
  M["code-map<br>固定コミットのファイルを並べる"] --> D
  D["入口を見つける (エージェント)<br>抽出器とパラメータを entry-list.yaml に書く。<br>抽出器で取れない入口は、読んで足す"] --> E
  E["enumerate (ツール)<br>抽出器を実行し、入口の候補を出す"] --> H
  H["全体の承認 (人)<br>入口と今回の作業を確定"] --> A
  A["分析 (エージェント)<br>入口ごとに results/ に YAML を書く"] --> V
  V["validate result (ツール)<br>形式と意味を検査する"] --> RV
  RV["レビュー (別の文脈のエージェント)<br>reviews/ に指摘を書く"] --> B
  B["build (ツール)<br>YAML → 表 → 集計表 → DuckDB"] --> S
  S["serve (ツール)<br>API、MCP、webapp"]
  H -.->|漏れや誤りがあれば、拾い方を直す| D
  V -.->|通らなければ直す| A
  RV -.->|指摘があれば直す| A
```

| 段 | 誰が | 入力 | 出力 |
|---|---|---|---|
| init | ツール | プロファイルの id | OSS 所有のファイル、作業定義のひな形、エージェントの設定 (6 製品分) |
| code-map | ツール | 作業定義、対象 Git | ファイルの一覧。定義ファイルの規則を指定すると、承認前に入口と[照合](impact.md)する |
| 入口を見つける | エージェント (入口発見 skill) | 対象のコード | `entry-list.yaml` の `extractors`。抽出器で取れない入口は、根拠と理由を付けて、`listed` 抽出器の設定に書く |
| enumerate | ツール | `extractors` | `entries` (`status: candidate`)。抽出器の出力は形式を検査する |
| 全体の承認 | 人 | AI が準備した入口・作業案と要確認への回答 | `entry-list.yaml` の入口の状態と `approval`。取りまとめ役が入口ごとに実行する |
| 分析 | エージェント (分析 skill) | 承認済みの入口、`.agents/memory` の癖 | `results/<file>` |
| validate result | ツール | 分析結果 | 指摘。形式に加えて、層・呼び出し元・不明の理由・根拠の実在を見る |
| レビュー | エージェント (レビュー skill) | 分析結果 | `reviews/<file>`。形式を検査する |
| build | ツール | `results/`、`entry-list.yaml`、プロファイル | `analysis/data/abatlas.duckdb` |
| serve | ツール | DuckDB | API、MCP (`/mcp`)、webapp (`/`) |

入口を列挙する主体は、エージェントです。抽出器は、その土台です。抽出器が取れた入口も、エージェントが足した入口も、同じ `entries` に並び、人が承認します。エージェントが足した入口には、印 (`attributes.listed_by: agent`) と理由が付きます ([profiles.md](profiles.md) の「抽出器の契約」)。

分析にかかった費用と時間 (`analyzer.run`) は、エージェントを呼び出した側が後から追記します。分析 skill は書きません ([formats.md](formats.md) の「来歴」)。

## build の中身

集計は、分析結果を、検査のコマンド (`validate result`) と同じ検査に通してから始めます (形式、呼び出しの木、語彙、列、プロファイルの層との突き合わせ)。1 件でも通らなければ、何も書かずに止まります。検査で落ちる結果が、集計には通る、ということが無いようにするためです。検査のコマンドとの違いは 2 つです。根拠のファイルの実在と行数は、対象の clone が読めるときだけ見ます (読めない場所でも、集計は動かせます)。有効な[再利用の確認記録](impact.md)がなく、対象 (リポジトリ、範囲、コミット) が作業定義と違う結果は、止めずに知らせます (対象を更新した後、入口を 1 件ずつ分析し直す間も、集計して画面で見られるようにするためです)。

```mermaid
flowchart LR
  subgraph SRC[dbt プロジェクトの合成]
    C[core のテンプレート<br>イメージの中]
    PF[プロファイルのテンプレート]
    RP[独自の集計表<br>analysis/dbt/models/repo]
  end
  C --> W[analysis/data/dbt/<br>作業用の dbt プロジェクト]
  PF --> W
  RP --> W
  Y[results/ と entry-list.yaml] -->|ETL| SD[seeds/*.csv]
  SD --> W
  W -->|dbt build| N[新しい DuckDB<br>別ファイル]
  N -->|宣言を検査| K{通ったか}
  K -->|はい| X[宣言と meta を書いて<br>ファイルを入れ替える]
  K -->|いいえ| Z[入れ替えない<br>前の版が残る]
```

| 決まり | 理由 |
|---|---|
| ETL は決定論 (同じ入力なら同じ CSV) | 再現できる処理はツールが行う |
| DuckDB は別ファイルに作ってから入れ替える | API が読んでいる最中でも壊れない |
| 宣言の検査に通らなければ入れ替えない | 画面と MCP に、読めない宣言を出さない |
| 一部だけ build しても (`--select`)、宣言はすべて検査する | 選ばなかった表も、引き継いだ DuckDB の中にある |
| 読んだプロファイルを検査する | [profiles.md](profiles.md) の「ツールが読むプロファイル」 |

`POST /recompute` (画面の「mart を rebuild」) も、同じ build をやり直します。

## 集計表の 3 層

| 持ち主 (`origin`) | 置き場 | 合成先 (派生物) | 直す人 |
|---|---|---|---|
| core | イメージの `dbt-template/models/core/` | `analysis/data/dbt/models/core/` | OSS |
| profile | イメージの `profiles/<id>/dbt-template/models/profile/`。作業定義の `profile.dir` に `dbt-template/` があれば、そちら | `analysis/data/dbt/models/profile/` | OSS (写したプロファイルなら分析リポジトリ) |
| repo | `analysis/dbt/models/repo/` | `analysis/data/dbt/models/repo/` | 分析リポジトリ |

分析リポジトリには core と profile のモデルを置きません。配布物との版のずれを気にする対象は、`analysis/dbt/models/repo/` だけです。

## 同じ木の繰り返し

分析結果は、入口 1 件 = 1 つの木です。同じ処理が、木の中や、入口の間で繰り返されることがあります。集計は、次の 2 つを行います。

| 繰り返し | 起きること | 集計の扱い |
|---|---|---|
| 同じ入口の中で、同じ処理を、もう一度書いたフレーム (分析の決まりで、呼び出し元を終端にしないために書く写しと、呼び出し元によって開く枝が違うときに書く写し) | 写しの読み書きを数えると、同じ読み書きを 2 回数える | 読み書きの行に印 (`stg_io` と `stg_io_fields` の `is_repeat`) を付け、箇所の数 (入口の概要、読み書きの表、列の読み書き、層のつながり、状態の変化) から除く。行そのものは残す (経路の表示に使う)。除くのは箇所の数だけで、不明の印と、列の使い方は、写しの分も合わせる |
| 多くの入口が通る、大きな処理 (多くの画面が描く部品など) | 入口の数だけ、同じ木が分析結果に書かれる。分析の費用が増え、入口ごとに書き方が割れる | 候補を出す (`mart_split_candidates`)。出すのは、プロファイルが、別の入口に分けられると決めた層 (`profile.yaml` の `split_from`) の処理だけ。その部品を別の入口に分けるかは、人が決める ([profiles.md](profiles.md) の「`ui-nextjs` の決まり」、経緯は ADR 0014 と 0016) |

`is_repeat` の判定は、決定論です: 定義の場所 (ファイルと行)・名前・層が同じフレームのうち、入口の中で、より前のフレームに、同じ相手 (種類とパス) への同じ操作がある読み書き (最初のフレームに読み書きが無く、後の 2 つに同じ読み書きがあるときは、後ろの 1 つだけが当たる)。引数で届く先が変わる処理を、届く先ごとに書いたとき (相手が違う) は、当たりません。

## コアの集計表

| 集計表 | 表示の種類 | 内容 |
|---|---|---|
| `mart_layer_flow` | 層の図 | 層のつながり。呼び出しと読み書きを、層の単位に集めたもの |
| `mart_entry_overview` | 表 | 入口ごとの概要。分析済みか、処理の段の数、読み書きの数、事実 / 解釈 / 不明の件数、実行の記録、古い版のプロファイルで分析したか (`profile_stale`) |
| `mart_entry_complexity` | 表 | 入口ごとの複雑度。分析済みの入口だけ。1 つの点数にまとめず、数を並べる (下の「複雑度」) |
| `mart_progress` | 指標 | 階層の第 1 段ごとの、入口の数 / 承認済み / 分析済み。実行の記録があれば、実績の費用と残りの見積もり |
| `mart_quality_unknowns` | 表 | 不明の主張を、理由別に数える |
| `mart_data_access` | 行列 | 読み書きするデータ。入口の階層 × データの階層 |
| `mart_dataflow` | 有向グラフ | 読むデータ → 入口 → 書くデータ |
| `mart_callstack` | ツリー | 入口ごとの処理の段と、親子関係 |
| `mart_sequence` | シーケンス | 入口ごとに、呼び出しと読み書きを順に並べたもの |
| `mart_external_if` | 表 | 外部 API のホストごとに、呼んでいる入口 |
| `mart_shared_frames` | 表 | 2 件以上の入口から呼ばれる同じ処理 |
| `mart_entry_within` | 表 | 入口を包む入口。1 行 = 包まれる入口 × 包む入口 |
| `mart_field_access` | 表 | 列の単位の読み書き。入口 × データ × 列ごとに、使い方 (R = 読む、W = 書く、F = 絞り込みに使う) |
| `mart_state_changes` | 表 | 状態の変化。決まった値を書く列ごとに、その値と、書く入口と処理 |
| `mart_entry_links` | 表 | 入口から、ほかの入口へのつながり。行き先が入口の一覧と結べたかも持つ |
| `mart_entry_access` | 表 | 入口ごとの権限のまとめ。認証の確認があるか、求める役割と権限 |
| `mart_entry_guards` | 表 | 権限の確認の一覧。1 行 = 確認 1 つ (それを行う入口と処理)。入口を包む入口の確認は、中で動く入口の数を添える |
| `mart_call_conditions` | 表 | いつも起きるとは限らない呼び出し (条件つき、失敗のときだけ) と、その条件 |
| `mart_settings` | 表 | 設定への依存。設定 × 入口ごとに、使う処理と、動きへの影響 |
| `mart_rules` | 表 | 業務のルールの一覧。内容と、根拠の場所 |
| `mart_test_coverage` | 表 | 処理ごとの、それを直接呼ぶテストの数と名前。テストとの対応を分析した結果だけ |
| `mart_sensitive_data` | 表 | 個人情報などの流れ。データの辞書で承認した列を使う入口と、同じ入口が呼ぶ外部の接続先 |
| `mart_data_links` | 3 列のつながり | データを介したつながり。同じデータを、書く入口と読む入口が別にあるもの (キューやテーブルやファイルを介して動く入口) |
| `mart_unreached_files` | 表 | どの入口からも辿られないファイル。対象の範囲にあって、分析結果のどこにも出てこないもの |
| `mart_guard_map` | 数の表 | 入口 × 権限の確認の種類。その入口に効く確認の数 (包む入口の分を含む)。認証の確認が無い入口に、印が付く |
| `mart_behavior_map` | 数の表 | 入口 × 動きを変える物の種類 (条件つきの呼び出し、業務のルールの種類、設定)。数の多い入口が分かる |
| `mart_setting_spread` | 数の表 | 設定 × 入口の階層の最初の段。その設定に動きを左右される入口の数 |
| `mart_entry_link_hubs` | 3 列のつながり | 入口どうしのつながりを、入口 1 件を真ん中にして見る。そこへ来る入口と、そこから行く入口 |
| `mart_unreached_dirs` | ツリー | どの入口からも辿られないファイルを、フォルダごとに数えたもの |
| `mart_split_candidates` | 表 | 別の入口に分ける候補。3 件以上の入口が通り、下に 10 以上の処理の段を持つ処理を、繰り返されている段の多い順に出す。プロファイルが、別の入口に分けられると決めた層の処理だけを出す (決めていないプロファイルでは、何も出ない)。分析の状態のページに出る (下の「同じ木の繰り返し」) |

補足です。

| 集計表 | 補足 |
|---|---|
| `mart_layer_flow` | 行 = 呼ぶ側の層 → 呼ばれる側の層、または 層 → `/` + データの種類。`calls` = 箇所の数、`entries` = 入口の数、`unknowns` = 確かめられていない箇所の数。`unknowns` が 1 つでもあれば `status` = unknown で、図では点線。区分 (`subject`) を持たず、構成のページが表示の種類 (`view: layers`) で引く。集計表のページも同じ図を出す |
| `mart_data_access` | `kind` 列が種類。`ops` は、種類ごとの操作の 1 文字を語彙の並び順に連ねたもの (RDB なら C / R / U / D、ファイルなら R / W / A / D / L) |
| `mart_dataflow` | 向きは語彙の `direction` (in = 読む側、out = 書く側) |
| `mart_entry_within` | `ord` が外側からの順。入口の一覧の `within` から作る。包む関係を持たないプロファイルでは 0 行 |

### 足した観点の集計表

`mart_field_access` から `mart_sensitive_data` までの 10 個は、分析結果の観点 ([formats.md](formats.md)) から作ります。`mart_data_links` は、読み書きの向きから作ります。`mart_unreached_files` は、対象の範囲にあるファイルと、分析結果を突き合わせて作ります。

| 決まり | 内容 |
|---|---|
| 置き場 | 区分は、分析の観点 (`subject: aspect`)。分析の観点のページに、タブで 1 つずつ出る。入口のページでは、その入口に絞ったタブとして出る (入口の列を持たない `mart_unreached_files` は、出ない) |
| 前の版の結果 | 観点を書く前の版 (分析の skill が 0.4.0 より前) の結果は、その項目を持たないので、これらの表に自分の行を出さない。`mart_entry_access` は、観点を分析した結果だけを 1 行ずつ出すので、「分析していない」と「確認が無い」を区別できる |
| 確かめられなかったテスト | `status` が `unknown` のテストは、`mart_test_coverage` の数と名前に入れない。数は `unknown_test_count` に出す |
| 確かめられなかった確認 | `status` が `unknown` の確認は、`mart_entry_access` の `authentication` に数えず、求める役割と権限にも並べない。数は `unknown_guard_count` に出す |
| 包む入口の確認 | 入口を包む入口 (枠) の確認は、中で動く入口にも効く。`mart_entry_guards` は、確認を行う入口の行だけを出し、中で動く入口の数 (`inner_entry_count`) を添える (はじめは、中で動く入口の数だけ行を増やしていたが、実物で 800 行を超えた)。入口ごとの効き方は、`mart_entry_access` が、包む入口の確認も合わせて出す。包む入口がまだ分析されていないと数えられないので、`enclosing_not_analyzed` で分かるようにしている |
| 全部の列 | 列が `*` の読み書きは、`mart_sensitive_data` では、そのデータの、辞書にある列すべてを使うものとして数える |
| データを介したつながり | `mart_data_links` は、読み書きの向きだけから作る。書く入口と読む入口が同じデータに触れる、ということだけを出し、同じ行を受け渡しているかまでは追っていない。呼び出しや遷移のつながり (`mart_entry_links`) とは別の表 |
| 辿られないファイル | `mart_unreached_files` は、集計のときに対象の clone を読んで、範囲にあるファイルを並べる (git の管理下なら、管理されているファイルだけ)。対象が読めない場所で集計すると、空になる。分析していない入口が残っている間は、そこからだけ辿られるファイルも出るので、使われていないものの候補と、分析が届いていない範囲が混ざる。テーブルや列の単位では、見ていない |
| 個人情報の流れの粗さ | `mart_sensitive_data` の外部の接続先は、「同じ入口が呼ぶもの」。その列の値が実際に送られるかは、追っていない |

### 複雑度

使い道は、直すときの影響の見積もりです。数に重みを付けて 1 つの点数にすることは、していません (重みの根拠が無いため)。並びは、直すときに一緒に確かめるものが多い順です。

| 列 | 数えるもの |
|---|---|
| `sharing_entry_count` | 同じ処理 (2 件以上の入口が通る処理) を通る、ほかの入口の数。その処理を直すと、一緒に確かめることになる |
| `shared_frame_count` | この入口が通る処理のうち、2 件以上の入口が通るものの数 |
| `written_datastore_count` | 書き込むデータの数 (同じデータは 1 回だけ数える) |
| `datastore_count` | 読み書きするデータの数 (外部の接続先は含めない) |
| `external_count` | 外部の接続先の数 (ホストとパスの組) |
| `frame_count` | 処理の段の数 |
| `max_depth` | 入口から、いちばん深い処理までの段の数 |
| `layer_crossings` | 呼び出し元と層が違う呼び出しの数 |
| `branch_count` | 条件つきの呼び出しの数 (分岐) |
| `failure_path_count` | 失敗のときだけの呼び出しの数 |
| `unknown_count` | 確かめられなかった主張の数 |

`branch_count` と `failure_path_count` は、呼び出しの条件 (`call.when`) から数えます。この観点を書く前の版の結果では、どちらも 0 です。画面の表に出す列は 9 つまでにしています (増やすと、右端が切れます)。`layer_crossings`、`failure_path_count`、`unknown_count` は、表には出さず、API で読めます。

## 集計表の宣言

**コードは集計表の名前を知りません。** 集計表は、dbt のモデルの `meta.abatlas` に宣言を書きます。画面と API と MCP は、宣言だけを読んで動きます。

```mermaid
flowchart LR
  S[schema.yml の<br>meta.abatlas] -->|build が検査| D[(DuckDB の<br>meta.declarations)]
  D --> A[API]
  A --> W[webapp<br>宣言から画面を組む]
  A --> M[MCP]
```

宣言と集計表が同じファイルにあるので、公開はファイルの入れ替え 1 回で済み、新旧が混ざりません。dbt の作業先の manifest は、失敗した build でも書き換わるので、API は読みません。

| 項目 | 必須 | 内容 |
|---|---|---|
| `origin` | ○ | 集計表の持ち主: `core` / `profile` / `repo` |
| `view` | ○ | 表示の種類 (下の表) |
| `level` | ○ | `entry` / `path` |
| `subject` | | 何についての表か: `entry` / `data` / `external` / `frame` / `aspect` / `analysis`。画面のメニューの項目になる |
| `topic` | | `subject: aspect` の表が答える問いの組: `access` (権限) / `data_detail` (データの細部) / `links` (つながり) / `behavior` (動きを変える物) / `coverage` (分析の届く範囲)。観点のページは、組ごとに表をまとめる。無い表は「そのほか」に出る |
| `rollup` | | 物ごとのまとめ方 (下の「物ごとのまとめ」) |
| `title` | | 論理名 (画面の見出し) |
| `hint` | | 読み方の 1 行 |
| `attach` | | 入口の画面のどの段に貼るか: `any` / `root` / `level1`〜`level5` |
| `tags` | | `monitor` = 分析の状態の画面に載る。`within` = 「入口を包む入口」の表の印 |
| `keys` | ○ | 表示の種類ごとの、列の対応 |
| `show` | | 一覧に出す列の並び |
| `labels` | | 列の表示名 |
| `filters` | | 一覧の絞り込みの候補 (`{label, where}`) |

表示の種類 (`view`) は 9 つです。必須と任意の `keys` の正本は、`dbt-template/models/core/schema.yml` の冒頭と、`abatlas/declarations.py` の `VIEWS` です。

| `view` | 描くもの | 任意で持てる `keys` の例 |
|---|---|---|
| `table` | 表 | `label` / `summary` / `members` / `order` / `source` |
| `matrix` | 行列 (開閉できる表) | `kind` (`subject: data` では必須) |
| `graph` | 有向グラフ | `label` / `status` / `path` |
| `layers` | 層の図。層どうしのつながりの表だけが使う | `label` / `status` |
| `sequence` | シーケンス | `node` / `evidence` |
| `tree` | ツリー | `source` / `tag` / `value` (数の列。あれば、棒と数を出し、子を畳んで出す) |
| `stat` | 指標 | — |
| `heat` | 数の表。行と列の値の組ごとに、数を 1 つ出す (階層で畳まない) | `flag` (真なら、注意して見るセル) / `order` (列の並び順) |
| `bridge` | 3 列のつながり。真ん中の物 (`id`) と、左右につながる入口 (`left` / `right`。パスを `", "` で連ねた列) | `label` / `kind` |

### 物ごとのまとめ (`rollup`)

入口をまたいで見る表は、同じ物が、入口の数だけ行になります (見本の umami では、列の読み書きの 5,103 行が、501 個の列の話でした)。`rollup` を宣言すると、観点のページは、行の一覧の代わりに「1 つの物 = 1 行」のまとめを先に出します。行の一覧にも、切り替えられます。

| 項目 | 内容 |
|---|---|
| `by` | まとめる列 (1〜3 段)。左の列でまとめ、開くと次の列でまとめ、最後に行の一覧 |
| `member` | 数える列。ふつうは、入口のパス |
| `flag` | 任意。真偽の列。真の `member` を、別に数える (例: 書く入口) |
| `chip` | 任意。相異なる値を、札で並べる列 (例: 状態の値) |

数えるのは、API の `groups` です ([api.md](api.md))。画面は、全行を読みません。

集計のときの検査は、列の型も見ます: `rollup.flag` は真偽の列、`heat` の `value` と `order`、`tree` の `value` は数の列。

`tags: within` の表は、入口の詳細の画面が次のように引きます。この表は `subject` を持ちません (入口の一覧の表と取り違えず、メニューにも出さないため)。

| `keys` | 意味 |
|---|---|
| `path` | 包まれる入口 |
| `members` | 包む入口 (1 行に 1 つ) |
| `order` | 外側からの順 |

build は、次を検査します。合わなければ、DuckDB を入れ替えません。

| 検査 | 内容 |
|---|---|
| 形式 | 宣言の項目と値が、決まりに合う |
| 列の実在 | `keys` / `show` / `labels` / `filters` の列が、集計表にある |
| 持ち主と置き場所 | `origin` が、定義の置き場所 (`models/core/`、`models/profile/`、`models/repo/`) と合う。例: 分析リポジトリの独自の集計表 (`models/repo/`) に `origin: core` と書くと、指摘される |
| 呼び名 | 宣言の文字の `"{id}"` が、用語集にある |

## meta (プロファイルと語彙)

build は、宣言と一緒に次の 4 つを DuckDB の `meta.atlas` に書きます。画面は `GET /meta` で読みます。

| キー | 内容 | 画面での使い道 |
|---|---|---|
| `profile` | プロファイルの id / version / label / `hierarchy` / `layers` | メニューの概念名、構成の図、入口の種類の札 |
| `resource_kinds` | データの種類の語彙 (`schema/vocab/resource-kinds.yaml`)。段の名前、操作の 1 文字、向き | データの階層、表の凡例 |
| `terms` | 用語集 (`schema/vocab/terms.yaml`)。概念の id → 呼び名 | 画面に出すすべての呼び名 |
| `target` | 分析対象の `name` / `repo` / `commit` | メニューの見出し、タブ、フッター |

`GET /meta` は、今の配布物の用語集にあって、この集計表に入っていない id があれば、`missing_terms` に並べて返します (配布物を新しくして、集計し直していない)。画面は、用語集が無いとき・`missing_terms` があるときに、集計し直すよう促して止まります (呼び名の代わりに、id を出さないため)。

`target.name` は、作業定義の `target.name` です。無ければ、`repo` の最後の区切りより後ろ (末尾の `.git` は除く) です。

### 層の並び (`layers`)

`layers` は、画面に要る項目だけを出します: `id` / `label` / `role` / `tier` / `stack` / `invokes_next`。

| 項目 | 意味 |
|---|---|
| `tier` | 層をまとめる区分の名前 (例: frontend / backend)。任意。「どこで動くか」ではない |
| `role` | `entry` = 入口の層、`boundary` = 外との境の層 |

構成のページ (`#/overview`。最初に開くページ) は、層を箱にして区分の枠に入れ、`view: layers` の表の行を線にして描きます。

| 図の部品 | 何から作るか |
|---|---|
| 箱と枠 | プロファイルの `layers` (`tier` が枠) |
| 線 | `view: layers` の表の行。`from` = 層の id、`to` = 層の id か `/` + データの種類、`label` = 箇所の数 |
| 箱の中の処理の数 | `subject: entry` の tree を、`keys.tag` で数える |

線は、分析結果にある実際の呼び出しと読み書きです。途中の層を飛ばす呼び出しも線になります。処理が 0 件の層は、箱を薄く描きます (プロファイルにはあるが、この対象では使われていない層)。

`layers` が無い集計表 (古い build) では、メニューに構成を出さず、入口のページから始まります。

### 入口の階層 (`hierarchy`)

| 項目 | 内容 |
|---|---|
| `level_labels` | 階層の段の名前。画面のメニューの概念名 (例: namespace › flow) になる |
| `notes` | 段の名前の読み方 (`text` と、任意の `contains`) |
| `entry_labels` | 入口の種類ごとの呼び名 (`contains` と `label`) |

`level_labels` の決まりです。

- `名前+` は、深さが可変の段です (例: `[namespace+, flow]`)。
- `+` は 1 つまでです。その後ろに置ける段も 1 つまでです。
- 繰り返しの段の下では、画面は葉だけを末尾の名前で呼びます (節の深さが決まらないため)。

`notes` は、対象のシステムの書き方が段の名前に残るときに使います (例: Next.js の動的な段 `[id]`)。

| 画面 | 出す `notes` |
|---|---|
| 入口の階層のページ | すべて |
| 入口の詳細のページ | `contains` を持たないものと、パスが `contains` の文字列を含むもの |

`entry_labels` は、階層を分けて別の種類の入口を並べるときに使います (例: 画面 page と、画面を包む枠 layout)。入口の種類の札、一覧の「種類」の列、路線の色は、次の順で決まります。

1. パスが `contains` を含む、最初の `entry_labels` の `label`。
2. 無ければ、`level_labels` から、入口の深さで決まる名前。

| `level_labels` | 形 | 入口の深さ | 種類の名前 |
|---|---|---|---|
| `[section+, page]` | 繰り返す段の後ろに段がある | どの深さでも | `page` |
| `[group, job]` | `+` が無い | 1 | `group` |
| `[group, job]` | `+` が無い | 2 | `job` |

## 画面に出す呼び名 (用語集)

**画面に出す呼び名は、用語集で決めます。** 概念 1 つに呼び名 1 つで、技術用語は英語のまま書きます (例: `entry` → entry point、`frame` → function)。

```mermaid
flowchart LR
  T[terms.yaml<br>id → 呼び名] --> B[build]
  D["宣言・プロファイル・語彙の文字<br>{id} と書く"] --> B
  B -->|置き換えて配る| M["/meta と /marts"]
  T -->|terms| M
  M --> W["webapp<br>term('id') で引く"]
```

| 書く場所 | 書き方 |
|---|---|
| 宣言の文字 (`title` / `hint` / `labels` / `filters` の `label`、モデルの `description`) | `"{<id>}"`。build が、配る前に呼び名へ置き換える |
| プロファイルの表示項目 (`label`、`layers` の `label` / `tier`、`hierarchy.notes` の `text`) | 同上 |
| データの種類の語彙 (種類と操作の `label`) | 用語集にある呼び名は `"{<id>}"` で引く |
| core の `title` と `labels` | `"{<id>}"` と、記号・単位だけで組む |
| webapp | `/meta` の `terms` を `term("<id>")` で引く。呼び名を直接書かない |

- 用語集に無い id は、宣言の検査が指摘します (`description` も見ます)。
- 文字どおりの `{id}` を出したいときは、`\{id}` と書きます。
- `tests/test_terms.py` が、使わなくなった呼び名 (用語集の `retired`) が残っていないことと、参照する id が用語集にあることを検査します。
