---
name: abatlas-analyze-entry
description: 承認済みの入口 1 件を、プロファイルの層の連鎖に沿って入口から外部ライブラリ呼び出しまで辿り、根拠付きの分析結果 YAML (results/ 配下、入口 1 件 = 1 ファイル) を書いて機械チェックに通す。「この入口を分析して」「results を作って」と頼まれたとき、または入口 id を渡されたときに使う。
---

# 入口 1 件の分析

入口 1 件につき YAML 1 ファイル。主張ごとに **事実 / 解釈 / 不明 + 理由** と根拠 (ファイルと行) を付ける。分からないことを分かったように書かない。

## 入力

- 分析リポジトリのルート (カレントディレクトリ)。`analysis/work-definition.yaml` と `analysis/entry-list.yaml` が必須
- 分析の資産は `analysis/` の下: `analysis/work-definition.yaml`、`analysis/entry-list.yaml`、`analysis/results/`、`analysis/reviews/`
- 入口 id (引数)。`analysis/entry-list.yaml` の `entries[]` で `status: approved` のもの
- OSS の参照物 `<oss>`: カレントディレクトリに `.abatlas/` があればそれ (分析リポジトリ)。無ければこの SKILL.md の実体の 3 つ上 (OSS の checkout)
- ツールの呼び方 `<abatlas>`: 分析リポジトリでは `docker compose run --rm abatlas` (コンテナの中で動く。パスはリポジトリのルートからの相対で書く)。OSS の checkout では `uv run abatlas`
- プロファイル: `analysis/work-definition.yaml` の `profile.dir`。無ければ `<oss>/profiles/<profile.id>/`
- 結果ファイル名 `<file>`: 入口 id の `/` を `__` に置き換えて `.yaml` を付けたもの (例: `daily/housekeeping` → `daily__housekeeping.yaml`、`daily.housekeeping` → `daily.housekeeping.yaml`)。ETL と機械チェックも同じ規則で探す
- 出力: `analysis/results/<file>`

## 前提

- 対象は `target.clone_path` に `target.commit` で checkout 済み (違えば止める)。分析リポジトリでは `.env` の `ABATLAS_TARGET` が同じ場所を指している (コンテナには `/ws/target` として見える)
- 冪等: `analysis/results/<file>` が既にあり、その `target.commit`・`analyzer.profile.version`・`analyzer.skill_version` が今回と同じなら、何もせず「skip」と報告して終わる。どれかが違えば、分析し直して、結果とレビューのファイルを置き換える

## 手順

1. **このリポジトリの癖を読む**: 分析リポジトリに `.agents/memory/desired-state/analysis-conventions.md` があれば最初に読み、以下の手順で `context.md` と食い違うときは**こちらを優先**する (unknown の扱い、データの当てはめ、見なくてよいもの)。無ければ飛ばす
2. 読む: `profile.yaml` (層の連鎖、各層の `invokes_next` と `io`)、`context.md` (分析で見るもの、事実・解釈・不明の付け方、データの当てはめ)、`<oss>/schema/vocab/unknown-reasons.yaml`、`<oss>/schema/vocab/resource-kinds.yaml`、見本 `<oss>/tests/fixtures/result-housekeeping.yaml`
3. 入口を特定する: `analysis/entry-list.yaml` の該当 entry の `source` と `attributes` を読む。`source.file` を開き、入口のフレーム (`caller: null`) を書く
4. 層の連鎖に沿って辿る。各フレームで次を決める:
   - `layer` (プロファイルの層 id)、`kind`、`name`、`source` (定義場所。`role: boundary` の層のフレームはリポジトリに定義が無いので、リポジトリの中でそれを使っている箇所。どの行にするかは `context.md` の決まりに従う)、`caller` (呼び出し元フレームの id)
   - `call`: 呼び出しが成立する根拠 (呼び出し箇所の file と line を evidence に)
   - `summary`: 何をする処理か (interpretation。読んだ範囲の代表行を evidence に)
   - `parameters`: 入力 (分かる範囲)
   - `io`: 読み書きするデータ。`resource.kind` と `levels`、そして `op`。**操作は種類ごとに決まっている** (`resource-kinds.yaml` の `kinds.<kind>.ops[].id`)。段の名前も同じファイルのとおり。分からない段は書かず、主張全体を `unknown` + `reason` にする

     | 種類 | 操作 |
     |---|---|
     | rdb | create / read / update / delete |
     | kvs | get / set / delete / expire |
     | queue | publish / consume |
     | filesystem | read / write / append / delete / list |
     | object_storage | get / put / delete / list |
     | external_api | call |
   - 次の層の呼び出しを見つけたら、新しいフレームを足して `caller` で指す。`role: boundary` の層 (外部ライブラリ・SDK・CLI) に達したらそこで閉じる
