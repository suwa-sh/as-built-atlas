# データの流れと集計表

[← architecture の地図へ](README.md)

対象のコードから、画面と MCP が読む集計表 (mart) ができるまでの流れです。

## 流れ

```mermaid
flowchart TB
  T[対象の clone] --> I
  I["init<br>配布物と、エージェントの設定を置く"] --> D
  D["入口のパターンを決める (エージェント)<br>抽出器とパラメータを entry-list.yaml に書く"] --> E
  E["enumerate (ツール)<br>抽出器を実行し、入口の候補を出す"] --> H
  H["承認 (人)<br>status を approved / rejected にする"] --> A
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
| 入口のパターンを決める | エージェント (入口発見 skill) | 対象のコード | `entry-list.yaml` の `extractors` |
| enumerate | ツール | `extractors` | `entries` (`status: candidate`)。抽出器の出力は形式を検査する |
| 承認 | 人 | `entries` | `entries[].status` = `approved` / `rejected` |
| 分析 | エージェント (分析 skill) | 承認済みの入口、`.agents/memory` の癖 | `results/<file>` |
| validate result | ツール | 分析結果 | 指摘。形式に加えて、層・呼び出し元・不明の理由・根拠の実在を見る |
| レビュー | エージェント (レビュー skill) | 分析結果 | `reviews/<file>`。形式を検査する |
| build | ツール | `results/`、`entry-list.yaml`、プロファイル | `analysis/data/abatlas.duckdb` |
| serve | ツール | DuckDB | API、MCP (`/mcp`)、webapp (`/`) |

分析にかかった費用と時間 (`analyzer.run`) は、エージェントを呼び出した側が後から追記します。分析 skill は書きません ([formats.md](formats.md) の「来歴」)。

## build の中身

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

## コアの集計表

| 集計表 | 表示の種類 | 内容 |
|---|---|---|
| `mart_layer_flow` | 層の図 | 層のつながり。呼び出しと読み書きを、層の単位に集めたもの |
| `mart_entry_overview` | 表 | 入口ごとの概要。分析済みか、処理の段の数、読み書きの数、事実 / 解釈 / 不明の件数、複雑度 (仮)、実行の記録、古い版のプロファイルで分析したか (`profile_stale`) |
| `mart_progress` | 指標 | 階層の第 1 段ごとの、入口の数 / 承認済み / 分析済み。実行の記録があれば、実績の費用と残りの見積もり |
| `mart_quality_unknowns` | 表 | 不明の主張を、理由別に数える |
| `mart_data_access` | 行列 | 読み書きするデータ。入口の階層 × データの階層 |
| `mart_dataflow` | 有向グラフ | 読むデータ → 入口 → 書くデータ |
| `mart_callstack` | ツリー | 入口ごとの処理の段と、親子関係 |
| `mart_sequence` | シーケンス | 入口ごとに、呼び出しと読み書きを順に並べたもの |
| `mart_external_if` | 表 | 外部 API のホストごとに、呼んでいる入口 |
| `mart_shared_frames` | 表 | 2 件以上の入口から呼ばれる同じ処理 |
| `mart_entry_within` | 表 | 入口を包む入口。1 行 = 包まれる入口 × 包む入口 |

補足です。

| 集計表 | 補足 |
|---|---|
| `mart_layer_flow` | 行 = 呼ぶ側の層 → 呼ばれる側の層、または 層 → `/` + データの種類。`calls` = 箇所の数、`entries` = 入口の数、`unknowns` = 確かめられていない箇所の数。`unknowns` が 1 つでもあれば `status` = unknown で、図では点線。区分 (`subject`) を持たず、構成のページが表示の種類 (`view: layers`) で引く。集計表のページも同じ図を出す |
| `mart_data_access` | `kind` 列が種類。`ops` は、種類ごとの操作の 1 文字を語彙の並び順に連ねたもの (RDB なら C / R / U / D、ファイルなら R / W / A / D / L) |
| `mart_dataflow` | 向きは語彙の `direction` (in = 読む側、out = 書く側) |
| `mart_entry_within` | `ord` が外側からの順。入口の一覧の `within` から作る。包む関係を持たないプロファイルでは 0 行 |

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
| `subject` | | 何についての表か: `entry` / `data` / `external` / `frame` / `analysis`。画面のメニューの項目になる |
| `title` | | 論理名 (画面の見出し) |
| `hint` | | 読み方の 1 行 |
| `attach` | | 入口の画面のどの段に貼るか: `any` / `root` / `level1`〜`level5` |
| `tags` | | `monitor` = 分析の状態の画面に載る。`within` = 「入口を包む入口」の表の印 |
| `keys` | ○ | 表示の種類ごとの、列の対応 |
| `show` | | 一覧に出す列の並び |
| `labels` | | 列の表示名 |
| `filters` | | 一覧の絞り込みの候補 (`{label, where}`) |

表示の種類 (`view`) は 7 つです。必須と任意の `keys` の正本は、`dbt-template/models/core/schema.yml` の冒頭と、`abatlas/declarations.py` の `VIEWS` です。

| `view` | 描くもの | 任意で持てる `keys` の例 |
|---|---|---|
| `table` | 表 | `label` / `summary` / `members` / `order` / `source` |
| `matrix` | 行列 (開閉できる表) | `kind` (`subject: data` では必須) |
| `graph` | 有向グラフ | `label` / `status` / `path` |
| `layers` | 層の図。層どうしのつながりの表だけが使う | `label` / `status` |
| `sequence` | シーケンス | `node` / `evidence` |
| `tree` | ツリー | `source` / `tag` |
| `stat` | 指標 | — |

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
