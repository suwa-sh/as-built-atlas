---
name: abatlas-review-entry
description: 分析結果 YAML (results/ 配下の 1 ファイル) を、分析した文脈を持たない立場で読み直し、根拠が主張を支えているか・事実と解釈の区別が妥当か・不明の理由が適切かを検査して reviews/ 配下の対応するファイルに指摘を書く。分析結果のレビューを頼まれたとき、abatlas-analyze-entry から呼ばれたときに使う。
---

# 分析結果のレビュー (フレッシュ文脈)

分析結果を書いた側の思い込みを外すためのレビュー。**YAML と対象のファイルだけを根拠に**判定する。分析をやり直さない。

## 入力

- 分析リポジトリのルート (カレントディレクトリ)。`analysis/work-definition.yaml`、`analysis/results/<file>`
- 入口 id (引数)。`<file>` は id の `/` を `__` に置き換えて `.yaml` を付けたもの (分析 skill と同じ規則)
- OSS の参照物 `<oss>`: カレントディレクトリに `.abatlas/` があればそれ (分析リポジトリ)。無ければこの SKILL.md の実体の 3 つ上 (OSS の checkout)
- ツールの呼び方 `<abatlas>`: 分析リポジトリでは `docker compose run --rm abatlas` (コンテナの中で動く。パスはリポジトリのルートからの相対で書く)。OSS の checkout では `uv run abatlas`
- 出力: `analysis/reviews/<file>`
- 2 回目のレビューで、「前のレビューで直さなかった指摘」を渡されたとき: いまの結果でも当てはまるかを確かめ、当てはまるものは、新しいレビューのファイルに、直っていない指摘 (`resolved` を書かない) として引き継ぐ (レビューのファイルは置き換わるので、引き継がないと、直さなかった指摘が数から消える)

## 手順

