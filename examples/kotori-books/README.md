# ことり書店 (kotori-books) のバッチ

as-built-atlas の公開サンプル。**架空**のオンライン書店「ことり書店」の夜間・定期バッチを、Kestra の Flow として組んだものです。
実在の会社・サービス・人物とは関係ありません。外部 API のホストは予約ドメイン `.example` です。

このリポジトリは分析される側 (対象) です。分析リポジトリは隣の `kotori-books-atlas/`。
as-built-atlas の `examples/generator/kotori_books.py` が、このコードと正解の分析結果 YAML を同じ仕様から生成しています。

## 構成

```text
flows/<namespace>/<flow>.yaml   Kestra の Flow (入口)。namespace は daily / daily.sales / ... / lib
scripts/run_job.sh              共通ランナー。設定を読み、python3 -m jobs.<job> を実行してログに追記する
scripts/db_snapshot.sh, rotate_logs.sh   シェルだけで完結するジョブ
jobs/<job>.py                   ジョブ本体 (PostgreSQL / Redis / S3 / 外部 API / キュー を読み書きする)
jobs/lib/                       共有の薄いラッパー (db / cache / storage / http / mq / notify)
jobs/settings.py                接続先の既定値とバケット名・ディレクトリ
config/prod.env                 本番の設定 (秘密は含まない)。config/digests.yaml はダイジェストの対象
sql/reports/*.sql.j2            実行時に組み立てる SQL のテンプレート
bin/legacy_pricing              ソースの無いバイナリの代わり (読めない成果物の例)
```

## Flow の一覧 (34 本)

| namespace | 本数 | flow |
|---|---|---|
| `daily` | 6 | close_day, fx_rates, data_quality_checks, digest, db_snapshot, rotate_logs |
| `daily.sales` | 5 | settle_orders, sales_report, product_ranking, coupon_expiry, refund_returns |
| `daily.inventory` | 4 | reconcile_stock, import_supplier_feeds, reorder_alerts, sync_search_index |
| `daily.customer` | 4 | segment_customers, send_cart_reminders, review_moderation, wishlist_price_drop |
| `hourly` | 4 | sync_shipments, abandoned_carts_snapshot, consume_stock_events, mail_queue_worker |
| `weekly` | 6 | close_week, cohort_retention, supplier_statements, tax_rate_refresh, legacy_price_sync, archive_old_orders |
| `monthly` | 4 | monthly_kpi, custom_reports, invoice_batch, purge_sessions |
| `lib` | 1 | notify_failure |

`daily.close_day` と `weekly.close_week` は Subflow で他の Flow を順に呼ぶ親。`daily.sales.settle_orders` などトリガの無い Flow は親からだけ呼ばれる。
`lib.notify_failure` は親の `errors` から呼ばれる。

## 分析の見どころ (正解 YAML に入れてある「不明」)

| 入口 | 不明 | 理由 |
|---|---|---|
| チャット通知を使う全ジョブ | Webhook の宛先 | `not_traceable_in_repo` (環境変数 `KOTORI_CHAT_WEBHOOK`) |
| `daily.customer.review_moderation` | 判定 API のホスト | `not_traceable_in_repo` (環境変数 `KOTORI_MODERATION_API_HOST`) |
| `daily.digest` | (不明ではない) | 読むディレクトリは `config/digests.yaml` に列挙されているので、1 ディレクトリずつ `fact` (根拠は設定の行) |
| `monthly.invoice_batch` | 書くディレクトリ | `dynamic_dispatch` (顧客コードで決まる) |
| `monthly.custom_reports` | 読むテーブルと書くファイル | `generated_at_runtime` (SQL が DB に保存されていて、リポジトリには無い)、`dynamic_dispatch` (ファイル名は定義の name) |
| `monthly.monthly_kpi` | (不明ではない) | Jinja テンプレートから SQL を組み立てるが、表名はテンプレートに静的に書かれているので `fact` (根拠はテンプレートの行) |
| `weekly.legacy_price_sync` | バイナリの中身 | `binary_or_vendored` |

このコードは読まれるために書いたもので、実行は想定していません (接続先は架空)。各ジョブの `--dry-run` は DB・ファイル・S3・キュー・キャッシュへの書き込みと通知を止め、読み取りと外部 API への問い合わせ以外の副作用を残しません (外部 API の呼び出しも `dry_run` で飛ばします)。
