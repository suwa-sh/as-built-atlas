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

## 手順

1. 分析リポジトリに `.agents/memory/desired-state/analysis-conventions.md` があれば読む (このリポジトリで合意済みの unknown の扱いやデータの当てはめは、指摘の対象にしない)。`analysis/results/<file>` と `analysis/work-definition.yaml` を読む。`target.clone_path/target.scope` を対象のルートとする
2. 機械チェックを先に回す: `<abatlas> validate result analysis/results/<file> --work analysis/work-definition.yaml`。NG なら、その指摘をそのまま findings に写して終わる (意味の検査はしない)。出力に「プロファイルを自動で読めない」と出たら、OK でも完了にしない (プロファイルとの突き合わせが省かれている)。`analysis/work-definition.yaml` の `profile.dir` と、その場所の `profile.yaml` を確かめて直す
3. 主張を 1 つずつ検査する。対象は `summary`、各フレームの `call` / `summary` / `parameters[]` / `io[]`
   - **根拠の実在**: `evidence` の file:line を開き、その行 (前後 5 行) が主張を支えているか。支えていなければ `evidence_mismatch`
   - **状態の妥当性**: コードにそのまま書いてあるのに `interpretation`、読み取りなのに `fact` になっていないか → `status_mismatch`
   - **不明の妥当性**: `unknown` の `reason` が実態と合うか (環境変数で決まるのに `dynamic_dispatch` など) → `reason_mismatch`。逆に、読めば分かるのに `unknown` → `avoidable_unknown`
   - **データの当てはめ**: `resource.kind` と `levels` が `context.md` の当てはめ方と合うか → `resource_mismatch`
   - **辿り漏れ**: フレームの `source` を読み、次の層の呼び出しがあるのにフレームが無い → `missing_frame`
4. `analysis/reviews/<file>` に書く (形式は `<oss>/schema/review.schema.json`):

```yaml
format_version: 1
entry_id: <id>
reviewed_at: "<ISO 8601>"
reviewer: "<誰が / 何が>"
machine_check: ok | ng
findings:
  - kind: evidence_mismatch | status_mismatch | reason_mismatch | avoidable_unknown | resource_mismatch | missing_frame | machine_check
    severity: high | medium | low
    where: callstack/<frame id>/io/0      # YAML 内の場所
    claim: "<何が問題か 1 文>"
    evidence: { file: <対象の file>, line: <行> }
    suggestion: "<直し方 1 文>"
```

   - **文字列は必ず二重引用符で囲む** (`claim` / `suggestion` / `notes`)。コロン・角括弧・`#` を含む文章を裸で書くと YAML として読めなくなる
   - 機械チェックの NG を写すときは `kind: machine_check`
5. 自分の出力を機械チェックする: `<abatlas> validate review analysis/reviews/<file> --result analysis/results/<file>`。NG なら直して OK にする
6. 報告: findings の件数 (severity 別) と、`high` の要約

## severity の目安

- high: 根拠が主張を支えていない / 辿り漏れでコールスタックが途中で切れている / 読めば分かるのに unknown
- medium: 状態 (fact / interpretation) の取り違え / データの段の当てはめ違い / reason の種類違い
- low: 表現、note の不足

## 禁止

- `analysis/results/<file>` を直接書き換える (指摘を書くだけ)
- 対象リポジトリを変える
- 分析のやり直し (フレームを自分で足さない。足りなければ `missing_frame` として指摘する)
