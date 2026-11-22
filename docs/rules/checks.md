# 開発時・コミット時・CI の機械チェック

このリポジトリのチェックは `scripts/check` で実行する。uv と mise を用意し、リポジトリのルートで次を実行する。イメージのビルドと検査には Docker も使う。

```bash
mise trust
mise install
uv sync --locked --dev
uv run --locked playwright install --only-shell chromium
git config --local core.hooksPath .githooks
mise exec -- scripts/check dev
```

既に Git フックを管理している場合は、既存の pre-commit から `.githooks/pre-commit` を呼び出す。

## 場面ごとの実行モード

`scripts/check <モード>` で、その場面のチェック一式を実行する。1 種類だけ実行する場合は、末尾にチェック名を付ける。

| チェック | 開発中 `dev` | コミット時 `hook` | PR の CI `pr` | main の CI `main` |
|---|---|---|---|---|
| generate | 全量 | — | 全量 | 全量 |
| format | HEAD からの差分を自動整形 | ステージした差分を確認 | PR の差分を確認 | 全量を確認 |
| lint | HEAD からの差分 | ステージした差分 | PR の差分 | 全量 |
| build | 個別指定時のみ | — | イメージをビルド | イメージをビルド |
| test | pytest 全件 | ステージ内容で文書テスト全件 | pytest 全件 | pytest 全件 |
| security（Gitleaks） | ローカル変更 | ステージした差分 | PR のコミットとローカル変更 | Git 全履歴とローカル変更 |
| security（Trivy） | `uv.lock` | — | `uv.lock` とビルドしたイメージ | `uv.lock` とビルドしたイメージ |

generate は製品別の設定とことり書店の見本を再生成して照合する。開発時は format の後に generate を実行する。pytest 全件には文書テストと Chromium での画面テストも含む。Linux の新規環境では Playwright の install に `--with-deps` を付ける。Gitleaks のローカル変更には作業ツリー、ステージ、Git が無視していない新規ファイルを含む。

GitHub Actions は PR の比較元コミットを `CHECK_BASE` で渡す。手元で `pr` を実行したときの既定の比較元は `origin/main`。別のブランチ向けの PR を再現するときは `CHECK_BASE` にその参照または SHA を指定する。

```bash
mise exec -- scripts/check dev          # 開発中の一式
mise exec -- scripts/check hook test    # コミット候補の文書テストだけ
mise exec -- scripts/check pr           # 手元で PR の CI を再現
mise exec -- scripts/check main lint    # 全量の lint だけ
```

コミット時は Gitleaks が通った後、ステージ内容を一時チェックアウトし、Qlty が format と lint を一度で検査する。指摘があるとコミットを止める。対象ファイルを直し、コミットに含める箇所をもう一度ステージする。部分ステージしたファイルの未ステージ部分はそのまま保たれる。Qlty の設定もステージした版を使うため、初回導入時は `.qlty/` の設定をコミット対象に含める。

Qlty のプラグインは `qlty init` の選定結果を `.qlty/qlty.toml` に記録する。Python は Ruff、dbt SQL は SQLFluff、Markdown は markdownlintで整形と lint を実行する。秘密と依存の検査は Gitleaks と Trivy が担当する。生成済みのアダプターとことり書店の見本は generate で照合する。ほかの公開見本は pytest で検査する。

## ティアごとの検査範囲