1. 分析リポジトリに `.agents/memory/desired-state/analysis-conventions.md` があれば読む (このリポジトリで合意済みの unknown の扱いやデータの当てはめは、指摘の対象にしない)。`analysis/results/<file>` と `analysis/work-definition.yaml` を読む。`target.clone_path/target.scope` を対象のルートとする
2. 機械チェックを先に回す: `<abatlas> validate result analysis/results/<file> --work analysis/work-definition.yaml`。NG なら、その指摘をそのまま findings に写して終わる (意味の検査はしない)。出力に「プロファイルを自動で読めない」と出たら、OK でも完了にしない (プロファイルとの突き合わせが省かれている)。`analysis/work-definition.yaml` の `profile.dir` と、その場所の `profile.yaml` を確かめて直す
3. 主張を 1 つずつ検査する。対象は `summary`、各フレームの `call` / `summary` / `parameters[]` / `io[]` / `links[]` / `guards[]` / `settings[]` / `rules[]` / `tests[]`
   - **根拠の実在**: `evidence` の file:line を開き、その行 (前後 5 行) が主張を支えているか。支えていなければ `evidence_mismatch`。先に `<abatlas> evidence analysis/results/<file> --work analysis/work-definition.yaml` で、根拠の近くに名前が無い主張を並べ、並んだ主張から確かめる (並ばなかった主張も、確かめる。名前が近くにあっても、主張を支えているとは限らない)。並んだ主張も、判定の基準は同じ (根拠の行がコードで主張を支えているか)。支えていなければ `evidence_mismatch`。支えていて、名前が近くに無い理由が結果の `notes` に書いてあれば、指摘しない。支えているのに理由が書かれていないときは、`missing_item` (low) で、理由を `notes` に足すように書く。理由を求めるのは、名前が見つからなかった行だけ (「(照合できない)」と付いた行は、根拠を確かめるだけで、理由が無くても指摘しない) (`analyzer.skill_version` が 0.4.6 より前の結果では、指摘しない。その手順が無かった)
     - 根拠の指摘の種類と重さは、次の表で決める (上から順に当てはめる。呼び出しの `when`、フレームの `layer` と `kind`、列の `use` などの当てはめだけが違うときは、この表ではなく、下の「当てはめ」の `classification_mismatch` にする。読み書きの相手の `resource.kind` と `levels` の違いは、下の「データの当てはめ」の `resource_mismatch` にする。`missing_item` は、YAML の項目が無いときと、上の「理由が書かれていない」ときに使う)

       | 起きていること | 種類 | 重さ |
       |---|---|---|
       | 違うのが、説明の文 (`summary`、`parameters` の `value`、`detail`、`note`) だけ。項目として書いた主張 (呼び出し、読み書きの相手と操作、つながり、権限の確認、設定、業務のルール) は、コードの動きと合っている。根拠が、説明文・help・コメントの行でも、実行されるコードの行でも同じ | `evidence_mismatch` | low |
       | 項目として書いた主張が、コードの動きと違う。または、根拠の行が、主張と関係のない場所を指している | `evidence_mismatch` | high |

       - 業務のルールの文 (`rules[].value`) は、ルールの中身そのものなので、説明の文ではなく、項目として書いた主張に数える。ルールの中身 (何をどう計算するか、どの条件で分けるか、日数や件数の範囲) がコードと違えば high。中身は合っていて、言い回しや補足だけが違えば low
       | 主張は合っているが、根拠の行が一部だけ足りない (文の中の句を支える行が無い) | `evidence_mismatch` | low |

     - 結果の `notes` に、前に並んだ主張への説明が残っていて、いまは並んでいないとき: 説明を確かめる義務は無い (根拠は、ほかの主張と同じに確かめる)
   - **状態の妥当性**: コードにそのまま書いてあるのに `interpretation`、読み取りなのに `fact` になっていないか → `status_mismatch`
   - **不明の妥当性**: `unknown` の `reason` が実態と合うか (環境変数で決まるのに `dynamic_dispatch` など) → `reason_mismatch`。逆に、読めば分かるのに `unknown` → `avoidable_unknown`。ただし、理由が `not_analyzed` (打ち切り) の主張は、読めば分かることが前提なので、それだけでは `avoidable_unknown` にしない。`note` に「どこまで読んだか」と「なぜ止めたか」が無いときだけ、low で指摘する (続きを分析するかは、人が決める)。打ち切りを、`analysis-conventions.md` かプロファイルの `context.md` が禁じているときは、`avoidable_unknown` として指摘する
   - **データの当てはめ**: `resource.kind` と `levels` が `context.md` の当てはめ方と合うか → `resource_mismatch`
   - **当てはめ**: フレームの `layer` や `kind`、呼び出しの `when` (基準は、分析の skill の `call` の説明。手前に、入力の誤りや権限の不足で打ち切る経路があるだけなら `always`)、列の `use`、つながり・確認・設定・ルールの `kind` が、コードと `context.md` の決まりに合うか → `classification_mismatch`
   - **綴り**: `guards[].value`、`settings[].name`、`links[].target`、`fields[].name`、`tests[].name` に、説明の文や、かっこ書きの補足が混ざっていないか (コードに書いてある文字だけを書く決まり)。同じもの (同じ設定、同じ確認の関数、同じ列) が、ほかの入口の結果 (`analysis/results/` のほかのファイル) に別の綴りで書かれていないか (名前や定義の場所で探す) → どちらも `classification_mismatch` (low)。この確かめのために、ほかの入口の結果を読んでよい (書き換えない)
   - **書き漏れ**: フレームの `source` を読み、次のものがあるのに書かれていない → `missing_item`。呼び出しに `when` が無い (`when` が書いてあって、種類が違うときは `classification_mismatch`) / 読み書きの列がコードから読めるのに `fields` が無いか、一部の列が欠けている / ほかの入口へのつながり、権限の確認、動きを変える設定、業務のルールが、その段にあるのに無い。`analyzer.skill_version` が 0.4.0 より前の結果では、指摘しない (その観点を分析していない)。`tests` の漏れは、`analyzer.tests` が `true` のときだけ見る。この入口の木の中の固定の値で閉じている呼び出し (分析の skill の「固定の値で閉じている呼び出しは、辿らない」) は、フレームが無くても漏れではない (条件を持つフレームの `summary` の `note` に、閉じている値と行が書いてあることと、当てはめる条件を、その経路が満たすことを確かめる。満たさないのに辿っていなければ `missing_frame`)。手前のコードが弾く呼び出し (分析の skill の「手前のコードが弾く呼び出しは、辿らない」) も同じ (`note` に、弾いている行と条件の行が書いてあることと、3 つの条件を、その経路が満たすことを確かめる)。入口の外から来る値 (URL のパラメータとクエリ、状態、保存されたデータ、設定、描く側から渡される値) で届かないように見えるだけの呼び出しを、辿っていなければ `missing_frame`。同じ処理が、呼び出し元によって閉じたり開いたりするときは、開いている枝の中にフレームになる呼び出しがあれば、開いている呼び出し元の下に、もう一度書いてあるかを見る (フレームになる呼び出しが無い枝は、次の項目)。前の版 (0.4.1 まで) の結果が、閉じた枝を `conditional` で書いていても、開いている枝を別の置き場に書いていても、指摘しない
   - 分析の skill が「もう一度書かない」と決めている所を、書き漏れにしない: すでに別の呼び出し元の下に書いた処理を呼ぶだけの呼び出し元 (`summary` で指していればよい)、開いている枝の中にフレームになる呼び出しが無い分かれ道 (設定やルールが、最初のフレームにあればよい。もう一度書いてあるのは、書かないと呼び出し元が終端の決まりを満たせないときだけ)。画面の入口で、入口の定義に書いてあるルートの名前やパスの固定の部分で閉じた枝も、漏れではない。呼ばれる側が、いつも同じ結果を返すだけの権限の確認が `guards` に残っているのは、誤りではない。`analyzer.skill_version` が 0.4.3 より前の結果で、これらを余分に書いているのも、指摘しない
   - **辿り漏れ**: フレームの `source` を読み、次の層の呼び出しがあるのにフレームが無い → `missing_frame`。読み書きを持たず、権限の確認 (`guards`) か業務のルール (`rules`) だけを持つ終端のフレームは、機械チェックが通すので、とくに確かめる: 確認や判定の後に、読み書きや外への呼び出しが続いていないか (続いているのに、その先のフレームが無ければ `missing_frame`)。プロファイルの `context.md` が「フレームにしない」と決めているもの (見た目だけの部品、同じ処理の 2 回目以降など) は、漏れに数えない
