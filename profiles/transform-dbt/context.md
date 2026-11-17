# transform-dbt プロファイル: エージェント向けの説明

対象は「dbt で組んだデータの変換」。入口の発見と、入口ごとの分析で、このファイルと `profile.yaml` の両方を読む。

分析の範囲 (`target.scope`) は、`dbt_project.yml` のあるフォルダにする。

## アーキテクチャと層の連鎖

```text
model  (dbt の model、snapshot。入口)
  → macro    (project の macro)
    → external (package の macro、adapter の関数。ここで終端)
```

- `model` が `role: entry`。model 1 つ = 入口 1 件
- **上流の model は、呼び出しではなく、読み書きで表す**。`ref('x')` は「model x が作る表を読む」、この model 自身は「自分の表を書く」。そうすると、「同じ表を、書く入口と読む入口」のつながり (データを介したつながりの表) が、そのまま model の依存になる
- macro を呼ばない model は、入口のフレーム 1 つだけの結果になる (読み書きを持つので、終端の決まりを満たす)

## 入口の判別

| もの | 入口にするか | 見つけ方 |
|---|---|---|
| model (SQL、Python) | する | 抽出器 `dbt-models` |
| snapshot | する。階層は `/(snapshot)/<名前>`。名前は、`{% snapshot 名前 %}` の名前 | 抽出器 `dbt-snapshots` (ファイルの名前を、snapshot の名前にする)。抽出器が出した候補ごとに、ファイルの中の名前と同じかを確かめる。違うファイル、1 ファイルに複数あるファイルは、抽出器の `exclude` に足して、読んで `listed` で足す。YAML で定義したものも、`listed` で足す |
| seed (CSV) | しない | データそのもの。読む model の読み書きに現れる |
| source | しない | project の外で作られる表。読む model の読み書きに現れる |
| analysis、macro、テスト | しない | macro は、呼ぶ model の中のフレーム。テストは、model の `tests` |
| 表を作らない model (`materialized='ephemeral'`) | する | 自分の表を書かず、呼ぶ model の SQL に埋め込まれる。読み取りだけを書く。これを `ref` する側の書き方は、下の「読み書きの書き方」 |
| 無効にした model (`enabled: false`) | しない | 抽出器の `exclude` に足し、`rationale` に書く |

- `dbt_project.yml` の `model-paths` / `snapshot-paths` を確かめ、既定と違えば、抽出器の `files` と `strip_prefix` を合わせる
- 階層は、`models` の下のフォルダと、model の名前 (`models/staging/stg_orders.sql` → `/staging/stg_orders`、id は `staging.stg_orders`)

## 入口ごとの分析で見るもの

| 層 | 読む場所 | 拾うこと |
|---|---|---|
| model | model のファイル、同じフォルダと上のフォルダの YAML (`schema.yml` など)、`dbt_project.yml` の該当の設定 | 作り方 (`materialized`)、読む相手 (`ref`、`source`)、書く表、列、業務のルール、テスト |
| macro | `macros/` の下の、model が呼ぶ macro | macro が読む表 (`ref`、`source`、`run_query`)、組み立てる SQL の決まり |
| external | package の macro や、adapter の関数を呼んでいる行 | `source` は、その行 |

### フレームにするもの・しないもの

- **入口のフレーム**: model のファイル (`layer: model`、`kind` は `model` / `snapshot`、`name` は model の名前)
- **macro のフレーム**: project の macro のうち、表を読む・書く・問い合わせを実行する (`run_query`、`ref`、`source` を含む) もの、業務のルール (計算、判定) を持つもの。列の名前を整えるだけ・SQL の断片を返すだけの macro は、フレームにしない (呼ぶフレームの `summary` に書く)
- **`external` のフレーム**: package の macro (`dbt_utils.star` など) が、SQL の組み立てや、読む列を左右するとき。`source` は、呼んでいる行。作り方 (materialization) や、adapter の内部は、フレームにしない。データベースに組み込みの SQL の関数 (`string_agg`、`coalesce` など) も、フレームにしない
- **dbt が暗黙に呼ぶ macro** (`generate_schema_name`、`generate_alias_name` など。model は呼んでいない): フレームにしない。schema や表の名前を決めた根拠として、読み書きの根拠に、macro の行を入れる
- **CTE (`with` の中の問い合わせ)** は、フレームにしない。model の中の手順として、`summary` に書く
- **hook** (`pre-hook`、`post-hook`、`on-run-start` / `on-run-end`): model に掛かる hook が、表を読み書きする・外を呼ぶなら、入口のフレームの読み書きに書く (`note` に、hook であることを書く)

### 読み書きの書き方