| このリポジトリの対象 | format・lint | テスト・ビルド | リファクタの見直し材料・検査の限界 |
|---|---|---|---|
| CLI・バックエンド（Python の検証・ETL・API・MCP） | Ruff、RadarLint、Bandit | pytest で入力検証、変換、API・MCP の応答と見本を検査 | 関数の循環的複雑度と認知的複雑度 |
| データ（dbt・DuckDB） | SQLFluff が core とプロファイルの SQL を DuckDB 方言で整形・検査 | pytest が見本で ETL → `dbt build` を実行。seed・モデル・定義済みデータテスト・集計結果・列の宣言を検査 | モデル別の JOIN・CTE・直接依存数。データテストの対象は YAML などでテストを定義した列・条件 |
| Web 画面（JavaScript・HTML・CSS） | Prettier と Biome。関数の循環的複雑度も検査 | pytest から Chromium を起動し、見本の API を使って広幅・狭幅で入口に移動する | 見た目の確認は2種類の見本で行う |
| 公開サイト（`site/`） | Prettier と Biome。JavaScript は複雑度も検査 | Chromium で日英の切替、タブ移動、動画の再生・停止、読み込み失敗時の表示を検査 | 動きを減らす設定、タッチ操作、複数の画面幅を含む |
| 形式・プロファイル・文書 | JSON は Prettier と Biome、YAML は Prettier と yamllint、Markdown は markdownlint | pytest が形式・意味・見本・文書リンクを検査。generate が生成物を照合 | YAML の重複キーも検査 |
| エージェント設定（mid-harness） | 取り込んだ Python とシェルにも同じ format・lint を適用 | pytest が同梱のアダプター・フックの回帰試験を実行し、generate で製品別設定の一致を検査 | 正本を上流で修正し、取り込んだ版と Git コミットを `VENDOR.md` に記録 |
| 開発・配布（シェル・Actions・イメージ） | shfmt、ShellCheck、actionlint、zizmor、dockerfmt、Hadolint | CI のイメージビルド、Gitleaks と Trivy は上表の範囲 | 週次は配布済みイメージも検査 |

dbt の SQL は `dbt-template/` と `profiles/*/dbt-template/` にある正本を調べる。SQLFluff は Jinja の dbt 組み込みを使い、構文、空白、末尾改行、未使用 CTE、ネストした CASE、NULL の比較を検査する。マクロ展開や参照の解決、DuckDB での実行結果は合成後の実ビルドで確認する。フックはステージした SQL の静的検査まで、開発・PR・main は pytest から実ビルドまで行う。

## 関数の複雑度とリファクタ候補の一覧

循環的複雑度は関数ごとに **10 まで**とし、11 以上で lint が失敗する。4 モードとも Qlty の同じ指標を使う。開発中と PR は変更したソースファイル内の全関数、フックはステージした版の変更ファイル内の全関数、main は全ソースファイルが対象。Qlty が関数として解析できるソース（現在は Python・JavaScript）を計測し、テストと設定で除外した生成物は対象外とする。

```bash
mise run complexity                        # 作業ツリー全体の関数一覧
mise run complexity > /tmp/complexity.tsv  # 表計算ソフトでも開ける TSV
```

一覧には循環的複雑度、Qlty の認知的複雑度、ファイル、関数名を出す。循環的複雑度の降順で、同値なら認知的複雑度の高い順に並ぶ。一覧の出力は上限を超えていても成功する。Python の認知的複雑度は引き続き RadarLint の S3776 が上限 15 で判定する。

リファクタを検討するときは、値が大きい関数の分岐を読み、別々に変わる業務ルールが混在しているか、分岐に対応するテストがあるかを確認する。

### dbt モデルの一覧

```bash
mise run complexity-dbt                               # 配布モデルの一覧
mise run complexity-dbt > /tmp/dbt-models.tsv          # TSV で保存
mise run complexity-dbt path/to/target/manifest.json   # 分析リポジトリの repo 独自モデルも含む
```

引数を省略すると、プロファイルの dbt テンプレートごとに core と合成し、seed のヘッダーを用意した一時プロジェクトで `dbt compile` する。プロファイル別テンプレートがなければ core を一度調べる。既存の manifest を渡す場合は、対象プロジェクトを全量 compile または build したものを使う。

一覧はコンパイル後の各 SQL モデルを1行とし、DuckDB 方言の構文木で数えた JOIN、CTE、manifest に記録された直接依存ノード（モデル・seed・source など）の順に降順で並ぶ。モデル識別子、合成したプロジェクト内のファイルパス、対象プロファイルも表示する。件数は調査の優先順位を決める材料とし、SQL の合否は SQLFluff と dbt のテストで判断する。