5. 辿れないところは **unknown + reason** で明示する (`context.md` の典型例に従う)。推測で埋めない
   - `not_analyzed` (手順がそこまで届いていない) で止めるときは、`note` に「どこまで読んだか」と「なぜ止めたか」を書く (続きを分析するかを、人が決められるように)。打ち切ってよい範囲を、分析リポジトリの `analysis-conventions.md` やプロファイルの `context.md` が決めていれば、それに従う
6. `summary` (入口全体の概要) と `analyzer` (profile の id / version、`skill_version` はこの SKILL.md 末尾の版、`model` に使ったモデル、`analyzed_at` は結果を書き終えた時点の実際の時刻。`date -u +%Y-%m-%dT%H:%M:%SZ` で取り、見込みの時刻を書かない。レビューの後に結果を直したら、直し終えた時刻に書き換える) を書く。`target` は `analysis/work-definition.yaml` と同じ
   - YAML の文字列 (summary の value、name、note、detail) は二重引用符で囲む。コロンや `#` を含む文章を裸で書くと読めなくなる
   - 結果のいちばん上の `notes` (任意) には、迷った点と選んだ扱い、直さなかったレビューの指摘と理由を書く
   - `analyzer.run` (コスト・所要時間) は**書かない**。実行中のセッションは自身のコストを知れない。呼び出した側が後で書く
7. 機械チェック: `<abatlas> validate result analysis/results/<file> --work analysis/work-definition.yaml` (プロファイルは、作業定義の `profile.dir` から自動で読まれる。出力に「プロファイルを自動で読めない」と出たら、OK でも完了にしない (プロファイルとの突き合わせが省かれている)。`analysis/work-definition.yaml` の `profile.dir` と、その場所の `profile.yaml` を確かめて直す)
   - NG なら指摘に従って YAML を直す (根拠の行番号の誤りは実ファイルで確かめて直す)。OK になるまで繰り返す
8. レビュー: **フレッシュなサブエージェント**に `abatlas-review-entry` を同じ入口 id で実行させ、`analysis/reviews/<file>` を `<abatlas> validate review ... --result ...` で確かめてから指摘を読む (読めない YAML なら、サブエージェントに直させる)
   - `severity: high` 以上の指摘は、必ず直す。medium と low は、直すか、直さない理由を結果の `notes` に書く
   - 直した指摘には、レビューのファイルの該当の指摘に `resolved: true` を書く (分析の側がレビューのファイルに書いてよいのは、この項目だけ。指摘の文や `where` は書き換えない。直した後に `where` の指す場所が動いても、そのままでよい)
   - 直したら、7 (機械チェック) をやり直す
   - **もう一度レビューするのは、high を直したときだけ、1 回だけ**。フレッシュなサブエージェントに、同じ入口で実行させる (レビューのファイルは、新しい結果で置き換わる)。2 回目の指摘も同じ扱いで直すが、3 回目のレビューはしない。medium と low だけを直したときは、もう一度レビューしない
   - 最後に、結果の `analyzer.reviewed` を書く: `by` は、最後のレビューのファイルの `reviewer` の値。`at` は、同じファイルの `reviewed_at` の値。`findings_open` は、最後のレビューの指摘のうち、`resolved: true` でないものの数
9. 報告: フレーム数、I/O 件数、unknown の件数と理由の内訳、レビューで直した点

## 完了条件

- `analysis/results/<file>` が機械チェック OK
- `analysis/reviews/<file>` があり、`analyzer.reviewed.findings_open` が書かれている
- unknown の主張すべてに `reason` と、必要なら `note` (何を見て分からなかったか) がある

## 禁止

- 対象リポジトリのファイルを変える
- `analysis/entry-list.yaml` を変える
- 根拠の無い `fact`。読んでいないファイルを evidence に書く
- scope の外のファイルを evidence に書く (外なら `out_of_scope`)

## 参照

- 形式: `<oss>/schema/analysis-result.schema.json`、説明: `<oss>/docs/architecture/formats.md` (文書の地図は同じ場所の `README.md`)
- skill_version: 0.3.0
  - 0.3.0: I/O の操作 (`op`) をデータの種類ごとの語彙にした (ファイルは read / write / append / delete / list、KVS は get / set / delete / expire、キューは publish / consume、オブジェクトストレージは get / put / delete / list)。0.2.0 の結果はファイルの `create` / `update` を `write` に読み替えれば移せるが、再分析の対象になる
  - 0.2.0: 分析リポジトリの `.agents/memory/desired-state/analysis-conventions.md` を最初に読み、`context.md` より優先する手順を追加。`analyzer.run` は書かない規則を明記。結果ファイル名 `<file>` の規則を明記 (0.1.0 の結果は再分析の対象になる)
  - 0.1.0: 最初の版
