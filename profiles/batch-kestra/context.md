# batch-kestra プロファイル: エージェント向けの説明

対象は「Kestra で定期起動されるバッチ」。入口の発見と入口ごとの分析で、このファイルと `profile.yaml` の両方を読む。

## アーキテクチャと層の連鎖

```text
scheduler (Kestra Flow YAML)
  → shell (tasks[].commands[] の bash。run-skill.sh のような起動スクリプトを含む)
    → agent_skill (AI エージェントの CLI で起動される persona と skill。例: claude -p --agent <persona> '/<skill> <args>'。SKILL.md の手順が本体)
    → program (Python スクリプト、dbt、bash の処理本体)
      → external (ライブラリ・SDK・CLI。ここで終端)
```

- `scheduler` が `role: entry`。Flow 1 本 = 入口 1 件
- Subflow (`io.kestra.plugin.core.flow.Subflow`) で呼ばれる Flow も入口として列挙する。親子関係はコールスタックのフレームで表す (親 Flow のフレームから子 Flow のフレームを `caller` で指す)。呼ぶ段には、`links` (`kind: trigger`、`entry_id` は子の Flow の入口) も書く。`finally` の Subflow も同じ
- `external` が `role: boundary`。ライブラリ・SDK・CLI の呼び出しに達したらコールスタックを閉じる
- **分析の範囲**: 呼び先 (skill の本体、persona、起動スクリプトが呼ぶスクリプト) が、Flow の置き場の外 (リポジトリのルートの skill の置き場など) にあることが多い。そのときは、作業定義の `target.scope` をリポジトリのルートにし、入口は抽出器の `files` で絞る。後から範囲を広げると、入口を定義するファイルのパスが変わり、承認がすべて外れ、前の結果が検査に落ちる

## 入口の判別 (抽出器のパラメータの決め方)

- Flow 定義は YAML で、`namespace` と `id` が必須。`files` の glob を実際の置き場に合わせる
- 階層パスは `/<namespace を '/' に>/<id>`。`profile.yaml` の既定パラメータでそのまま出る
- `triggers` が無い Flow (Subflow 専用、手動起動) も入口として列挙する。使われ方は `attributes.triggers` で分かる
- 呼ぶ子の Flow は、`attributes.subflows` (`tasks` の直下) と `attributes.finally_subflows` (`finally` の直下) に出る。入れ子の task の中の Subflow は出ないので、Flow を読んで拾う

## 入口ごとの分析で見るもの

| 層 | 読む場所 | 拾うこと |
|---|---|---|
| scheduler | Flow YAML | tasks の順、commands、Subflow の呼び先、env、inputs、triggers (cron) |
| shell | commands が指すスクリプト | 呼び出す次のコマンド、読み書きするファイル、環境変数の由来 |
| agent_skill | 起動スクリプトが渡す persona の定義と、skill の `SKILL.md` (と、その `references/`) | 手順にある bash ブロックの実行内容、読み書きするファイル、MCP ツール、DB への記録。どの CLI で起動するかが設定で決まるときは、CLI ごとに段を分けず、persona の段 1 つ + skill の段 1 つにし、CLI の選択は、選んでいる段の `settings` (`kind: config_file`) に書く。書き分けは、下の「agent_skill の段の書き分け」 |
| program | スクリプト本体 | 接続先 (DB の host / database / table、ファイルパス、API の host / path)、操作 (RDB は CRUD、ファイルは read / write / append / delete / list) |

## agent_skill の段の書き分け

skill の本体は、手順を書いた文書 (`SKILL.md` と、その `references/`) で、実行するのは AI エージェントである。手順の中身ごとに、次のように書く。

| 手順の中身 | 書き方 | 根拠の行 |
|---|---|---|
| persona の定義 | agent_skill の段 (`kind: agent`)。persona がいつも読むファイルを `io` に書く。skill の段は、この段を `caller` にする | persona の定義の行 |
| CLI に渡すツールの許可のフラグ | `guards` にも `settings` にも書かない (満たさないと止まる確認でも、動きの切り替えでもない)。persona の段の `summary` の `note` に書く。環境変数や設定ファイルで切り替わるときだけ `settings` | 起動スクリプトの行 |
| bash ブロックで起動するスクリプト | program 層 (bash の関数なら shell 層) の段 | `call` は手順の文書の行、`io` はスクリプトの行 |
| 手順の文書に直接書いた SQL やコマンド | skill の段の `io` と、その道具の段 (external) | 手順の文書の行 |
| エージェントがツールで直接読み書きするファイル | skill の段の `io` | 手順の文書の行 |
| MCP のツールの呼び出し | skill の段の `io` (`external_api`、`path` に MCP のツールの名前) | 手順の文書の行 |
| 別の skill の手順に従う | 呼ばれる skill を agent_skill の段にし、呼ぶ側の skill の段を `caller` にする。呼ぶ経路が 2 つ以上あるときは、共通の親を `caller` にし、経路を `call` の `note` に並べる | 呼ぶ側の手順の文書の行 |
| サブエージェントの起動 | agent_skill の段 (`kind: subagent`)。依頼文の型 (references の prompt) があれば、それを `source` にする。サブエージェントの読み書きはこの段の `io`、サブエージェントが動かすスクリプトは、この段の子の段 | 起動を指示する行 |
| プロンプトで受け渡すファイル (状態、人の回答) | 渡す側と受ける側の両方の読み書きに書く | Flow の行と、手順の文書の行の両方 |
| 「関連」の節に名前が出るだけの skill | 段にも `links` にもしない | — |
| persona が従う共通の規約にある手順 | その入口の経路で実際に行う分を、persona の段の下に書く | 規約の文書の行 |