## Markdown の整形・lint・テスト

開発中は `dev format` で Markdown の空行やリストの間隔などを自動修正し、`dev lint` で見出しの階層などを検査する。フックと CI は読み取り専用で検査する。日本語の段落の長さと既存の表の列間隔は自由とし、表内の改行と翻訳 README のアンカーを許可する。設定はルートの `.markdownlint.json` にある。

文書テストはルートの `*.md` と `docs/**/*.md` にあるリンクと画像の参照先（参照形式を含む）、配布先で切れるリンク、Mermaid の一部の記法を検査する。画像だけを削除しても参照元の文書のリンクが切れるので、差分モードでも文書テストは全件読む。開発と CI は pytest から、フックはステージ内容の一時チェックアウトで同じ検査を呼ぶ。外部 URL の疎通と図の描画はこのテストの対象外。

## 週次の脆弱性スキャン

毎週月曜 09:17（日本時間）、GitHub Actions の **Weekly vulnerability scan** がデフォルトブランチの `uv.lock` と、GHCR で配布中の `latest` を Trivy で全量検査する。リリース後に公表された脆弱性も、コードの変更や再ビルドを待たずに検出する。ワークフローの画面から手動でも実行できる。

公開タグの digest を一度だけ確定し、同じ版の linux/amd64 と linux/arm64 を調べる。例外の判定には配布イメージが記録したコミットの依存関係と、現在の例外一覧を使う。各回の Summary に対象、脆弱性 ID、深刻度、導入版を表示する。修正版がある指摘には対応版も表示し、有効な例外を除いて実行を失敗にする。修正版がない指摘は Summary に件数を載せ、ログに `UNFIXED` として全件を載せる。失敗通知の受け取り先は GitHub の Actions 通知設定に従う。[GitHub Actions のスケジュール](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)

## Trivy の判定と例外

Trivy が修正版を返した指摘は、深刻度が LOW や UNKNOWN でも失敗する。スキャナーの異常終了、ロックファイルや OS を解析できなかった場合も失敗する。リリースでは amd64 と arm64 を個別に検査し、両方が通った OCI イメージをそのまま配布する。

推移的依存を更新できないときは、上流のリリースと依存制約を確認し、`.trivy-exceptions.toml` に次の形式で記録する。下記は架空の記入例。最初の項目を追加するときは空の `exception = []` を置き換える。

```toml
[[exception]]
id = "CVE-2099-12345"
purl = "pkg:pypi/example-child@1.0"
target = "uv.lock"
parent = "example-parent"
upstream = "pypi/example-parent"
parent_release = "2.3.0"
reason = "直接依存の公開版が child < 2 を要求し、修正版の 2.0 と両立しない。"
evidence = "https://upstream.example/releases/2.3.0/dependencies"
expires = 2099-01-01
```

- 指摘 ID、バージョンを含むパッケージ URL、Trivy の対象名がすべて一致する箇所だけを除外する。対象名はロックファイルなら `uv.lock`、イメージ内の Python なら `Python`、バイナリならそのパス。
- Python は uv.lock の直接依存からの到達性と、上流の最新版を確認する。上流版と修正版を uv で同時に解決できればエラーに戻す。イメージではアプリの仮想環境にある同じパッケージだけが対象になる。
- コンパイル済みのバイナリは Trivy の依存グラフとルートの版を確認する。`upstream` は直接依存を配布する `github/所有者/リポジトリ`、`parent_release` はそのリリースタグに合わせる。レビューでは根拠 URL と配布元の対応も確認する。
- 直接依存の新版が出たとき、期限日（UTC）を迎えたとき、または上流を確認できないときは失敗する。OS パッケージはイメージのビルドで更新する。

判定の経緯は [ADR 0031](../adr/0031-machine-checks.md) にある。ツールの仕様は [Qlty CLI](https://github.com/qltysh/qlty)、[Gitleaks](https://github.com/gitleaks/gitleaks)、[Trivy の脆弱性検査](https://trivy.dev/docs/latest/scanner/vulnerability/) を参照する。
