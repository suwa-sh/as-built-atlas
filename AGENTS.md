# AGENTS.md

このファイルは、すべてのコーディングエージェントが共有する行動契約と、知識の読み分けルールの正本です。

## 行動契約

- 変更は小さく、目的ごとに commit する
- 推測で設定やライブラリの使い方を変えない。公式ドキュメントで確認してから変更する
- 破壊的な操作 (削除、履歴改変、外部への送信) は実行前に確認する
- テストが通っても、実物 (見本の分析リポジトリ、ブラウザ) で確かめるまで完了にしない
- 決定を変えたら、経緯を ADR (`docs/adr/`) に書き、守るべき最新の状態を `docs/` に書く。`docs/` は、人とエージェントの両方が読む
- 作業中に得た、今後の作業でも理解しておくべきことは、agent memory (`.agents/memory/`) に書く。agent memory は、エージェントだけが読む
- 作業が終わったら、学び、リファクタの案、残っている作業を、番号を振って挙げる (番号で選べるようにする。リファクタをやるかどうかは、人が決める)

## 標準コマンド

開発時の機械チェックは `mise exec -- scripts/check dev`、main と同じ全量検査は `mise exec -- scripts/check main`。セットアップ、Git フック、個別の検査は[機械チェックのルール](docs/rules/checks.md)を参照する。

```bash
uv sync                                   # 依存を入れる (Python 3.11+ / uv)
uv run pytest -q                          # コアのテスト
uv run abatlas validate profile profiles/<id>/profile.yaml
uv run abatlas validate result <result.yaml> --profile profiles/<id>/profile.yaml --work <work-definition.yaml>
uv run abatlas enumerate <entry-list.yaml> --profile profiles/<id>/profile.yaml
uv run abatlas init <分析リポ> --profile <id>   # 分析リポジトリの初期化 (OSS 所有の配置 + 中ハーネス 6 製品)。開発中の確認用
uv run abatlas migrate <分析リポ> [--dry-run]   # 前の形式の項目名を、いまの形式に書き換える (分析する側のファイルだけ。値は変えない。文の中の「(tier: <id>)」だけ直す)
uv run abatlas dictionary <分析リポ>            # 分析結果に出てきた列を、データの辞書に candidate で足す (区分は決めない)
uv run abatlas diff <分析リポ> --from <git の版>   # 前の分析結果と、いまの分析結果を比べる (入口ごとに、足されたものと消えたもの)
uv run abatlas build <分析リポ>                 # ETL → dbt build (派生物は <分析リポ>/analysis/data/)
uv run abatlas serve <分析リポ>                 # webapp + 集計表 API + MCP (http://127.0.0.1:8765, /mcp)
uv run abatlas evaluate <results> --truth <truth>   # 分析結果を正解と突き合わせる (適合率 / 再現率)
uv run python examples/generator/kotori_books.py    # 公開サンプル (対象 + 正解 YAML) の再生成。仕様を変えたら再生成して commit (tests/test_examples.py が差を検出する)
docker build -t ghcr.io/suwa-sh/as-built-atlas:dev .   # 配布物 (コンテナイメージ)。分析リポジトリはこれだけに依存する
```

分析リポジトリ側の使い方 (docker compose) は `docs/architecture/analysis-repo.md`。配布物の中身を変えたら、イメージを作り直して、手元の確認用の分析リポジトリで `docker compose run --rm abatlas upgrade .` を試す。

## このリポジトリの約束

- 正本は `schema/` (JSON Schema と語彙)。schema を変えたら `tests/fixtures/` の見本と `abatlas/validate.py` の意味検査も合わせて直し、`docs/architecture/` の説明 (形式は `formats.md`、地図は `README.md`) を更新する
- 決定論でできることは決定論で行う。抽出器・列挙・機械チェック・ETL・集計はスクリプトにし、エージェントに任せるのは、入口を見つけること (抽出器の設定を書き、抽出器で取れない入口を根拠付きで足す) と、各フレームの概要だけ
- skill (`.agents/skills/`) は agent skills の規約の範囲で書き、特定製品のツール名を書かない
- 公開されていない対象の分析結果は、このリポジトリに入れない (試すときの置き場 `spike/` は gitignore)
- 計画、進み具合の記録、検討の途中の資料、手元の絶対パス、個人の情報は、このリポジトリに入れない
- 公開サンプル (`examples/kotori-books*`) は手で直さず、`examples/generator/kotori_books.py` を直して再生成する。架空の題材で、実在の会社・サービス・人物を含めない (外部ホストは `.example`)
- 見本 (`examples/*-atlas/`) は、プロファイルごとに 1 つ持つ (`tests/test_examples_profiles.py` が確かめる)。ことり書店のほかは、公開されているソフトを AI が分析した実例。入れるのは分析リポジトリの資産 (作業定義・入口の一覧・分析結果・レビュー) だけで、対象のコードは入れない。手で直さず、手元の分析リポジトリで分析し直した結果を `examples/generator/import_atlas.py` で写す。手元の絶対パスや個人の情報を残さない (`clone_path` は `../<対象の clone の名前>`)。見本の README に、対象とそのライセンスを書く
- 見本を足すのは、プロファイルを足すときだけ (同じプロファイルに 2 つ目を足さない)。公開されていない対象の分析結果は、見本にしない

## 知識の読み分け

- このリポジトリを直すときは、skill `dev-change` の流れに従う。触る部分ごとのルールは `docs/rules/README.md` の表から選ぶ
- 決定の経緯は `docs/adr/`、いま守ることは `docs/architecture/` (仕組み) と `docs/rules/` (開発のルール)
- リポジトリ知識の全体像が必要なときは `docs/README.md` から辿る
- 作業開始時に `.agents/memory/index.md` を読み、対象タスクに必要なリンクだけを追加で読む
- スキル実行時は、そのスキルの `SKILL.md` と参照された資料を優先する
- 新しいトラブルシューティングは、まず該当スキルの `references/` へ記録する
- 複数スキルに影響する場合は `.agents/memory/troubleshooting/` へ昇格する

## 中ハーネスの構成

この repository は portable core (`AGENTS.md` / `docs/` / `.agents/`) と、そこから生成した製品別 adapter (`.claude/` / `.codex/` など) に分かれています。adapter は手修正せず、`.agents/harness.yaml` と core を直して再生成します (mid-harness skill の `audit` でドリフトを検査します)。