| もの | 種類と操作 | 段 |
|---|---|---|
| この model が作る表 | `rdb`。`materialized` が `table` / `view` / `materialized_view` なら `create`。`incremental` なら `create` と、増やし方に応じて `update` (merge) や `delete` (delete+insert)。`ephemeral` なら書かない | `schema` と `table` (下の「表の名前」) |
| `ref('x')` で読む model / seed / snapshot | `rdb` の `read` | 相手の model が書く表と、同じ段にそろえる。seed は、`dbt_project.yml` の `seeds` の設定から、同じ決め方で段を作る (CSV が範囲に無くても、`out_of_scope` にしない。設定をたどったので `interpretation`) |
| `ref('x')` で読む相手が、表を作らない model (`ephemeral`) | 相手の SQL が、この model に埋め込まれる。**相手が読んでいる表を、この model の読み取りとして書く** (`rdb` の `read`。根拠は、`ref` の行と、相手のファイルの中の行。相手がさらに `ephemeral` を読むなら、表を作る相手に着くまで辿る)。`summary` に、どの `ephemeral` を経由したかを書く | 相手が読む表の段 |
| `source('s', 't')` で読む表 | `rdb` の `read` | source の定義 (YAML) の `schema` と、表の名前 (`identifier` があれば、それ) |
| snapshot が作る表 | `rdb` の `create` と `update` (変化があった行に、終わりの時刻を書く) | snapshot の設定の `target_schema` と名前 |
| `run_query` で実行する SQL | SQL のとおり | SQL のとおり |

- **表の名前**: `table` は、`alias` があればそれ、無ければ model の名前。`schema` は、`dbt_project.yml` と model の設定の `+schema` / `schema` の値 (project が `generate_schema_name` の macro を持つなら、その決まりで作った名前。読めなければ、設定の値をそのまま書き、`note` に書く)。接続先で決まる既定の schema (設定に無いとき) は、書かない
- `dbms` は、範囲の中の `profiles.yml` の `type` が読めれば書く。`database` は、設定に値がそのまま書いてあるときだけ書く (`env_var` で決まるものは、既定の値があっても書かない)。どちらも、読めなければ書かない (そのために `unknown` にしない)
- フォルダ単位の設定 (`dbt_project.yml` の `+materialized`、`+schema`) で、作り方や schema が決まるときは、その行を、読み書きと、入口のフレームの `summary` の両方の根拠に入れる
- **列 (`fields`)**
  - この model が作る表: 最後の `select` が出す列を、`write` で書く。`select *` で終わるときは、`*`
  - 読む相手: その相手から取り出す列を `read`、結合・絞り込み・並べ替え・集計の区切りに使う列を `filter` で書く。相手を `select *` で読むときは、`*`
  - 列の名前を付け替えているとき (`as`) は、読む側には元の名前、書く側には付け替えた後の名前を書く
  - 式で作った値 (列をつないだキーなど) を、結合・絞り込み・集計の区切りに使うときは、元の列を `read` と `filter` の両方で書く
  - `join ... using (x)` の列は、両方の相手で `filter`。`read` は、`select` で取り出している側だけ
  - 表を作る model の、最後の `order by` の列は、`filter` に書かない (並びは、表の中身を変えない)
- 同じ相手を、1 つの model の中で何度読んでも、読み書きは 1 件にまとめる (列と条件は、合わせて書く)

### 呼び出しの条件・設定・ルール・テスト

- **`call.when`**: macro を、条件の中 (`{% if %}`) で呼ぶときは `conditional`
- **増分の更新** (`is_incremental()`): 2 回目からの実行だけで効く絞り込みは、入口のフレームの `rules` (`decision`) に、「どの行を取り込むか」を書く
- **`settings`**: `var('x')`、`env_var('X')`、`target.name` で、SQL や対象が変わるとき。`kind` は、`var` なら `config_file`、`env_var` なら `env`、`target` なら `other`
- **`rules`**: 業務の意味を持つ計算 (金額や率の式、区分を決める `case`)、取り込む行を決める絞り込み (相手に無い行を落とす `inner join` を含む)、重複を除く決まり (何を同じとみなすかが業務の意味を持つ `distinct`、`row_number` での選び方)。書かないもの: 型の変換、名前の付け替え、null を補うだけの `coalesce`、キーを作るための文字の連結、行を減らさない `distinct`
  - ルールの `value` は、式を言い換えた文になる。式がそのまま 1 か所に書いてあれば `fact`、複数の句を合わせて読み取ったものは `interpretation`
- **`guards`** は、ふつう書かない (dbt の model は、権限の確認をしない)
- **`tests`** (作業定義で選んだときだけ): YAML に書いた model と列のテスト (`unique`、`not_null`、`relationships`、`accepted_values`、package のテスト)、`tests/` の下の SQL のテストで、この model を `ref` するもの。`kind` は、データを確かめるテストは `integration`、`unit_tests:` で定義したテストは `unit`。`name` は、テストの名前と、掛かる列 (例: `not_null:order_id`)
- **`links`** は、ふつう書かない (model どうしの依存は、読み書きで表す)。model が、別の処理を起動する (hook で外部の API を呼ぶ) ときは、読み書きに書く

## 事実・解釈・不明の付け方

- **fact**: SQL や YAML にそのまま書いてある (`ref('stg_orders')`、`select order_id`、`materialized='table'`)。根拠はその行
- **interpretation**: 読み取って要約したもの (フレームの `summary`)。設定をたどって決めた schema。package の macro が出す列
- **unknown**: 次の典型例では、この理由を使う
  - 読む相手や列が、実行時の問い合わせの結果で決まる (`run_query` の結果で、列や表を組み立てる) → `generated_at_runtime`
  - 相手の名前が、変数で決まる (`ref(var('x'))`) → `dynamic_dispatch` (既定の値が読めれば、その相手を書いて `interpretation`)
  - package の macro の中が、範囲に無い → フレームは `external` で閉じる (不明にしない)。出す列が分からないときだけ、その読み書きの `fields` を書かず、`note` に書く