4. `analysis/reviews/<file>` に書く (形式は `<oss>/schema/review.schema.json`):

   ```yaml
   format_version: 1
   entry_id: <id>
   reviewed_at: "<ISO 8601。書き終えた時点の実際の時刻。date -u +%Y-%m-%dT%H:%M:%SZ で取る>"
   reviewer: "<レビューしたモデルの名前と、fresh context であること。例: claude-xxx (fresh context)>"
   machine_check: ok | ng
   findings:
     - kind: evidence_mismatch | status_mismatch | reason_mismatch | avoidable_unknown | resource_mismatch | classification_mismatch | missing_frame | missing_item | machine_check
       severity: high | medium | low
       where: callstack/<frame id>/io/0      # YAML 内の場所。項目が無い、という指摘 (書き漏れ) は、それが入るはずの親を指す (例: フレームに io が 1 つも無いなら callstack/<frame id>)。ほかの形: summary (入口の概要)、callstack/<frame id>/call、callstack/<frame id>/summary、callstack/<frame id>/parameters/0、callstack/<frame id>/links/0 (guards / settings / rules / tests も同じ形)、callstack/<frame id>/io/0/fields
       claim: "<何が問題か 1 文>"
       evidence: { file: <対象の file>, line: <行> }
       suggestion: "<直し方 1 文>"
   notes: "<指摘にしなかったが、伝えておくこと (任意)>"
   ```

   - `resolved` は書かない (分析の側が、直した指摘に書く)

   - **文字列は必ず二重引用符で囲む** (`claim` / `suggestion` / `notes`)。コロン・角括弧・`#` を含む文章を裸で書くと YAML として読めなくなる
   - 機械チェックの NG を写すときは `kind: machine_check`

5. 自分の出力を機械チェックする: `<abatlas> validate review analysis/reviews/<file> --result analysis/results/<file>`。NG なら直して OK にする
6. 報告: findings の件数 (severity 別) と、`high` の要約

## severity の目安

- high: 根拠が主張を支えていない (重さは、手順 3 の「根拠の実在」の表で決める。説明の文だけの違いと、根拠の行の一部の不足は low) / 辿り漏れでコールスタックが途中で切れている / 読めば分かるのに unknown
- medium: 状態 (fact / interpretation) の取り違え / データの段の当てはめ違い / reason の種類違い / 層や種類の当てはめ違い (`when` は、`on_failure` に関わる違いだけ) / 権限の確認・書き込む列の書き漏れ
- low: 表現、note の不足。`always` と `conditional` の取り違え。そのほかの書き漏れ (読むだけの列、設定、業務のルール)。主張は合っているが、根拠の行が一部だけ足りない (例: 数値の定義の行が無い)

## 禁止

- `analysis/results/<file>` を直接書き換える (指摘を書くだけ)
- 対象リポジトリを変える
- 分析のやり直し (フレームを自分で足さない。足りなければ `missing_frame` として指摘する)
