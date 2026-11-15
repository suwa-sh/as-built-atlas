# batch-kestra プロファイル: エージェント向けの説明

対象は「Kestra で定期起動されるバッチ」。入口の発見と入口ごとの分析で、このファイルと `profile.yaml` の両方を読む。

## アーキテクチャと層の連鎖

```text
scheduler (Kestra Flow YAML)
  → shell (tasks[].commands[] の bash。run-skill.sh のような起動スクリプトを含む)
    → agent_skill (claude -p --agent <persona> '/<skill> <args>' で起動。SKILL.md の手順が本体)
    → program (Python スクリプト、dbt、bash の処理本体)
      → external (ライブラリ・SDK・CLI。ここで終端)
```

- `scheduler` が `role: entry`。Flow 1 本 = 入口 1 件
- Subflow (`io.kestra.plugin.core.flow.Subflow`) で呼ばれる Flow も入口として列挙する。親子関係はコールスタックのフレームで表す (親 Flow のフレームから子 Flow のフレームを `caller` で指す)
- `external` が `role: boundary`。ライブラリ・SDK・CLI の呼び出しに達したらコールスタックを閉じる

## 入口の判別 (抽出器のパラメータの決め方)

- Flow 定義は YAML で、`namespace` と `id` が必須。`files` の glob を実際の置き場に合わせる
- 階層パスは `/<namespace を '/' に>/<id>`。`profile.yaml` の既定パラメータでそのまま出る
- `triggers` が無い Flow (Subflow 専用、手動起動) も入口として列挙する。使われ方は `attributes.triggers` で分かる

## 入口ごとの分析で見るもの

| 層 | 読む場所 | 拾うこと |
|---|---|---|
| scheduler | Flow YAML | tasks の順、commands、Subflow の呼び先、env、inputs、triggers (cron) |
| shell | commands が指すスクリプト | 呼び出す次のコマンド、読み書きするファイル、環境変数の由来 |
| agent_skill | `claude -p --agent <persona> '/<skill> ...'` の persona 定義 (`.agents/agent-specs/<persona>/prompt.md` など) と skill の `SKILL.md` | 手順にある bash ブロックの実行内容、読み書きするファイル、MCP ツール、DB への記録 |
| program | スクリプト本体 | 接続先 (DB の host / database / table、ファイルパス、API の host / path)、操作 (RDB は CRUD、ファイルは read / write / append / delete / list) |

## 事実・解釈・不明の付け方

- **fact**: コードや定義にそのまま書いてある (`commands` の文字列、SQL の `INSERT INTO job_outcomes`、`open(path)`)。根拠はその行
- **interpretation**: 読み取って要約したもの (フレームの summary、何のための処理か)。根拠は読んだ範囲の代表行
- **unknown**: 次の典型例ではこの理由を使う
  - 接続文字列が環境変数 (`DB_URL` など) で、値がリポジトリに無い → `not_traceable_in_repo` (host は書かず、database / table は SQL から分かれば書く)
  - skill の手順が LLM の判断で分岐し、どのファイルを書くか静的に決まらない → `generated_at_runtime`
  - `{{ inputs.x }}` のような実行時の値で呼び先が決まる → `dynamic_dispatch`
  - 呼び先が scope の外 (同じリポジトリの、分析の範囲に入れていないディレクトリ) → `out_of_scope`

## データの当てはめ

- PostgreSQL (`ops_logs` など) → `rdb` (host は不明のことが多い。database / schema / table を書く。操作は create / read / update / delete)
- ファイル (`data/…`, `reports/raw/…`) → `filesystem` (host は書かない。directory / file。操作は read / write / append / delete / list。新規作成も上書きも `write`)
- Discord / Buffer / YouTube / GA4 などの API → `external_api` (`op: call`、host / path)
- SQLite ファイル → `rdb` (dbms: sqlite, database: ファイルパス)
