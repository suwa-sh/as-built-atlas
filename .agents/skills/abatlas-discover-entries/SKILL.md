---
name: abatlas-discover-entries
description: 分析対象リポジトリの「入口」(ジョブ・エンドポイント・画面) を列挙するための抽出器とパラメータを決め、entry-list.yaml の extractors に書く。入口一覧を作りたい・抽出器の設定を決めたい・列挙結果を見直したいときに使う。
---

# 入口パターンの発見 (抽出器の設定を書く)

入口の一覧そのものは作らない。**どの抽出器を、どのパラメータで使うか**を決めて `entry-list.yaml` に書き、列挙ツール (決定的) に候補を出させる。承認は人が行う。

## 入力

- 分析リポジトリのルート (カレントディレクトリ)。`analysis/work-definition.yaml` が必須
- 分析の資産は `analysis/` の下: `analysis/work-definition.yaml`、`analysis/entry-list.yaml`、`analysis/results/`、`analysis/reviews/`
- OSS の参照物 `<oss>`: カレントディレクトリに `.abatlas/` があればそれ (分析リポジトリ)。無ければこの SKILL.md の実体の 3 つ上 (OSS の checkout)
- ツールの呼び方 `<abatlas>`: 分析リポジトリでは `docker compose run --rm abatlas` (コンテナの中で動く。パスはリポジトリのルートからの相対で書く)。OSS の checkout では `uv run abatlas`
- プロファイル: `analysis/work-definition.yaml` の `profile.dir`。無ければ `<oss>/profiles/<profile.id>/`

## 前提

- 分析リポジトリでは Docker が動き、`.env` の `ABATLAS_TARGET` が対象の clone を指している (`<abatlas>` はそれを `/ws/target` として読む)。OSS の checkout では `uv sync` 済み
- 対象は `analysis/work-definition.yaml` の `target.clone_path` に clone 済みで、`target.commit` が checkout されている (`git -C <clone_path> rev-parse HEAD` で確かめる。違えば止めて人に伝える)

## 手順

1. プロファイルを読む: `profile.yaml` (層、`extractors[]` の候補と `hint`、`hierarchy.derivation`) と `context.md` (入口の判別の節)
2. 対象を調べる: `target.clone_path/target.scope` の中で、プロファイルの `extractors[].hint` に従って定義ファイルの置き場・形式・必須項目を確かめる。`rg` / `find` / 実ファイルの先頭を読む程度にとどめ、全ファイルを読まない
3. `analysis/entry-list.yaml` を作る (無ければ)。`format_version: 1`、`target` は `analysis/work-definition.yaml` と同じ、`profile.id` と `profile.version` は `profile.yaml` から、`entries: []`
4. `extractors[]` を書く。プロファイルの既定パラメータを出発点に、このリポジトリに合わせて `files` の glob・フィールドの式・`post` を埋める。各抽出器に `rationale` (なぜこの設定か) を 1〜2 文で書く
5. 試す: `<abatlas> enumerate analysis/entry-list.yaml --dry-run` (プロファイルは、作業定義の `profile.dir` から自動で読まれる。読んだ場所が出力の最初に出る。「自動で読めない」と出たら、`profile.dir` を直す)
   - 失敗したら標準エラーの指摘 (契約違反・schema 違反) に従って設定を直す。抽出器のコードは直さない
   - 件数と階層パスの分布を見て、明らかな漏れ (定義ファイルがあるのに出ない) や重複 (同じ入口が別 id) があれば設定を見直す
6. 本番の列挙: `--dry-run` を外して実行する。`entries[]` に `status: candidate` で候補が書かれる
7. 人に渡す報告を書く (標準出力でよい): 件数、階層の第 1 段ごとの内訳、既定パラメータから変えた点とその理由、抽出器に当たらなかったが入口かもしれないもの (気付いた範囲で)

## 完了条件

- `<abatlas> validate entries analysis/entry-list.yaml` が OK。出力に「プロファイルを自動で読めない」と出たら、OK でも完了にしない (プロファイルとの突き合わせが省かれている)。`analysis/work-definition.yaml` の `profile.dir` と、その場所の `profile.yaml` を確かめて直す
- `entries[]` が 1 件以上あり、すべて `status: candidate` (承認は人の作業。このスキルでは `approved` にしない)
- 各抽出器に `rationale` がある

## 禁止

- `entries[]` を手で書く・直す (列挙ツールの出力だけが正)
- `status` を `approved` / `rejected` に変える
- 抽出器 (配布物の `abatlas/extractors/` やプロファイルの `extractors/`) のコードを変える。足りなければ、その旨を報告して止める

## 参照

- 抽出器の契約と `params` の書き方: `<oss>/docs/architecture/profiles.md` の「抽出器の契約」、`<oss>/schema/entry-candidate.schema.json`、プロファイルの `profile.yaml` の `extractors[]` (既定の params と hint)
- 入口一覧の形式: `<oss>/schema/entry-list.schema.json`