- **1 つの Flow が、skill を 2 回以上起動するとき**: 起動ごとに、起動スクリプト以下の段を 1 組ずつ書く (`name` と `source` は同じ、`id` だけ変える)。2 回目を途中で止めると、2 回目の skill の読み書きが集計から消える。人の確認 (Pause) の後の起動は、再開されたときの `conditional`
- **起動の仕組みの段 (起動スクリプト、結果の記録、通知) は、多くの入口が通る**。`name` と `source` を、先に分析した入口の結果にそろえる (共有の処理の表で 1 行にまとまる)。`summary`・`io`・`rules` は、その入口が通る経路の分だけを書いてよい (入口ごとに違ってよい)。ほかの入口の結果から写すときは、skill の名前、commit の範囲、タイムアウトなど、入口に固有の文を見直す
- **スクリプトが直接呼ぶ外部のコマンド** (`pg_dump`、`aws s3 cp` など): コマンドを `external` の段にして閉じ、コマンドが行う読み書きは、**呼ぶ側の段** (shell や program) の `io` に書く。`external` の段には `io` を書かない (読み書きの置き場が、入口ごとに割れない)。呼ぶ側を辿れていないとき (呼び出しが `unknown`) だけ、`external` の段に書いてよい。前に `external` の段に書いた結果は、誤りではない (レビューは、指摘しない)
- **段にする外部のコマンドと、しないコマンド** (`cli` の説明と同じ): 別のプロセスやサービスに届くコマンド (`pg_dump`、`psql`、`aws`、`curl`、`ssh`) を `external` の段にする。ファイルを直接扱うシェルの標準のコマンド (`find`、`gzip`、`mkdir`、`cp`、`mv`、`rm`、リダイレクト) と、整形だけのコマンド (`jq`、`sed`、`awk`、`sort`) は、段にしない。読み書きは、そのコマンドを書いたスクリプトの段の `io` (`filesystem`) に書き、根拠はその行。`find ... -exec gzip {} \;` の gzip の読み書きも、`find` を書いたスクリプトの段に書く
- **フレームの `kind`**: `flow` (その結果の入口として書く Flow。Subflow 専用の Flow でも、自分の結果では `flow`)、`subflow` (親の Flow の結果の中に、Subflow の呼び先として書く Flow)、`script` (ファイルとして起動するスクリプト。シェル、`python notify.py`)、`module` (モジュールとして起動するか、import して使う処理。`python -m jobs.x`、`jobs.lib.db`)、`binary` (ソースの無い実行ファイル)、`agent` (persona)、`skill` (skill)、`subagent` (サブエージェント)、`cli` (外部のコマンド)、`library` (ライブラリ・SDK)。新しく分析するときに使う語で、前に分析した結果の別の綴りは、誤りではない (レビューは、指摘しない)
- **読み書きも、業務のルールも、権限の確認も持たない包み** (計測の包み、タイムアウトの包み): 段にしない。包んでいる側の `summary` に名前を書く
- **起動される側のつながり** (上流の Flow の成功で起動される、人の確認の後に再開される): `links` は出ていく向きだけなので、入口の段の `parameters` に書く
- **リポジトリの外のファイル** (ホームの設定、プラグインのキャッシュ、別のリポジトリへのリンクの先): 読み書きの相手としてだけ書き、根拠には使わない (範囲の外は、検査が根拠として認めない)

## 事実・解釈・不明の付け方

- **fact**: コードや定義にそのまま書いてある (`commands` の文字列、SQL の `INSERT INTO job_outcomes`、`open(path)`)。根拠はその行
- **interpretation**: 読み取って要約したもの (フレームの summary、何のための処理か)。根拠は読んだ範囲の代表行
- **unknown**: 次の典型例ではこの理由を使う
  - 接続文字列が環境変数 (`DB_URL` など) で、値がリポジトリに無い → `not_traceable_in_repo` (host は書かず、database / table は SQL から分かれば書く)
  - skill の手順がエージェントの判断で分かれ、どのファイルを書くかが静的に決まらない → 置き場と操作が手順の文書で決まっていて、どのファイルかだけが実行時に決まるなら、`interpretation` で、名前の変わる所を `*` にして書き (例: `ideas/todo/*.md`)、実行時に決まることを `note` に書く。置き場そのものが決まらないときだけ `generated_at_runtime`
  - `{{ inputs.x }}` のような実行時の値で呼び先が決まる → `dynamic_dispatch`
  - 呼び先が scope の外 (同じリポジトリの、分析の範囲に入れていないディレクトリ) → `out_of_scope`
- 同じファイルに綴りが 2 つあるとき (skill の置き場が、別の置き場へのリンクになっている): リンクの先 (実体) の綴りで書く (綴りが 2 つあると、集計が分かれる)
- 起動スクリプトが、Flow の `env` より後に、リポジトリの外の設定を読み込むときは、Flow が固定の値で書いた環境変数でも、分析の skill の「固定の値で閉じている呼び出し」に当てはめない (値が上書きされうる)。動きを変える変数は `settings` に書き、この入口での値を `note` に書く

## データの当てはめ

- PostgreSQL (`ops_logs` など) → `rdb` (host は不明のことが多い。database / schema / table を書く。操作は create / read / update / delete)
- ファイル (`data/…`, `reports/raw/…`) → `filesystem` (host は書かない。directory / file。操作は read / write / append / delete / list。新規作成も上書きも `write`)
- Discord / Buffer / YouTube / GA4 などの API → `external_api` (`op: call`、host / path)
- SQLite ファイル → `rdb` (dbms: sqlite, database: ファイルパス)
