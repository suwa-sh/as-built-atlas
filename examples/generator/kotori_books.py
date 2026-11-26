"""公開サンプル「ことり書店」(架空のオンライン書店) の Kestra バッチと、その正解 YAML を生成する。

対象 (分析される側) と正解 (分析結果 YAML) を同じ仕様から作るので、根拠の行番号は構成上ずれない。
生成物は examples/kotori-books/ (対象) と examples/kotori-books-atlas/analysis/ (分析リポジトリの資産) に置き、
そのまま commit する (利用者は生成を実行しなくてよい)。

    uv run python examples/generator/kotori_books.py            # examples/ に書く
    uv run python examples/generator/kotori_books.py --out DIR  # DIR/kotori-books と DIR/kotori-books-atlas に書く (テスト用)

仕様を変えたら再生成して commit する。tests/test_examples.py が「生成物が最新か」を確かめる。
"""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

VAR_BACKUP = "var/backup"
SHOP_ORDERS = "shop.orders"
SHOP_ORDER_ITEMS = "shop.order_items"
SHOP_PAYMENTS = "shop.payments"
WAREHOUSE_STOCK = "warehouse.stock"
SHOP_PRODUCTS = "shop.products"
MART_DAILY_SALES = "mart.daily_sales"
DAILY_SALES = "daily.sales"
SHOP_CUSTOMERS = "shop.customers"
V3_MAIL_SEND = "/v3/mail/send"
AUDIT_MAIL_LOG = "audit.mail_log"
MAIL_LOG_COLUMNS = "sent_at, template, customer_id, provider_message_id"
MAIL_LOG_DESCRIPTION = "送ったメールの記録"
DAILY_INVENTORY = "daily.inventory"
WAREHOUSE_STOCK_MOVEMENTS = "warehouse.stock_movements"
VAR_INBOX_SUPPLIERS = "var/inbox/suppliers"
CSV_GLOB = "*.csv"
WAREHOUSE_SUPPLIERS = "warehouse.suppliers"
SHOP_PRODUCT_PRICES = "shop.product_prices"
DAILY_CUSTOMER = "daily.customer"
MART_CUSTOMER_SEGMENTS = "mart.customer_segments"
MAIL_RATE_LIMIT_KEY = "ratelimit:mail:{customer_id}"
WEEK_START_HELP = "週の初日 (月曜)"
MONTH_HELP = "対象月 (YYYY-MM)"
JOBS_LIB_DB_PY = "jobs/lib/db.py"
JOBS_LIB_CACHE_PY = "jobs/lib/cache.py"
JOBS_LIB_STORAGE_PY = "jobs/lib/storage.py"
JOBS_LIB_HTTP_PY = "jobs/lib/http.py"
JOBS_LIB_MQ_PY = "jobs/lib/mq.py"
SCRIPTS_RUN_JOB_SH = "scripts/run_job.sh"
FUTURE_ANNOTATIONS_IMPORT = "from __future__ import annotations"
SETTINGS_IMPORT = "from jobs import settings"
JOBS_LIB_NOTIFY_PY = "jobs/lib/notify.py"
TESTS_TEST_NOTIFY_PY = "tests/test_notify.py"
CONFIG_DIGESTS_YAML = "config/digests.yaml"
BIN_LEGACY_PRICING = "bin/legacy_pricing"
IF_WRITES_ENABLED = "    if not args.dry_run:"
VAR_LOG_JOBS = "var/log/jobs"


HERE = Path(__file__).resolve().parent
OSS_ROOT = HERE.parent.parent
sys.path.insert(0, str(OSS_ROOT))

from abatlas.enumerate import enumerate_entries  # noqa: E402
from abatlas.schemas import load_yaml  # noqa: E402

TARGET_NAME = "kotori-books"
ATLAS_NAME = "kotori-books-atlas"
PROFILE_ID = "batch-kestra"
PROFILE_VERSION = "0.1.0"
SKILL_VERSION = "0.4.0"
ANALYZED_AT = "2026-11-08T12:00:00+09:00"
ANALYST = "as-built-atlas examples/generator (対象と同じ仕様から生成した正解)"

DB = {"host": "db.internal", "dbms": "postgresql", "database": "kotori"}
CACHE = {"host": "cache.internal", "instance": "0"}
BROKER = "mq.internal"
HOSTS = {
    "PAYMENT_API_HOST": "api.payment.example",
    "CARRIER_API_HOST": "api.carrier.example",
    "MAIL_API_HOST": "api.mail.example",
    "TAX_API_HOST": "api.tax.example",
    "FX_API_HOST": "api.fx.example",
    "SEARCH_HOST": "search.example",
    "PUSH_API_HOST": "api.push.example",
    "RECOMMEND_API_HOST": "api.recommend.example",
}
BUCKETS = {
    "REPORTS_BUCKET": "kotori-reports",
    "EXPORTS_BUCKET": "kotori-exports",
    "BACKUPS_BUCKET": "kotori-backups",
}
DIRS = {
    "EXPORT_DIR": "var/export",
    "INBOX_DIR": "var/inbox",
    "LOG_DIR": "var/log",
    "TMP_DIR": "var/tmp",
    "BACKUP_DIR": VAR_BACKUP,
}


# ---------------------------------------------------------------- 仕様 (I/O の短い書き方)


def rdb_read(
    *tables: str,
    detail: str | None = None,
    unknown: str | None = None,
    note: str | None = None,
    template: bool = False,
    stored: bool = False,
    where: str | None = None,
    select: list[str] | None = None,
    params: str | None = None,
) -> dict:
    """template: SQL をテンプレートから組み立てる (表は静的に読める → fact)。stored: SQL が DB の中にある (表は読めない → unknown)。
    where: WHERE 句 (既定は前日 1 日分の窓)。select: SELECT 文を行ごとに書く (集計・分類を実装するとき。表が出てくる行が根拠)。params: 実引数の式。"""
    return {
        "kind": "rdb",
        "op": "read",
        "tables": list(tables),
        "detail": detail,
        "unknown": unknown,
        "note": note,
        "template": template,
        "stored": stored,
        "where": where,
        "select": select,
        "params": params,
    }


def rdb(
    op: str,
    table: str,
    cols: str,
    detail: str | None = None,
    params: tuple | None = None,
) -> dict:
    """update の params は SET の %s に渡す行のキー (省略時は代入先の列名)。"""
    return {
        "kind": "rdb",
        "op": op,
        "table": table,
        "cols": cols,
        "detail": detail,
        "params": params,
    }


def rdb_fields(op: str, cols: str) -> list[dict]:
    """書き込みの SQL が触る列 (分析結果の io[].fields)。create は列の並び、update は SET の代入先と WHERE の id、delete は行ごと。"""
    if op == "create":
        return [{"name": c.strip(), "use": ["write"]} for c in cols.split(",")]
    if op == "delete":
        return [{"name": "*", "use": ["write"]}]
    out = []
    for part in cols.split(","):
        name, _, value = (x.strip() for x in part.partition("="))
        fl: dict = {"name": name, "use": ["write"]}
        if value.startswith("'") and value.endswith("'"):
            fl["set_to"] = value.strip("'")  # 決まった値を書く列 (状態の変化)
        out.append(fl)
    return out + [{"name": "id", "use": ["filter"]}]


def kvs(op: str, key: str, detail: str, ttl: str = "36 * 3600") -> dict:
    return {"kind": "kvs", "op": op, "key": key, "detail": detail, "ttl": ttl}


def fs(
    op: str,
    directory: str,
    file: str,
    detail: str,
    unknown: str | None = None,
    note: str | None = None,
    dirs: list[str] | None = None,
) -> dict:
    """dirs: 設定ファイルに列挙されたサブディレクトリ (静的に読めるので 1 つずつ fact にする)。"""
    return {
        "kind": "filesystem",
        "op": op,
        "directory": directory,
        "file": file,
        "detail": detail,
        "unknown": unknown,
        "note": note,
        "dirs": dirs,
    }


def py(*lines: str, rows: str | None = None) -> dict:
    """ジョブに差し込む Python の行 (I/O ではない。読んだ行を次の書き込みの形に整える)。rows はその結果の変数名。"""
    return {"kind": "py", "lines": list(lines), "rows": rows}


def s3(op: str, bucket_const: str, prefix: str, detail: str) -> dict:
    return {
        "kind": "object_storage",
        "op": op,
        "bucket_const": bucket_const,
        "prefix": prefix,
        "detail": detail,
    }


def api(
    method: str,
    host_const: str | None,
    path: str,
    detail: str,
    unknown: str | None = None,
    note: str | None = None,
) -> dict:
    return {
        "kind": "external_api",
        "op": "call",
        "method": method,
        "host_const": host_const,
        "path": path,
        "detail": detail,
        "unknown": unknown,
        "note": note,
    }


def mq(op: str, topic: str, detail: str) -> dict:
    return {"kind": "queue", "op": op, "topic": topic, "detail": detail}


@dataclass
class Flow:
    ns: str
    id: str
    desc: str  # Flow の description と入口の概要 (1〜2 文)
    cron: str | None = None  # None なら Subflow 専用 (トリガ無し)
    kind: str = "python"  # python | shell | orchestrator
    io: list = field(default_factory=list)
    inputs: list = field(default_factory=list)  # [(id, type, 説明)]
    subflows: list = field(
        default_factory=list
    )  # orchestrator: ["daily.sales.settle_orders", ...]
    on_error: str | None = None  # orchestrator: errors で呼ぶ Subflow
    labels: dict = field(default_factory=dict)
    binary: bool = False  # bin/legacy_pricing を呼ぶ (読めない成果物)
    template_sql: str | None = (
        None  # 実行時に組み立てる SQL のテンプレート (表名は静的に読める)
    )
    checks: bool = (
        False  # 読んだ表ごとに件数の検査結果を集め、それを書く (data_quality_checks)
    )
    concurrency: bool = True

    @property
    def full_id(self) -> str:
        return f"{self.ns}.{self.id}"

    @property
    def flow_file(self) -> str:
        return f"flows/{self.ns.replace('.', '/')}/{self.id}.yaml"


DATE_INPUT = ("date", "DATE", "処理対象日 (省略時は実行日)")

FLOWS: list[Flow] = [
    # ---- daily (日次の締めと保守)
    Flow(
        "daily",
        "close_day",
        "日次の締め。注文の決済確定 → 売上集計 → 在庫の突き合わせ を Subflow で順に呼ぶ。失敗時は lib.notify_failure に通知する",
        cron="0 1 * * *",
        kind="orchestrator",
        inputs=[DATE_INPUT],
        subflows=[
            "daily.sales.settle_orders",
            "daily.sales.sales_report",
            "daily.inventory.reconcile_stock",
        ],
        on_error="lib.notify_failure",
        labels={"owner": "commerce-platform", "criticality": "high"},
    ),
    Flow(
        "daily",
        "fx_rates",
        "為替レートを外部 API から取り込み、shop.exchange_rates に追加して Redis に当日分を置く",
        cron="15 0 * * *",
        labels={"owner": "commerce-platform"},
        io=[
            api(
                "GET", "FX_API_HOST", "/latest", "基準通貨 JPY で主要通貨のレートを取得"
            ),
            rdb(
                "create",
                "shop.exchange_rates",
                "rate_date, currency, rate",
                "取得した通貨ごとに 1 行",
            ),
            kvs("set", "fx:{currency}", "当日のレートを通貨ごとに置く"),
            kvs("expire", "fx:{currency}", "48 時間で失効", ttl="48 * 3600"),
        ],
    ),
    Flow(
        "daily",
        "data_quality_checks",
        "主要テーブルの前日分の行の有無を検査し (0 件なら ng)、検査ごとの結果を audit.data_quality に書いてチャットに通知する",
        cron="30 6 * * *",
        inputs=[DATE_INPUT],
        labels={"owner": "data-platform"},
        checks=True,
        io=[
            rdb_read(
                SHOP_ORDERS,
                SHOP_ORDER_ITEMS,
                detail="検査 orders_with_items: 前日の注文と明細の行の有無",
            ),
            rdb_read(SHOP_PAYMENTS, detail="検査 payments: 前日の決済の行の有無"),
            rdb_read(
                WAREHOUSE_STOCK,
                SHOP_PRODUCTS,
                detail="検査 stock_with_products: 前日に更新された在庫と商品の行の有無",
            ),
            rdb_read(MART_DAILY_SALES, detail="検査 daily_sales: 前日の集計行の有無"),
            rdb(
                "create",
                "audit.data_quality",
                "checked_at, check_name, status, detail",
                "検査 1 項目 = 1 行 (status は ok / ng)",
            ),
            "notify",
        ],
    ),
    Flow(
        "daily",
        "digest",
        "config/digests.yaml に列挙された日次レポートの CSV を集めて 1 本のダイジェストにし、S3 に置いてチャットに要約を流す",
        cron="0 9 * * *",
        inputs=[DATE_INPUT],
        labels={"owner": "data-platform"},
        io=[
            fs(
                "read",
                "config",
                "digests.yaml",
                "ダイジェストに含めるレポートの一覧 (ディレクトリ名と見出し)",
            ),
            fs(
                "read",
                "var/export",
                "{dir}/*_{date}.csv",
                "一覧 (config/digests.yaml) にあるディレクトリの当日 CSV を読む",
                dirs=["sales", "weekly", "monthly"],
            ),
            fs(
                "write",
                "var/export/digest",
                "digest_{date}.md",
                "Markdown のダイジェスト",
            ),
            s3("put", "REPORTS_BUCKET", "daily/digest/", "ダイジェストを置く"),
            "notify",
        ],
    ),
    Flow(
        "daily",
        "db_snapshot",
        "pg_dump で DB 全体のスナップショットを取り、S3 の kotori-backups/db/ に置く。最後の更新から 8 日以上たったローカルのダンプは消す",
        cron="30 23 * * *",
        kind="shell",
        labels={"owner": "sre"},
    ),
    Flow(
        "daily",
        "rotate_logs",
        "最後の更新から 2 日以上たったジョブのログを gzip し、31 日以上たった圧縮済みログを削除する",
        cron="50 23 * * *",
        kind="shell",
        labels={"owner": "sre"},
    ),
    # ---- daily.sales
    Flow(
        DAILY_SALES,
        "settle_orders",
        "前日の未確定注文を決済 API で売上確定 (capture) し、shop.orders と shop.payments を更新する。確定した注文はキュー orders.settled に流す",
        inputs=[DATE_INPUT],
        labels={"owner": "commerce-platform", "criticality": "high"},
        io=[
            rdb_read(
                SHOP_ORDERS,
                SHOP_PAYMENTS,
                detail="status = 'authorized' の注文と、その与信 (authorization) を取る",
            ),
            api(
                "POST",
                "PAYMENT_API_HOST",
                "/v1/captures",
                "与信 ID ごとに売上確定を要求",
            ),
            rdb(
                "update",
                SHOP_ORDERS,
                "status = 'settled', settled_at = now()",
                "確定できた注文",
            ),
            rdb(
                "create",
                SHOP_PAYMENTS,
                "order_id, kind, amount, provider_ref, created_at",
                "kind = 'capture' の行を追加",
            ),
            mq("publish", "orders.settled", "確定した注文 ID と金額"),
        ],
    ),
    Flow(
        DAILY_SALES,
        "sales_report",
        "確定済み注文の明細を商品別・日別に集計して mart.daily_sales に入れ替え、CSV を S3 に置く",
        inputs=[DATE_INPUT],
        labels={"owner": "sales-ops"},
        io=[
            rdb_read(
                SHOP_ORDERS,
                SHOP_ORDER_ITEMS,
                SHOP_PRODUCTS,
                detail="確定済み注文の明細を商品別・日別に集計する",
                select=[
                    "SELECT o.ordered_at::date AS sales_date, oi.product_id, p.category_id,",
                    "       SUM(oi.quantity) AS quantity, SUM(oi.quantity * oi.unit_price) AS amount",
                    "FROM shop.orders o",
                    "JOIN shop.order_items oi ON oi.order_id = o.id",
                    "JOIN shop.products p ON p.id = oi.product_id",
                    "WHERE o.status = 'settled' AND o.ordered_at >= %s::date - interval '1 day' AND o.ordered_at < %s::date",
                    "GROUP BY 1, 2, 3",
                ],
            ),
            rdb(
                "delete",
                MART_DAILY_SALES,
                "sales_date = %s",
                "同じ日の集計を消してから入れ直す",
            ),
            rdb(
                "create",
                MART_DAILY_SALES,
                "sales_date, product_id, category_id, quantity, amount",
                "商品別の集計行",
            ),
            fs("write", "var/export/sales", "daily_sales_{date}.csv", "集計結果の CSV"),
            s3("put", "REPORTS_BUCKET", "daily/sales/", "CSV を日付名で置く"),
            "notify",
        ],
    ),
    Flow(
        DAILY_SALES,
        "product_ranking",
        "直近 7 日の販売数から商品ランキングを作り、mart.product_ranking を入れ替えて Redis に上位 100 件を置く",
        cron="30 2 * * *",
        inputs=[DATE_INPUT],
        labels={"owner": "sales-ops"},
        io=[
            rdb_read(
                SHOP_ORDER_ITEMS,
                SHOP_ORDERS,
                SHOP_PRODUCTS,
                detail="直近 7 日の確定注文の明細をカテゴリ内で販売数順に順位付け",
                select=[
                    "SELECT oi.product_id, p.category_id, SUM(oi.quantity) AS units_7d,",
                    "       RANK() OVER (PARTITION BY p.category_id ORDER BY SUM(oi.quantity) DESC) AS rank",
                    "FROM shop.order_items oi",
                    "JOIN shop.orders o ON o.id = oi.order_id",
                    "JOIN shop.products p ON p.id = oi.product_id",
                    "WHERE o.status = 'settled' AND o.ordered_at >= %s::date - interval '7 days' AND o.ordered_at < %s::date",
                    "GROUP BY oi.product_id, p.category_id",
                ],
            ),
            py(
                'rows_2 = [{"ranking_date": day, **r} for r in rows_1 if r["rank"] <= 100]  # カテゴリごとに上位 100 件',
                rows="rows_2",
            ),
            rdb(
                "delete",
                "mart.product_ranking",
                "ranking_date = %s",
                "同じ日の順位を消す",
            ),
            rdb(
                "create",
                "mart.product_ranking",
                "ranking_date, rank, product_id, category_id, units_7d",
                "順位 1 行 = 商品 1 件 (カテゴリ内 100 位まで)",
            ),
            kvs(
                "set", "ranking:daily:{category_id}", "カテゴリごとに上位 100 件の商品"
            ),
            kvs("expire", "ranking:daily:{category_id}", "36 時間で失効"),
        ],
    ),
    Flow(
        DAILY_SALES,
        "coupon_expiry",
        "有効期限を過ぎたクーポンを失効させ、90 日より古い利用履歴を削除する",
        cron="0 3 * * *",
        labels={"owner": "sales-ops"},
        io=[
            rdb_read(
                "shop.coupons", detail="expires_at < now() かつ status = 'active'"
            ),
            rdb("update", "shop.coupons", "status = 'expired'", "期限切れのクーポン"),
            rdb(
                "delete",
                "shop.coupon_usages",
                "used_at < now() - interval '90 days'",
                "古い利用履歴",
            ),
        ],
    ),
    Flow(
        DAILY_SALES,
        "refund_returns",
        "承認済みの返品について決済 API に返金を要求し、shop.returns と shop.payments に結果を書く。返金完了はメール API で顧客に知らせる",
        cron="0 4 * * *",
        inputs=[DATE_INPUT],
        labels={"owner": "customer-support", "criticality": "high"},
        io=[
            rdb_read(
                "shop.returns",
                SHOP_PAYMENTS,
                SHOP_CUSTOMERS,
                detail="status = 'approved' の返品と元の決済、顧客のメールアドレス",
            ),
            api(
                "POST",
                "PAYMENT_API_HOST",
                "/v1/refunds",
                "元の決済の provider_ref を指定して返金",
            ),
            rdb(
                "update",
                "shop.returns",
                "status = 'refunded', refunded_at = now()",
                "返金できた返品",
            ),
            rdb(
                "create",
                SHOP_PAYMENTS,
                "order_id, kind, amount, provider_ref, created_at",
                "kind = 'refund' の行",
            ),
            api("POST", "MAIL_API_HOST", V3_MAIL_SEND, "返金完了メール"),
            rdb(
                "create",
                AUDIT_MAIL_LOG,
                MAIL_LOG_COLUMNS,
                MAIL_LOG_DESCRIPTION,
            ),
        ],
    ),
    # ---- daily.inventory
    Flow(
        DAILY_INVENTORY,
        "reconcile_stock",
        "前日の入出庫 (stock_movements) を在庫数に反映し、日次の在庫スナップショットを mart に書く。Redis の在庫キャッシュも更新する",
        inputs=[DATE_INPUT],
        labels={"owner": "warehouse", "criticality": "high"},
        io=[
            rdb_read(
                WAREHOUSE_STOCK,
                WAREHOUSE_STOCK_MOVEMENTS,
                detail="前日分の入出庫を SKU ごとに合計し、現在庫と並べる",
                select=[
                    "SELECT s.id, s.sku, s.reserved, SUM(m.delta) AS delta, s.on_hand + SUM(m.delta) AS on_hand",
                    "FROM warehouse.stock s",
                    "JOIN warehouse.stock_movements m ON m.sku = s.sku",
                    "WHERE m.moved_at >= %s::date - interval '1 day' AND m.moved_at < %s::date",
                    "GROUP BY s.id, s.sku, s.reserved, s.on_hand",
                ],
            ),
            py('rows_2 = [{"snapshot_date": day, **r} for r in rows_1]', rows="rows_2"),
            rdb(
                "update",
                WAREHOUSE_STOCK,
                "on_hand = on_hand + %s, updated_at = now()",
                "SKU ごとの差分を加算",
                params=("delta",),
            ),
            rdb(
                "create",
                "mart.inventory_snapshot",
                "snapshot_date, sku, on_hand, reserved",
                "当日の在庫スナップショット",
            ),
            kvs("set", "stock:{sku}", "SKU ごとの現在庫"),
        ],
    ),
    Flow(
        DAILY_INVENTORY,
        "import_supplier_feeds",
        "仕入先が置いた入荷 CSV (var/inbox/suppliers/) を取り込み、入荷と入庫を記録する。処理したファイルは done/ に移す",
        cron="30 0 * * *",
        labels={"owner": "warehouse"},
        io=[
            fs(
                "list",
                VAR_INBOX_SUPPLIERS,
                CSV_GLOB,
                "未処理の入荷 CSV を名前順に拾う",
            ),
            fs(
                "read",
                VAR_INBOX_SUPPLIERS,
                CSV_GLOB,
                "1 行 = 1 入荷明細 (sku, quantity, received_at)",
            ),
            rdb_read(
                WAREHOUSE_SUPPLIERS,
                detail="ファイル名の先頭 (仕入先コード) を仕入先 ID に解決する",
                select=["SELECT id, code FROM warehouse.suppliers"],
            ),
            py(
                "codes = {s['code']: s['id'] for s in rows_3}",
                'rows_4 = [{**r, "supplier_id": codes[r["source_file"].split("_")[0]]} for r in rows_2]  # ファイル名 <code>_<日付>.csv',
                rows="rows_4",
            ),
            rdb(
                "create",
                "warehouse.inbound_receipts",
                "supplier_id, sku, quantity, received_at, source_file",
                "入荷の記録 (CSV 1 行 = 1 行)",
            ),
            py(
                'rows_5 = [{"sku": r["sku"], "delta": int(r["quantity"]), "reason": "inbound", "moved_at": r["received_at"]} for r in rows_4]',
                rows="rows_5",
            ),
            rdb(
                "create",
                WAREHOUSE_STOCK_MOVEMENTS,
                "sku, delta, reason, moved_at",
                "reason = 'inbound' の入庫 (入荷 1 行 = 1 行)",
            ),
            fs(
                "write",
                "var/inbox/suppliers/done",
                CSV_GLOB,
                "処理済みファイルを移す (rename)",
            ),
            fs("delete", VAR_INBOX_SUPPLIERS, CSV_GLOB, "移動元 (rename で消える)"),
        ],
    ),
    Flow(
        DAILY_INVENTORY,
        "reorder_alerts",
        "在庫が発注点を下回った SKU の発注案を warehouse.purchase_orders に作り、仕入先担当にメールで知らせる",
        cron="0 6 * * *",
        labels={"owner": "warehouse"},
        io=[
            rdb_read(
                WAREHOUSE_STOCK,
                SHOP_PRODUCTS,
                WAREHOUSE_SUPPLIERS,
                detail="on_hand < reorder_point の SKU と仕入先",
            ),
            rdb(
                "create",
                "warehouse.purchase_orders",
                "supplier_id, sku, quantity, status, created_at",
                "status = 'draft' の発注案",
            ),
            api("POST", "MAIL_API_HOST", V3_MAIL_SEND, "仕入先担当への発注案メール"),
            rdb(
                "create",
                AUDIT_MAIL_LOG,
                MAIL_LOG_COLUMNS,
                MAIL_LOG_DESCRIPTION,
            ),
        ],
    ),
    Flow(
        DAILY_INVENTORY,
        "sync_search_index",
        "商品と在庫の有無を検索サービスのインデックスに一括登録する",
        cron="0 5 * * *",
        labels={"owner": "commerce-platform"},
        io=[
            rdb_read(
                SHOP_PRODUCTS,
                SHOP_PRODUCT_PRICES,
                WAREHOUSE_STOCK,
                detail="公開中の商品の名前・価格・在庫有無",
            ),
            api(
                "POST",
                "SEARCH_HOST",
                "/indexes/products/documents",
                "1000 件ずつ bulk upsert",
            ),
        ],
    ),
    # ---- daily.customer
    Flow(
        DAILY_CUSTOMER,
        "segment_customers",
        "購入回数と最終購入日から顧客をセグメント (new / active / dormant / churned) に分け、mart.customer_segments を入れ替える",
        cron="30 3 * * *",
        inputs=[DATE_INPUT],
        labels={"owner": "crm"},
        io=[
            rdb_read(
                SHOP_CUSTOMERS,
                SHOP_ORDERS,
                detail="顧客ごとの購入回数と最終購入日からセグメントを決める",
                select=[
                    "SELECT c.id AS customer_id, COUNT(o.id) AS orders_count, MAX(o.ordered_at) AS last_ordered_at,",
                    "       CASE WHEN COUNT(o.id) = 0 THEN 'new'",
                    "            WHEN MAX(o.ordered_at) >= %s::date - interval '90 days' THEN 'active'",
                    "            WHEN MAX(o.ordered_at) >= %s::date - interval '365 days' THEN 'dormant'",
                    "            ELSE 'churned' END AS segment",
                    "FROM shop.customers c",
                    "LEFT JOIN shop.orders o ON o.customer_id = c.id AND o.status = 'settled'",
                    "GROUP BY c.id",
                ],
            ),
            py('rows_2 = [{"segment_date": day, **r} for r in rows_1]', rows="rows_2"),
            rdb(
                "delete",
                MART_CUSTOMER_SEGMENTS,
                "segment_date = %s",
                "同じ日の分を消す",
            ),
            rdb(
                "create",
                MART_CUSTOMER_SEGMENTS,
                "segment_date, customer_id, segment, orders_count, last_ordered_at",
                "顧客 1 行",
            ),
        ],
    ),
    Flow(
        DAILY_CUSTOMER,
        "send_cart_reminders",
        "24 時間以上放置されたカートの持ち主にリマインドメールを送る。1 顧客 1 日 1 通に制限する",
        cron="0 10 * * *",
        labels={"owner": "crm"},
        io=[
            kvs("get", "cart:*", "SCAN で全カートを読み、更新時刻を見る"),
            py(
                'rows_2 = [c for c in rows_1 if c and c["updated_at"] < (dt.datetime.now() - dt.timedelta(hours=24)).isoformat()]  # 24 時間以上放置',
                rows="rows_2",
            ),
            rdb_read(
                SHOP_CUSTOMERS,
                detail="放置カートの持ち主のうち配信可の顧客のメールアドレス",
                select=[
                    "SELECT id AS customer_id, email FROM shop.customers",
                    "WHERE id = ANY(%s) AND mail_opt_in",
                ],
                params='([c["customer_id"] for c in rows_2],)',
            ),
            kvs(
                "get",
                MAIL_RATE_LIMIT_KEY,
                "当日すでに送った顧客を除く (1 顧客 1 日 1 通)",
            ),
            api("POST", "MAIL_API_HOST", V3_MAIL_SEND, "カートリマインド"),
            kvs("set", MAIL_RATE_LIMIT_KEY, "送信済みの印"),
            kvs(
                "expire",
                MAIL_RATE_LIMIT_KEY,
                "24 時間で失効",
                ttl="24 * 3600",
            ),
            rdb(
                "create",
                AUDIT_MAIL_LOG,
                MAIL_LOG_COLUMNS,
                MAIL_LOG_DESCRIPTION,
            ),
        ],
    ),
    Flow(
        DAILY_CUSTOMER,
        "review_moderation",
        "未審査のレビューを外部の判定 API にかけ、結果で公開 / 保留を決める",
        cron="0 7 * * *",
        labels={"owner": "customer-support"},
        io=[
            rdb_read("shop.reviews", detail="status = 'pending' のレビュー本文"),
            api(
                "POST",
                None,
                "/v1/classify",
                "レビュー本文の判定 (host は環境変数 KOTORI_MODERATION_API_HOST)",
                unknown="not_traceable_in_repo",
                note="host は環境変数 KOTORI_MODERATION_API_HOST で、既定値がリポジトリに無い",
            ),
            rdb(
                "update",
                "shop.reviews",
                "status = %s, moderated_at = now()",
                "判定結果 (published / held)",
            ),
        ],
    ),
    Flow(
        DAILY_CUSTOMER,
        "wishlist_price_drop",
        "欲しいものリストの商品が値下げされていたら、プッシュ通知で知らせる",
        cron="0 8 * * *",
        inputs=[DATE_INPUT],
        labels={"owner": "crm"},
        io=[
            rdb_read(
                "audit.price_changes",
                "shop.wishlists",
                SHOP_CUSTOMERS,
                detail="前日の値下げと、その商品をリストに入れている顧客",
            ),
            api(
                "POST",
                "PUSH_API_HOST",
                "/v1/notifications",
                "顧客のデバイストークン宛に通知",
            ),
        ],
    ),
    # ---- hourly
    Flow(
        "hourly",
        "sync_shipments",
        "配送中の出荷の追跡情報を配送業者 API から取り、shop.shipments の状態を更新する",
        cron="15 * * * *",
        labels={"owner": "warehouse"},
        io=[
            rdb_read(
                "shop.shipments",
                detail="status in ('shipped', 'in_transit') の出荷と追跡番号",
            ),
            api(
                "GET",
                "CARRIER_API_HOST",
                "/v2/tracking/{tracking_no}",
                "追跡番号ごとに最新の状態",
            ),
            rdb(
                "update",
                "shop.shipments",
                "status = %s, last_event_at = %s",
                "状態が変わった出荷",
            ),
        ],
    ),
    Flow(
        "hourly",
        "abandoned_carts_snapshot",
        "Redis のカートを毎時なめて、放置カートの件数と金額を audit.cart_snapshots に書く",
        cron="5 * * * *",
        labels={"owner": "crm"},
        io=[
            kvs("get", "cart:*", "SCAN で全カートを読む"),
            rdb(
                "create",
                "audit.cart_snapshots",
                "taken_at, carts_total, carts_abandoned, amount_abandoned",
                "毎時 1 行",
            ),
        ],
    ),
    Flow(
        "hourly",
        "consume_stock_events",
        "キュー stock.changed を 5 分ごとに読み、在庫数と Redis の在庫キャッシュへ反映する",
        cron="*/5 * * * *",
        labels={"owner": "warehouse", "criticality": "high"},
        io=[
            mq(
                "consume",
                "stock.changed",
                "出荷・返品・棚卸で発生した在庫の変化 (sku, delta, reason, moved_at, id)",
            ),
            rdb(
                "update",
                WAREHOUSE_STOCK,
                "on_hand = on_hand + %s, updated_at = now()",
                "SKU ごとに加算",
                params=("delta",),
            ),
            rdb(
                "create",
                WAREHOUSE_STOCK_MOVEMENTS,
                "sku, delta, reason, moved_at",
                "イベント 1 件 = 1 行",
            ),
            kvs("set", "stock:{sku}", "更新後の現在庫"),
        ],
    ),
    Flow(
        "hourly",
        "mail_queue_worker",
        "キュー mail.requests を 10 分ごとに読み、メール API で送って audit.mail_log に記録する",
        cron="*/10 * * * *",
        labels={"owner": "crm"},
        io=[
            mq("consume", "mail.requests", "各ジョブ・各画面が積んだメール要求"),
            api(
                "POST",
                "MAIL_API_HOST",
                V3_MAIL_SEND,
                "テンプレートと宛先を指定して送信",
            ),
            rdb(
                "create",
                AUDIT_MAIL_LOG,
                MAIL_LOG_COLUMNS,
                MAIL_LOG_DESCRIPTION,
            ),
        ],
    ),
    # ---- weekly
    Flow(
        "weekly",
        "close_week",
        "週次の締め。コホート分析と仕入先向け明細を Subflow で呼ぶ。失敗時は lib.notify_failure に通知する",
        cron="0 3 * * 1",
        kind="orchestrator",
        inputs=[("week_start", "DATE", WEEK_START_HELP)],
        subflows=["weekly.cohort_retention", "weekly.supplier_statements"],
        on_error="lib.notify_failure",
        labels={"owner": "data-platform"},
    ),
    Flow(
        "weekly",
        "cohort_retention",
        "初回購入月ごとのコホートで週次の継続率を計算し、mart.cohort_retention と CSV (S3) に出す",
        inputs=[("week_start", "DATE", WEEK_START_HELP)],
        labels={"owner": "data-platform"},
        io=[
            rdb_read(
                SHOP_CUSTOMERS, SHOP_ORDERS, detail="初回購入月と週ごとの購入有無"
            ),
            rdb(
                "create",
                "mart.cohort_retention",
                "week_start, cohort_month, week_index, customers, retained",
                "コホート × 週で 1 行",
            ),
            fs("write", "var/export/weekly", "cohort_{week_start}.csv", "継続率の表"),
            s3("put", "REPORTS_BUCKET", "weekly/cohort/", "CSV を置く"),
        ],
    ),
    Flow(
        "weekly",
        "supplier_statements",
        "仕入先ごとの週次明細 (入荷と発注) を CSV にまとめ、メールで送る",
        inputs=[("week_start", "DATE", WEEK_START_HELP)],
        labels={"owner": "warehouse"},
        io=[
            rdb_read(
                WAREHOUSE_SUPPLIERS,
                "warehouse.inbound_receipts",
                "warehouse.purchase_orders",
                detail="仕入先ごとの入荷と発注",
            ),
            fs(
                "write",
                "var/export/suppliers",
                "{supplier_code}_{week_start}.csv",
                "仕入先 1 件 = 1 ファイル",
            ),
            api(
                "POST",
                "MAIL_API_HOST",
                V3_MAIL_SEND,
                "CSV を添付して仕入先担当に送る",
            ),
            rdb(
                "create",
                AUDIT_MAIL_LOG,
                MAIL_LOG_COLUMNS,
                MAIL_LOG_DESCRIPTION,
            ),
        ],
    ),
    Flow(
        "weekly",
        "tax_rate_refresh",
        "税率 API から最新の税率表を取り、shop.tax_rates を更新する",
        cron="0 4 * * 0",
        labels={"owner": "commerce-platform"},
        io=[
            api("GET", "TAX_API_HOST", "/v1/rates", "国・地域ごとの税率"),
            rdb(
                "update",
                "shop.tax_rates",
                "rate = %s, effective_from = %s",
                "変わった地域だけ更新",
            ),
        ],
    ),
    Flow(
        "weekly",
        "legacy_price_sync",
        "旧価格計算エンジン (bin/legacy_pricing、バイナリ) を実行し、出力の価格表で shop.product_prices を更新する。変更は audit.price_changes に残す",
        cron="0 2 * * 6",
        labels={"owner": "commerce-platform"},
        binary=True,
        io=[
            fs(
                "read",
                "var/tmp",
                "pricing.out",
                "バイナリが書いた TSV (sku, new_price)",
            ),
            rdb_read(SHOP_PRODUCT_PRICES, detail="現在の価格 (差分の検出用)"),
            rdb(
                "update",
                SHOP_PRODUCT_PRICES,
                "price = %s, updated_at = now()",
                "価格が変わった SKU",
            ),
            rdb(
                "create",
                "audit.price_changes",
                "changed_at, product_id, old_price, new_price, source",
                "source = 'legacy_pricing'",
            ),
        ],
    ),
    Flow(
        "weekly",
        "archive_old_orders",
        "2 年より古い注文を JSON Lines にして S3 のアーカイブに置き、DB から削除する",
        cron="0 1 * * 0",
        inputs=[DATE_INPUT],
        labels={"owner": "data-platform", "criticality": "high"},
        io=[
            rdb_read(
                SHOP_ORDERS,
                SHOP_ORDER_ITEMS,
                detail="2 年より古い注文と、その明細 (JSON にまとめる)",
                select=[
                    "SELECT o.id, o.customer_id, o.ordered_at, o.status,",
                    "       json_agg(json_build_object('product_id', oi.product_id, 'quantity', oi.quantity, 'unit_price', oi.unit_price)) AS items",
                    "FROM shop.orders o",
                    "JOIN shop.order_items oi ON oi.order_id = o.id",
                    "WHERE o.ordered_at < %s::date - interval '2 years'",
                    "GROUP BY o.id",
                ],
            ),
            fs(
                "write",
                "var/export/archive",
                "orders_{yyyymm}.jsonl",
                "注文 1 件 = 1 行 (明細を含む)",
            ),
            s3("put", "EXPORTS_BUCKET", "archive/orders/", "月ごとのファイルを置く"),
            rdb(
                "delete",
                SHOP_ORDER_ITEMS,
                "order_id = ANY(%s)",
                "アーカイブ済みの明細",
            ),
            rdb("delete", SHOP_ORDERS, "id = ANY(%s)", "アーカイブ済みの注文"),
        ],
    ),
    # ---- monthly
    Flow(
        "monthly",
        "monthly_kpi",
        "月次 KPI (売上・顧客数・継続率) を sql/reports/ のテンプレートから組み立てた SQL で集計し、mart.monthly_kpi と Excel (S3) に出す",
        cron="0 5 1 * *",
        inputs=[("month", "STRING", MONTH_HELP)],
        labels={"owner": "data-platform"},
        template_sql="sql/reports/monthly_kpi.sql.j2",
        io=[
            rdb_read(
                MART_DAILY_SALES,
                MART_CUSTOMER_SEGMENTS,
                "mart.cohort_retention",
                template=True,
                detail="Jinja テンプレートに month を埋めて組み立てた SQL で読む。参照する表はテンプレートに静的に書かれている",
            ),
            rdb(
                "create",
                "mart.monthly_kpi",
                "month, kpi_name, kpi_value",
                "KPI 1 項目 = 1 行",
            ),
            fs("write", "var/export/monthly", "kpi_{month}.xlsx", "KPI の表"),
            s3("put", "REPORTS_BUCKET", "monthly/kpi/", "Excel を置く"),
        ],
    ),
    Flow(
        "monthly",
        "custom_reports",
        "audit.report_definitions に登録された SQL (利用部門が管理画面から登録する) を月初に実行し、結果を定義ごとの CSV にして S3 に置く",
        cron="0 7 1 * *",
        inputs=[("month", "STRING", MONTH_HELP)],
        labels={"owner": "data-platform"},
        io=[
            rdb_read(
                "audit.report_definitions",
                where="t0.enabled = true",
                detail="enabled = true の定義 (name, sql, owner)",
            ),
            rdb_read(
                stored=True,
                unknown="generated_at_runtime",
                detail="定義ごとに、保存された SQL をそのまま実行する",
                note="どの表を読むかは DB の中の文字列 (audit.report_definitions.sql) で決まり、リポジトリからは読めない",
            ),
            fs(
                "write",
                "var/export/custom",
                "{report_name}_{month}.csv",
                "定義ごとに 1 ファイル (結果の行を CSV に)",
                unknown="dynamic_dispatch",
                note="ファイル名は定義の name で実行時に決まる",
            ),
            s3(
                "put",
                "REPORTS_BUCKET",
                "monthly/custom/",
                "定義ごとの CSV を同じループの中で置く",
            ),
        ],
    ),
    Flow(
        "monthly",
        "invoice_batch",
        "法人顧客の前月分の請求書 (PDF) を顧客ごとのディレクトリに作り、メールで送る",
        cron="0 6 1 * *",
        inputs=[("month", "STRING", MONTH_HELP)],
        labels={"owner": "sales-ops", "criticality": "high"},
        io=[
            rdb_read(
                SHOP_CUSTOMERS,
                SHOP_ORDERS,
                "shop.addresses",
                detail="kind = 'corporate' の顧客と前月の確定注文、請求先住所",
            ),
            fs(
                "write",
                "var/export/invoices",
                "{customer_code}/invoice_{month}.pdf",
                "顧客ごとのディレクトリに PDF",
                unknown="dynamic_dispatch",
                note="ディレクトリ名は顧客コードで実行時に決まる",
            ),
            api("POST", "MAIL_API_HOST", V3_MAIL_SEND, "PDF を添付して送る"),
            rdb(
                "create",
                AUDIT_MAIL_LOG,
                MAIL_LOG_COLUMNS,
                MAIL_LOG_DESCRIPTION,
            ),
        ],
    ),
    Flow(
        "monthly",
        "purge_sessions",
        "最後に使われてから 90 日を超えたセッションを Redis から消し、同じ期間を超えて放置されたカートを shop.carts から削除する",
        cron="0 4 1 * *",
        labels={"owner": "sre"},
        io=[
            kvs("get", "session:*", "SCAN で最終アクセス時刻を読む"),
            kvs(
                "delete",
                "session:*",
                "値が空か、最後に使われた日 (last_seen) が無いか、90 日前の日付より前のもの",
            ),
            rdb(
                "delete",
                "shop.carts",
                "updated_at < now() - interval '90 days'",
                "放置カート",
            ),
        ],
    ),
    # ---- lib
    Flow(
        "lib",
        "notify_failure",
        "他の Flow の errors から呼ばれ、失敗した Flow の名前と実行 ID をチャットに通知する",
        inputs=[
            ("flow_id", "STRING", "失敗した Flow"),
            ("execution_id", "STRING", "失敗した実行の ID"),
        ],
        labels={"owner": "sre"},
        concurrency=False,
        io=["notify_failure"],
    ),
]

LIBS = {
    "rdb": ("lib_db", JOBS_LIB_DB_PY, "psycopg", "db"),
    "kvs": ("lib_cache", JOBS_LIB_CACHE_PY, "redis", "cache"),
    "object_storage": ("lib_storage", JOBS_LIB_STORAGE_PY, "boto3", "storage"),
    "external_api": ("lib_http", JOBS_LIB_HTTP_PY, "requests", "http"),
    "queue": ("lib_mq", JOBS_LIB_MQ_PY, "pika", "mq"),
}


# ---------------------------------------------------------------- 行番号を記録しながら書く


class Src:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.marks: dict[str, int] = {}

    def add(self, text: str = "", mark: str | None = None) -> int:
        self.lines.append(text)
        n = len(self.lines)
        if mark:
            self.marks[mark] = n
        return n

    def block(self, text: str) -> None:
        for line in text.strip("\n").splitlines():
            self.add(line)

    def text(self) -> str:
        return "\n".join(self.lines) + "\n"


def write(root: Path, rel: str, text: str, executable: bool = False) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    if executable:
        p.chmod(0o755)


# ---------------------------------------------------------------- 対象: 共通ファイル


def gen_common(target: Path) -> dict[str, Src]:
    """共通のスクリプトとライブラリを書き、行番号の記録を返す。"""
    srcs: dict[str, Src] = {}

    run_job = Src()
    run_job.block("""
#!/usr/bin/env bash
# 共通ランナー: 環境の設定を読み、ジョブモジュール (jobs/<name>.py) を実行し、ログに追記する。
# 使い方: bash scripts/run_job.sh <job> [args...]   (Kestra の Flow から呼ばれる)
set -euo pipefail
JOB="${1:?job name}"
shift
cd "$(dirname "$0")/.."
""")
    run_job.add(
        "# 実行ユーザーの確認: KOTORI_RUN_USER が設定されていれば、そのユーザーでなければ動かさない"
    )
    run_job.add(
        'if [ -n "${KOTORI_RUN_USER:-}" ] && [ "$(id -un)" != "$KOTORI_RUN_USER" ]; then',
        mark="run_user",
    )
    run_job.add('  echo "run_job.sh: ${KOTORI_RUN_USER} で実行してください" >&2')
    run_job.add("  exit 77")
    run_job.add("fi")
    run_job.add('ENV_FILE="config/${KOTORI_ENV:-prod}.env"', mark="env_file")
    run_job.add("# shellcheck disable=SC1090")
    run_job.add('source "$ENV_FILE"', mark="source_env")
    run_job.add('export PYTHONPATH="$PWD"')
    run_job.add("mkdir -p var/log/jobs")
    run_job.add('LOG="var/log/jobs/${JOB}.log"', mark="log_path")
    run_job.add('echo "$(date -Is) start ${JOB} $*" >> "$LOG"', mark="log_start")
    run_job.add("set +e")
    run_job.add('python3 -m "jobs.${JOB}" "$@" 2>&1 | tee -a "$LOG"', mark="python")
    run_job.add("rc=${PIPESTATUS[0]}")
    run_job.add("set -e")
    run_job.add('echo "$(date -Is) end ${JOB} rc=${rc}" >> "$LOG"')
    run_job.add('exit "$rc"')
    write(target, SCRIPTS_RUN_JOB_SH, run_job.text(), executable=True)
    srcs[SCRIPTS_RUN_JOB_SH] = run_job

    snap = Src()
    snap.block("""
#!/usr/bin/env bash
# DB の日次スナップショット: pg_dump → var/backup/ → S3 (kotori-backups/db/<日付>/)。最後の更新から 8 日以上たったローカルのダンプは消す。
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck disable=SC1090
""")
    snap.add('source "config/${KOTORI_ENV:-prod}.env"', mark="source_env")
    snap.add('STAMP="$(date +%Y%m%d)"')
    snap.add('OUT="var/backup/kotori_${STAMP}.dump"')
    snap.add("mkdir -p var/backup")
    snap.add(
        'pg_dump --format=custom --dbname="${KOTORI_DATABASE_URL}" --file="${OUT}"',
        mark="pg_dump",
    )
    snap.add('aws s3 cp "${OUT}" "s3://${BACKUPS_BUCKET}/db/${STAMP}/"', mark="aws_cp")
    snap.add("find var/backup -name 'kotori_*.dump' -mtime +7 -delete", mark="prune")
    write(target, "scripts/db_snapshot.sh", snap.text(), executable=True)
    srcs["scripts/db_snapshot.sh"] = snap

    rot = Src()
    rot.block("""
#!/usr/bin/env bash
# ログのローテーション: 最後の更新から 2 日以上たったジョブログを gzip し、31 日以上たった圧縮済みログを削除する。
set -euo pipefail
cd "$(dirname "$0")/.."
""")
    rot.add(
        "find var/log/jobs -name '*.log' -mtime +1 -exec gzip -f {} \\;", mark="gzip"
    )
    rot.add("find var/log/jobs -name '*.log.gz' -mtime +30 -delete", mark="prune")
    write(target, "scripts/rotate_logs.sh", rot.text(), executable=True)
    srcs["scripts/rotate_logs.sh"] = rot

    settings = Src()
    settings.block('''
"""設定値。秘密 (パスワード・トークン) は環境変数からだけ読み、既定値を持たない。"""
from __future__ import annotations

import os
''')
    settings.add("")
    settings.add(
        f'DATABASE_URL = os.environ.get("KOTORI_DATABASE_URL", "postgresql://kotori@{DB["host"]}:5432/{DB["database"]}")',
        mark="db_url",
    )
    settings.add(
        f'CACHE_URL = os.environ.get("KOTORI_CACHE_URL", "redis://{CACHE["host"]}:6379/{CACHE["instance"]}")',
        mark="cache_url",
    )
    settings.add(
        f'MQ_URL = os.environ.get("KOTORI_MQ_URL", "amqp://kotori@{BROKER}:5672/%2F")',
        mark="mq_url",
    )
    settings.add("")
    for const, host in HOSTS.items():
        settings.add(f'{const} = "{host}"', mark=const)
    settings.add("")
    for const, bucket in BUCKETS.items():
        settings.add(f'{const} = os.environ.get("{const}", "{bucket}")', mark=const)
    settings.add("")
    for const, d in DIRS.items():
        settings.add(f'{const} = "{d}"', mark=const)
    write(target, "jobs/settings.py", settings.text())
    srcs["jobs/settings.py"] = settings

    write(
        target,
        "jobs/__init__.py",
        '"""ことり書店のバッチジョブ。scripts/run_job.sh が `python3 -m jobs.<name>` で起動する。"""\n',
    )
    write(
        target,
        "jobs/lib/__init__.py",
        '"""ジョブが共有する薄いラッパー (DB / キャッシュ / オブジェクトストレージ / HTTP / キュー / 通知)。"""\n',
    )

    db = Src()
    db.add('"""PostgreSQL への接続と問い合わせ (psycopg の薄いラッパー)。"""')
    db.add(FUTURE_ANNOTATIONS_IMPORT)
    db.add("")
    db.add("from contextlib import contextmanager")
    db.add("")
    db.add("import psycopg", mark="import")
    db.add("")
    db.add(SETTINGS_IMPORT)
    db.add("")
    db.add("")
    db.add("@contextmanager")
    db.add("def connect():")
    db.add("    conn = psycopg.connect(settings.DATABASE_URL)", mark="connect")
    db.block("""
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def fetch_all(sql: str, params: tuple = ()) -> list[dict]:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        cols = [d.name for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def execute(sql: str, params: tuple = ()) -> int:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.rowcount


def execute_many(sql: str, rows: list[tuple]) -> int:
    if not rows:
        return 0
    with connect() as conn, conn.cursor() as cur:
        cur.executemany(sql, rows)
        return cur.rowcount
""")
    write(target, JOBS_LIB_DB_PY, db.text())
    srcs[JOBS_LIB_DB_PY] = db

    cache = Src()
    cache.add(
        '"""Redis のキャッシュ (redis-py の薄いラッパー)。キーの設計は docs/keys.md。"""'
    )
    cache.add(FUTURE_ANNOTATIONS_IMPORT)
    cache.add("")
    cache.add("import json")
    cache.add("from typing import Iterator")
    cache.add("")
    cache.add("import redis", mark="import")
    cache.add("")
    cache.add(SETTINGS_IMPORT)
    cache.add("")
    cache.add("_client: redis.Redis | None = None")
    cache.add("")
    cache.add("")
    cache.add("def client() -> redis.Redis:")
    cache.add("    global _client")
    cache.add("    if _client is None:")
    cache.add(
        "        _client = redis.Redis.from_url(settings.CACHE_URL, decode_responses=True)",
        mark="connect",
    )
    cache.block("""
    return _client


def get(key: str):
    raw = client().get(key)
    return json.loads(raw) if raw else None


def set(key: str, value) -> None:  # noqa: A001
    client().set(key, json.dumps(value, ensure_ascii=False))


def expire(key: str, seconds: int) -> None:
    client().expire(key, seconds)


def delete(*keys: str) -> int:
    return client().delete(*keys) if keys else 0


def scan(pattern: str) -> Iterator[str]:
    yield from client().scan_iter(match=pattern, count=500)
""")
    write(target, JOBS_LIB_CACHE_PY, cache.text())
    srcs[JOBS_LIB_CACHE_PY] = cache

    storage = Src()
    storage.add('"""S3 互換のオブジェクトストレージ (boto3 の薄いラッパー)。"""')
    storage.add(FUTURE_ANNOTATIONS_IMPORT)
    storage.add("")
    storage.add("import boto3", mark="import")
    storage.add("")
    storage.add("_s3 = None")
    storage.add("")
    storage.add("")
    storage.add("def client():")
    storage.add("    global _s3")
    storage.add("    if _s3 is None:")
    storage.add('        _s3 = boto3.client("s3")', mark="connect")
    storage.block("""
    return _s3


def put_object(bucket: str, key: str, body: bytes, content_type: str = "application/octet-stream") -> None:
    client().put_object(Bucket=bucket, Key=key, Body=body, ContentType=content_type)


def get_object(bucket: str, key: str) -> bytes:
    return client().get_object(Bucket=bucket, Key=key)["Body"].read()


def list_objects(bucket: str, prefix: str) -> list[str]:
    paginator = client().get_paginator("list_objects_v2")
    return [o["Key"] for page in paginator.paginate(Bucket=bucket, Prefix=prefix) for o in page.get("Contents", [])]


def delete_object(bucket: str, key: str) -> None:
    client().delete_object(Bucket=bucket, Key=key)
""")
    write(target, JOBS_LIB_STORAGE_PY, storage.text())
    srcs[JOBS_LIB_STORAGE_PY] = storage

    http = Src()
    http.add(
        '"""外部 API 呼び出し (requests の薄いラッパー)。認証ヘッダはホストごとの環境変数 KOTORI_API_TOKEN_<HOST> から付ける。"""'
    )
    http.add(FUTURE_ANNOTATIONS_IMPORT)
    http.add("")
    http.add("import os")
    http.add("")
    http.add("import requests", mark="import")
    http.add("")
    http.add("TIMEOUT = (5, 30)")
    http.add("")
    http.add("")
    http.add("def _headers(host: str) -> dict:")
    http.add(
        '    token = os.environ.get("KOTORI_API_TOKEN_" + host.split(".")[1].upper(), "")'
    )
    http.add(
        '    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}'
    )
    http.add("")
    http.add("")
    http.add("def get_json(host: str, path: str, params: dict | None = None) -> dict:")
    http.add(
        '    r = requests.get(f"https://{host}{path}", params=params, headers=_headers(host), timeout=TIMEOUT)',
        mark="get",
    )
    http.add("    r.raise_for_status()")
    http.add("    return r.json()")
    http.add("")
    http.add("")
    http.add("def post_json(host: str, path: str, body: dict) -> dict:")
    http.add(
        '    r = requests.post(f"https://{host}{path}", json=body, headers=_headers(host), timeout=TIMEOUT)',
        mark="post",
    )
    http.add("    r.raise_for_status()")
    http.add("    return r.json()")
    write(target, JOBS_LIB_HTTP_PY, http.text())
    srcs[JOBS_LIB_HTTP_PY] = http

    mqs = Src()
    mqs.add(
        '"""メッセージキュー (pika / AMQP の薄いラッパー)。トピック名はキュー名と同じ。"""'
    )
    mqs.add(FUTURE_ANNOTATIONS_IMPORT)
    mqs.add("")
    mqs.add("import json")
    mqs.add("from typing import Iterator")
    mqs.add("")
    mqs.add("import pika", mark="import")
    mqs.add("")
    mqs.add(SETTINGS_IMPORT)
    mqs.add("")
    mqs.add("")
    mqs.add("def _channel():")
    mqs.add(
        "    conn = pika.BlockingConnection(pika.URLParameters(settings.MQ_URL))",
        mark="connect",
    )
    mqs.block('''
    return conn, conn.channel()


def publish(topic: str, payload: dict) -> None:
    conn, ch = _channel()
    try:
        ch.queue_declare(queue=topic, durable=True)
        ch.basic_publish(exchange="", routing_key=topic, body=json.dumps(payload, ensure_ascii=False))
    finally:
        conn.close()


def consume(topic: str, limit: int = 1000) -> Iterator[dict]:
    """メッセージを取り出して ACK する (キューから消える)。"""
    conn, ch = _channel()
    try:
        ch.queue_declare(queue=topic, durable=True)
        for _ in range(limit):
            method, _props, body = ch.basic_get(queue=topic, auto_ack=False)
            if method is None:
                break
            yield json.loads(body)
            ch.basic_ack(method.delivery_tag)
    finally:
        conn.close()


def peek(topic: str, limit: int = 1000) -> list[dict]:
    """メッセージを読むだけで ACK しない (NACK で戻す。dry-run 用)。"""
    conn, ch = _channel()
    try:
        ch.queue_declare(queue=topic, durable=True)
        tags, out = [], []
        for _ in range(limit):
            method, _props, body = ch.basic_get(queue=topic, auto_ack=False)
            if method is None:
                break
            tags.append(method.delivery_tag)
            out.append(json.loads(body))
        for tag in tags:
            ch.basic_nack(tag, requeue=True)
        return out
    finally:
        conn.close()
''')
    write(target, JOBS_LIB_MQ_PY, mqs.text())
    srcs[JOBS_LIB_MQ_PY] = mqs

    notify = Src()
    notify.add(
        '"""運用チャットへの通知。Webhook の URL は環境変数 KOTORI_CHAT_WEBHOOK (リポジトリには置かない)。"""'
    )
    notify.add(FUTURE_ANNOTATIONS_IMPORT)
    notify.add("")
    notify.add("import os")
    notify.add("")
    notify.add("import requests", mark="import")
    notify.add("")
    notify.add("")
    notify.add("def post(text: str) -> None:")
    notify.add('    url = os.environ.get("KOTORI_CHAT_WEBHOOK")', mark="url")
    notify.add("    if not url:")
    notify.add("        return")
    notify.add(
        '    requests.post(url, json={"text": text}, timeout=(5, 10)).raise_for_status()',
        mark="post",
    )
    write(target, JOBS_LIB_NOTIFY_PY, notify.text())
    srcs[JOBS_LIB_NOTIFY_PY] = notify
    test_notify = Src()
    test_notify.add('"""jobs.lib.notify の単体テスト (pytest)。"""')
    test_notify.add("from jobs.lib import notify")
    test_notify.add("")
    test_notify.add("")
    test_notify.add(
        "def test_post_without_webhook_does_nothing(monkeypatch):", mark="test"
    )
    test_notify.add('    monkeypatch.delenv("KOTORI_CHAT_WEBHOOK", raising=False)')
    test_notify.add("    calls = []")
    test_notify.add(
        '    monkeypatch.setattr(notify.requests, "post", lambda *a, **k: calls.append(a))'
    )
    test_notify.add('    notify.post("hello")')
    test_notify.add("    assert calls == []  # URL が無ければ、何も送らない")
    write(target, TESTS_TEST_NOTIFY_PY, test_notify.text())
    srcs[TESTS_TEST_NOTIFY_PY] = test_notify

    write(
        target,
        "config/prod.env",
        "\n".join(
            [
                "# 本番の設定 (秘密は含めない。パスワード・トークンは実行環境の環境変数で渡す)",
                f"KOTORI_DATABASE_URL=postgresql://kotori@{DB['host']}:5432/{DB['database']}",
                f"KOTORI_CACHE_URL=redis://{CACHE['host']}:6379/{CACHE['instance']}",
                f"KOTORI_MQ_URL=amqp://kotori@{BROKER}:5672/%2F",
                *(f"{k}={v}" for k, v in BUCKETS.items()),
                "AWS_DEFAULT_REGION=ap-northeast-1",
            ]
        )
        + "\n",
    )
    write(
        target,
        CONFIG_DIGESTS_YAML,
        "\n".join(
            [
                "# daily.digest がまとめるレポート。dir は var/export/ の下のディレクトリ",
                "digests:",
                "  - dir: sales",
                "    title: 売上 (日次)",
                "  - dir: weekly",
                "    title: コホート継続率 (週次)",
                "  - dir: monthly",
                "    title: 月次 KPI",
            ]
        )
        + "\n",
    )
    write(
        target,
        "sql/reports/monthly_kpi.sql.j2",
        "\n".join(
            [
                "-- 月次 KPI。monthly.monthly_kpi が Jinja で month を埋めて実行する",
                "SELECT 'sales_amount' AS kpi_name, SUM(amount) AS kpi_value FROM mart.daily_sales WHERE to_char(sales_date, 'YYYY-MM') = '{{ month }}'",
                "UNION ALL",
                "SELECT 'active_customers', COUNT(*) FROM mart.customer_segments WHERE segment = 'active' AND to_char(segment_date, 'YYYY-MM') = '{{ month }}'",
                "UNION ALL",
                "SELECT 'retention_w4', AVG(retained::numeric / NULLIF(customers, 0)) FROM mart.cohort_retention WHERE week_index = 4 AND to_char(week_start, 'YYYY-MM') = '{{ month }}'",
            ]
        )
        + "\n",
    )
    write(
        target,
        BIN_LEGACY_PRICING,
        "\n".join(
            [
                "#!/bin/sh",
                "# このファイルは、旧価格計算エンジンのコンパイル済みバイナリの代わりに置いてあるもの。",
                "# 実際のシステムではソースの無い成果物で、何を読んで価格を決めるかは外から読めない。ここでは決まった価格表を --out に書くだけ。",
                'out="${2:?--out <file>}"',
                'mkdir -p "$(dirname "$out")"',
                "printf 'BK-0001\\t1200\\nBK-0002\\t980\\nBK-0003\\t2400\\n' > \"$out\"",
            ]
        )
        + "\n",
        executable=True,
    )
    write(
        target,
        "requirements.txt",
        "psycopg[binary]>=3.1\nredis>=5.0\nboto3>=1.34\nrequests>=2.31\npika>=1.3\nPyYAML>=6.0\nJinja2>=3.1\nopenpyxl>=3.1\n",
    )
    write(target, ".gitignore", "var/\n__pycache__/\n*.pyc\n")
    return srcs


# ---------------------------------------------------------------- 対象: Flow と ジョブ


def file_root(d):
    base = next((c for c, v in DIRS.items() if d == v or d.startswith(v + "/")), None)
    if base is None:
        return f'Path("{d}")'
    root = f"Path(settings.{base})"
    sub = d[len(DIRS[base]) + 1 :]
    return f'{root} / "{sub}"' if sub else root


def emit_subflow_tasks(s, f):
    for sub in f.subflows:
        ns, _, fid = sub.rpartition(".")
        s.add(f"  - id: {fid}")
        s.add("    type: io.kestra.plugin.core.flow.Subflow")
        s.add(f"    namespace: {ns}")
        s.add(f"    flowId: {fid}", mark=f"subflow:{sub}")
        s.add("    wait: true")
        s.add("    transmitFailed: true")
        if f.inputs:
            s.add("    inputs:")
            for iid, _, _ in f.inputs:
                s.add(f'      {iid}: "{{{{ inputs.{iid} }}}}"')


def emit_flow_tasks(s, f):
    s.add("tasks:")
    if f.kind == "orchestrator":
        emit_subflow_tasks(s, f)
    else:
        script = f"scripts/{f.id}.sh" if f.kind == "shell" else SCRIPTS_RUN_JOB_SH
        args = f"{f.id} " if f.kind != "shell" else ""
        for iid, _, _ in f.inputs:
            args += f'--{iid.replace("_", "-")} "{{{{ inputs.{iid} }}}}" '
        s.add("  - id: run")
        s.add("    type: io.kestra.plugin.scripts.shell.Commands")
        s.add("    taskRunner:")
        s.add("      type: io.kestra.plugin.core.runner.Process")
        s.add("    workingDirectory: /opt/kotori")
        s.add("    env:")
        s.add("      KOTORI_ENV: prod", mark="env")
        s.add("    commands:")
        s.add(f"      - bash {script} {args}".rstrip(), mark="command")


def gen_flow(target: Path, f: Flow) -> Src:
    s = Src()
    s.add(f"id: {f.id}")
    s.add(f"namespace: {f.ns}")
    s.add("description: |", mark="description")
    s.add(f"  {f.desc}")
    if f.labels:
        s.add("labels:")
        for k, v in f.labels.items():
            s.add(f"  {k}: {v}")
    if f.inputs:
        s.add("inputs:")
        for iid, typ, help_ in f.inputs:
            s.add(f"  - id: {iid}", mark=f"input:{iid}")
            s.add(f"    type: {typ}")
            s.add("    required: false")
            s.add(f"    description: {help_}")
    if f.concurrency:
        s.add("concurrency:", mark="concurrency")
        s.add("  limit: 1")
        s.add("  behavior: CANCEL")
    emit_flow_tasks(s, f)
    if f.on_error:
        ns, _, fid = f.on_error.rpartition(".")
        s.add("errors:")
        s.add(f"  - id: {fid}")
        s.add("    type: io.kestra.plugin.core.flow.Subflow")
        s.add(f"    namespace: {ns}")
        s.add(f"    flowId: {fid}", mark=f"subflow:{f.on_error}")
        s.add("    inputs:")
        s.add(f'      flow_id: "{f.full_id}"')
        s.add('      execution_id: "{{ execution.id }}"')
    if f.cron:
        s.add("triggers:")
        s.add("  - id: schedule")
        s.add("    type: io.kestra.plugin.core.trigger.Schedule")
        s.add(f'    cron: "{f.cron}"', mark="cron")
        s.add("    timezone: Asia/Tokyo")
    write(target, f.flow_file, s.text())
    return s


def _sql_alias(i: int) -> str:
    return f"t{i}"


def _singular(table: str) -> str:
    name = table.split(".")[1]
    if name.endswith("ies"):
        return name[:-3] + "y"
    if name.endswith("sses"):  # addresses → address
        return name[:-2]
    return name.rstrip("s")


def pyexpr(template: str, inputs: list) -> str:
    """'{date}' のような穴を Python の f-string にする。Flow の inputs は args.<id>、それ以外は row[...] から取る。"""
    if "{" not in template:
        return f'"{template}"'
    names = {iid for iid, _, _ in inputs}
    out = template
    for ph in sorted(set(re.findall(r"\{([a-z_.]+)\}", template))):
        if ph in names:
            rep_ = f"{{args.{ph}}}"
        elif ph == "yyyymm":
            rep_ = "{args.date[:7].replace('-', '')}"
        elif ph == "yyyymmdd":
            rep_ = "{args.date.replace('-', '')}"
        else:
            rep_ = f"{{row['{ph.split('.')[-1]}']}}"
        out = out.replace("{" + ph + "}", rep_)
    return f'f"{out}"'


class JobWriter:
    """Emit a flow's operations and keep the source lines used as evidence."""

    def __init__(self, target, flow, source):
        self.target = target
        self.flow = flow
        self.source = source
        self.truth_io: list[dict] = []
        self.loop_indent: str | None = (
            None  # 直前の I/O が「行ごとのループ」で終わっていれば、その中に続けて書くための字下げ
        )
        self.last_rows: str | None = (
            None  # 直前に定義した rows_N (書き込み側が読む変数)
        )
        self.last_files = "[]"  # 直前に定義した files_N
        self.rename_line: int | None = (
            None  # rename (移動) の行。移動元の削除の根拠に使う
        )
        self.need_render_report = False
        self.step = 0

    def emit(self, io):
        if io in ("notify", "notify_failure"):
            self.emit_notification(io)
            return
        if io["kind"] == "py":
            self.emit_python_step(io)
            return
        self.step += 1
        kind, op = io["kind"], io["op"]
        rows = self.last_rows or "[]"
        self.update_loop_indent(kind, op, io)
        self.source.add("")
        if kind == "rdb" and op == "read":
            self.read_database(io, rows)
        else:
            writer = {
                "rdb": self.write_database,
                "kvs": self.key_value,
                "queue": self.queue,
                "filesystem": self.filesystem,
                "object_storage": self.object_storage,
                "external_api": self.external_api,
            }.get(kind)
            if writer is not None:
                writer(io, rows)

    def update_loop_indent(self, kind, op, io):
        follows_file_write = (kind == "object_storage" and op == "put") or (
            kind == "external_api" and io["method"] == "POST"
        )
        if not follows_file_write:
            self.loop_indent = None

    def emit_notification(self, io):
        self.source.add(IF_WRITES_ENABLED)
        if io == "notify":
            message = f'        notify.post(f"{self.flow.full_id}: done")'
        else:
            message = '        notify.post(f"[kotori] {args.flow_id} が失敗しました (execution {args.execution_id})")'
        self.source.add(message, mark="notify")

    def read_database(self, io, rows):
        kind = io["kind"]
        op = io["op"]
        tables = io["tables"]
        if io.get("stored"):
            self.source.add(f"    rows_{self.step} = []")
            self.source.add(f"    for defn in {rows}:")
            line = self.source.add(
                f'        rows_{self.step}.append({{"report_name": defn["name"], "rows": db.fetch_all(defn["sql"])}})  # 定義に保存された SQL をそのまま実行する'
            )
            self.last_rows = f"rows_{self.step}"
            self.truth_io.append(
                {
                    "kind": kind,
                    "op": op,
                    "levels": dict(DB),
                    "detail": io["detail"],
                    "status": "unknown",
                    "reason": io["unknown"],
                    "note": io["note"],
                    "evidence": [line],
                }
            )
            return
        if io.get("template"):
            self.read_template(io, kind, op, tables)
            return
        self.source.add(f"    rows_{self.step} = db.fetch_all(")
        self.source.add('        """')
        lines, n_ph = self.emit_select(io, tables)
        if io.get("params"):
            self.source.add('        """,')
            self.source.add(f"        {io['params']},")
        elif n_ph:
            self.source.add('        """,')
            self.source.add("        (" + ", ".join(["day"] * n_ph) + ",),")
        else:
            self.source.add('        """')
        self.source.add("    )")
        self.last_rows = f"rows_{self.step}"
        if self.flow.checks:
            name = (io["detail"] or "").split(":")[0].replace("検査 ", "")
            self.source.marks.setdefault("check_rule", len(self.source.lines) + 1)
            self.source.add(
                f'    checks.append({{"checked_at": dt.datetime.now(), "check_name": "{name}", "status": "ok" if rows_{self.step} else "ng", "detail": f"{{len(rows_{self.step})}} 行"}})'
            )
            self.last_rows = "checks"
        for t, line in zip(tables, lines):
            schema, table = t.split(".")
            self.truth_io.append(
                {
                    "kind": kind,
                    "op": op,
                    "levels": {**DB, "schema": schema, "table": table},
                    "detail": io["detail"],
                    "status": "fact",
                    "evidence": [line],
                }
            )

    def write_database(self, io, rows):
        kind = io["kind"]
        op = io["op"]
        schema, table = io["table"].split(".")
        if op == "create":
            cols = io["cols"]
            names = [c.strip() for c in cols.split(",")]
            ph = ", ".join(["%s"] * len(names))
            self.source.add("    db.execute_many(")
            line = self.source.add(
                f'        "INSERT INTO {io["table"]} ({cols}) VALUES ({ph})",'  # nosec B608 - static fixture schema; row values use placeholders
            )
            self.source.add(
                f"        [tuple(r.get(c) for c in ({', '.join(repr(c) for c in names)})) for r in {rows}] if not args.dry_run else [],"
            )
            self.source.add("    )")
        elif op == "update":
            # SET の %s には行のキー (params、省略時は代入先の列名) を順に渡し、最後に id
            targets = io.get("params") or tuple(
                part.split("=")[0].strip()
                for part in io["cols"].split(",")
                if "%s" in part
            )
            values = "".join(f'row["{k}"], ' for k in targets)
            self.source.add(IF_WRITES_ENABLED)
            self.source.add("        db.execute_many(")
            line = self.source.add(
                f'            "UPDATE {io["table"]} SET {io["cols"]} WHERE id = %s",'  # nosec B608 - static fixture schema; row values use placeholders
            )
            self.source.add(f'            [({values}row["id"]) for row in {rows}],')
            self.source.add("        )")
        else:
            if "ANY(%s)" in io["cols"]:
                params = f'([row["id"] for row in {rows}],)'
            elif "%s" in io["cols"]:
                params = "(day,)"
            else:
                params = "()"
            self.source.add(IF_WRITES_ENABLED)
            line = self.source.add(
                f'        db.execute("DELETE FROM {io["table"]} WHERE {io["cols"]}", {params})'  # nosec B608 - static fixture schema; row values use placeholders
            )
        self.truth_io.append(
            {
                "kind": kind,
                "op": op,
                "levels": {**DB, "schema": schema, "table": table},
                "detail": io["detail"],
                "status": "fact",
                "evidence": [line],
                "fields": rdb_fields(op, io["cols"]),
            }
        )

    def key_value(self, io, rows):
        kind = io["kind"]
        op = io["op"]
        key = io["key"]
        expr = pyexpr(key, self.flow.inputs)
        looped = "{" in key
        if op == "get" and key.endswith("*"):
            line = self.source.add(
                f"    rows_{self.step} = [cache.get(key) for key in cache.scan({expr})]"
            )
            self.last_rows = f"rows_{self.step}"
        elif op == "get":
            line = self.source.add(
                f"    rows_{self.step} = [row for row in {rows} if not cache.get({expr})]  # 既に印のある行を除く"
            )
            self.last_rows = f"rows_{self.step}"
        elif op == "set" and looped:
            self.source.add(IF_WRITES_ENABLED)
            self.source.add(f"        for row in {rows}:")
            line = self.source.add(f"            cache.set({expr}, row)")
        elif op == "set":
            self.source.add(IF_WRITES_ENABLED)
            line = self.source.add(f"        cache.set({expr}, {rows})")
        elif op == "expire" and looped:
            self.source.add(IF_WRITES_ENABLED)
            self.source.add(f"        for row in {rows}:")
            line = self.source.add(f"            cache.expire({expr}, {io['ttl']})")
        elif op == "expire":
            self.source.add(IF_WRITES_ENABLED)
            line = self.source.add(f"        cache.expire({expr}, {io['ttl']})")
        else:
            self.source.add(IF_WRITES_ENABLED)
            line = self.source.add(
                f"        cache.delete(*[key for key in cache.scan({expr}) if is_stale(cache.get(key))])"
            )
        self.truth_io.append(
            {
                "kind": kind,
                "op": op,
                "levels": {**CACHE, "key_pattern": key},
                "detail": io["detail"],
                "status": "fact",
                "evidence": [line],
            }
        )

    def queue(self, io, rows):
        kind = io["kind"]
        op = io["op"]
        if op == "publish":
            self.source.add(IF_WRITES_ENABLED)
            line = self.source.add(
                f'        mq.publish("{io["topic"]}", {{"ids": [r["id"] for r in {rows}]}})'
            )
        else:
            line = self.source.add(
                f'    rows_{self.step} = list(mq.consume("{io["topic"]}")) if not args.dry_run else mq.peek("{io["topic"]}")  # dry-run では ACK しない'
            )
            self.last_rows = f"rows_{self.step}"
        self.truth_io.append(
            {
                "kind": kind,
                "op": op,
                "levels": {"broker": BROKER, "topic": io["topic"]},
                "detail": io["detail"],
                "status": "fact",
                "evidence": [line],
            }
        )

    def read_file(self, root, fn_expr, fn):
        if "*" in fn:
            line = self.source.add(f"    rows_{self.step} = []")
            self.source.add(f"    for p in {self.last_files}:")
            self.source.add('        with p.open(encoding="utf-8") as fh:')
            self.source.add(
                f'            rows_{self.step}.extend({{**r, "source_file": p.name}} for r in csv.DictReader(fh))'
            )
            self.last_rows = f"rows_{self.step}"
        else:
            if fn.endswith((".yaml", ".yml")):
                line = self.source.add(
                    f'    rows_{self.step} = yaml.safe_load(({root} / {fn_expr}).read_text(encoding="utf-8"))["digests"]'
                )
            else:
                line = self.source.add(
                    f'    rows_{self.step} = [dict(zip(("sku", "new_price"), l.split("\\t"))) for l in ({root} / {fn_expr}).read_text(encoding="utf-8").splitlines()]'
                )
            self.last_rows = f"rows_{self.step}"
        return line

    def write_file_operation(self, io, root, fn_expr, rows, fn):
        if io.get("unknown") or "row[" in fn_expr:
            line = self.write_row_files(root, fn_expr, rows, fn)
        elif "*" in fn:
            self.source.add(IF_WRITES_ENABLED)
            self.source.add(f"        for p in {self.last_files}:")
            line = self.source.add(f"            p.rename({root} / p.name)")
            self.rename_line = line
        else:
            line = self.write_file(root, fn_expr, rows, fn)
        return line

    def filesystem(self, io, rows):
        kind = io["kind"]
        op = io["op"]
        d, fn = io["directory"], io["file"]
        root = file_root(d)
        fn_expr = pyexpr(fn, self.flow.inputs)
        if op == "list":
            line = self.source.add(
                f'    files_{self.step} = sorted(({root}).glob("{fn}"))'
            )
            self.last_files = f"files_{self.step}"
        elif op == "read" and io.get("dirs"):
            self.read_configured_directories(io, kind, op, root, d, fn, rows)
            return
        elif op == "read":
            line = self.read_file(root, fn_expr, fn)
        elif op == "write":
            line = self.write_file_operation(io, root, fn_expr, rows, fn)
        elif op == "append":
            self.source.add(IF_WRITES_ENABLED)
            line = self.source.add(
                f'        with ({root} / {fn_expr}).open("a", encoding="utf-8") as fh:'
            )
            self.source.add(
                f"            fh.write(json.dumps({rows}, default=str) + '\\n')"
            )
        elif self.rename_line:
            self.source.lines.pop()  # この I/O は文を足さない (直前の空行を戻す)
            line = self.rename_line  # rename で移動元が消える (同じ行が根拠)
        else:
            self.source.add(IF_WRITES_ENABLED)
            line = self.source.add(
                f"        ({root} / {fn_expr}).unlink(missing_ok=True)"
            )
        self.record_file_access(io, kind, op, d, fn, line)

    def object_storage(self, io, _rows):
        kind = io["kind"]
        op = io["op"]
        bucket = BUCKETS[io["bucket_const"]]
        if op == "put" and self.loop_indent:
            self.source.lines.pop()  # 直前の空行を戻し、行ごとのループの中に続ける (1 ファイル書くごとに置く)
            line = self.source.add(
                f'{self.loop_indent}storage.put_object(settings.{io["bucket_const"]}, "{io["prefix"]}" + out.name, out.read_bytes())'
            )
        elif op == "put":
            self.source.add(IF_WRITES_ENABLED)
            line = self.source.add(
                f'        storage.put_object(settings.{io["bucket_const"]}, "{io["prefix"]}" + out.name, out.read_bytes())'
            )
        elif op == "get":
            line = self.source.add(
                f'    body = storage.get_object(settings.{io["bucket_const"]}, "{io["prefix"]}" + name)'
            )
        elif op == "list":
            line = self.source.add(
                f'    keys = storage.list_objects(settings.{io["bucket_const"]}, "{io["prefix"]}")'
            )
        else:
            self.source.add(IF_WRITES_ENABLED)
            line = self.source.add(
                f"        storage.delete_object(settings.{io['bucket_const']}, key)"
            )
        self.truth_io.append(
            {
                "kind": kind,
                "op": op,
                "levels": {"bucket": bucket, "prefix": io["prefix"]},
                "detail": io["detail"],
                "status": "fact",
                "evidence": [line],
            }
        )

    def external_api(self, io, rows):
        kind = io["kind"]
        op = io["op"]
        fn = "get_json" if io["method"] == "GET" else "post_json"
        path = io["path"]
        path_expr = f'f"{path}"' if "{" in path else f'"{path}"'
        if "{tracking_no}" in path:
            path_expr = "f\"/v2/tracking/{row['tracking_no']}\""
        if io["host_const"]:
            host_expr = f"settings.{io['host_const']}"
            levels = {"host": HOSTS[io["host_const"]], "path": path}
            entry = {"status": "fact"}
        else:
            host_expr = 'os.environ["KOTORI_MODERATION_API_HOST"]'
            levels = {"path": path}
            entry = {
                "status": "unknown",
                "reason": io["unknown"],
                "note": io["note"],
            }
        if io["method"] == "GET" and "{" not in path:
            line = self.source.add(
                f'    rows_{self.step} = http.{fn}({host_expr}, {path_expr})["items"]'
            )
            self.last_rows = f"rows_{self.step}"
        elif io["method"] == "GET":
            self.source.add(f"    for row in {rows}:")
            line = self.source.add(
                f"        row.update(http.{fn}({host_expr}, {path_expr}))"
            )
        elif self.loop_indent:
            # 直前の「行ごとにファイルを書く」ループの中で、書いたファイルを添付して送る
            self.source.lines.pop()
            line = self.source.add(
                f'{self.loop_indent}http.{fn}({host_expr}, {path_expr}, {{**row, "attachment": {{"name": out.name, "content_base64": base64.b64encode(out.read_bytes()).decode()}}}})'
            )
        else:
            self.source.add(f"    for row in {rows}:")
            self.source.add("        if args.dry_run:")
            self.source.add("            continue")
            line = self.source.add(f"        http.{fn}({host_expr}, {path_expr}, row)")
        self.truth_io.append(
            {
                "kind": kind,
                "op": op,
                "levels": levels,
                "detail": io["detail"],
                "evidence": [line],
                **entry,
            }
        )

    def record_file_access(self, io, kind, op, d, fn, line):
        levels = {"directory": d, "file": fn}
        entry = {
            "kind": kind,
            "op": op,
            "levels": levels,
            "detail": io["detail"],
            "status": "fact",
            "evidence": [line],
        }
        if io.get("unknown"):
            entry.update(status="unknown", reason=io["unknown"], note=io["note"])
            entry["levels"] = {
                "directory": d
            }  # ファイル名 (と下のディレクトリ) は実行時に決まる
        self.truth_io.append(entry)

    def write_file(self, root, fn_expr, rows, fn):
        self.source.add(f"    out = {root} / {fn_expr}")
        self.source.add(IF_WRITES_ENABLED)
        self.source.add("        out.parent.mkdir(parents=True, exist_ok=True)")
        if fn.endswith(".csv"):
            line = self.source.add(
                '        with out.open("w", newline="", encoding="utf-8") as fh:'
            )
            self.source.add(
                f"            csv.writer(fh).writerows(r.values() for r in {rows})"
            )
        elif fn.endswith(".jsonl"):
            line = self.source.add(
                f'        out.write_text("".join(json.dumps(r, ensure_ascii=False, default=str) + "\\n" for r in {rows}), encoding="utf-8")'
            )
        else:
            line = self.source.add(f"        out.write_bytes(render_report({rows}))")
            self.need_render_report = True
        return line

    def write_row_files(self, root, fn_expr, rows, fn):
        self.source.add(IF_WRITES_ENABLED)
        line = self.source.add(f"        for row in {rows}:")
        self.source.add(f"            out = {root} / {fn_expr}")
        self.source.add("            out.parent.mkdir(parents=True, exist_ok=True)")
        if fn.endswith(".csv"):
            self.source.add(
                '            with out.open("w", newline="", encoding="utf-8") as fh:'
            )
            self.source.add(
                '                csv.writer(fh).writerows(r.values() for r in (row["rows"] if "rows" in row else [row]))'
            )
        else:
            self.source.add("            out.write_bytes(render_report(row))")
            self.need_render_report = True
        self.loop_indent = "            "
        return line

    def read_configured_directories(self, io, kind, op, root, d, fn, rows):
        # 設定ファイルに列挙されたディレクトリを順に読む。設定は同梱なので 1 ディレクトリずつ fact (根拠は設定の行と読む行)
        self.source.add(f"    rows_{self.step} = []")
        line = self.source.add(
            f"    for row in {rows}:  # config/digests.yaml の各エントリ (dir, title)"
        )
        self.source.add(
            f'        for p in sorted(({root} / row["dir"]).glob(f"*_{{args.date}}.csv")):'
        )
        self.source.add(
            f'            rows_{self.step}.append({{"title": row["title"], "file": p.name, "body": p.read_text(encoding="utf-8")}})'
        )
        self.last_rows = f"rows_{self.step}"
        cfg_lines = (
            (self.target / CONFIG_DIGESTS_YAML).read_text(encoding="utf-8").splitlines()
        )
        for sub_dir in io["dirs"]:
            cl = next(
                i
                for i, line_text in enumerate(cfg_lines, 1)
                if line_text.strip() == f"- dir: {sub_dir}"
            )
            self.truth_io.append(
                {
                    "kind": kind,
                    "op": op,
                    "levels": {
                        "directory": f"{d}/{sub_dir}",
                        "file": fn.replace("{dir}/", ""),
                    },
                    "detail": io["detail"],
                    "status": "fact",
                    "evidence": [(CONFIG_DIGESTS_YAML, cl), line],
                    "note": "読むディレクトリは config/digests.yaml に列挙されている (設定を変えれば変わる)",
                }
            )

    def emit_select(self, io, tables):
        lines = []
        if io.get("select"):
            # 集計・分類を実装した SELECT。表が最初に出てくる行を根拠にする
            emitted = [self.source.add("        " + ln) for ln in io["select"]]
            for t in tables:
                lines.append(next(e for e, ln in zip(emitted, io["select"]) if t in ln))
            n_ph = sum(ln.count("%s") for ln in io["select"])
        else:
            self.source.add(f"        SELECT {_sql_alias(0)}.*")
            for i, t in enumerate(tables):
                if i == 0:
                    lines.append(self.source.add(f"        FROM {t} {_sql_alias(0)}"))
                else:
                    cond = (
                        f"{_sql_alias(i)}.{_singular(tables[0])}_id = t0.id"
                        if i == 1
                        else f"{_sql_alias(i)}.id = t1.{_singular(t)}_id"
                    )
                    lines.append(
                        self.source.add(f"        JOIN {t} {_sql_alias(i)} ON {cond}")
                    )
            where = (
                io.get("where")
                or "t0.updated_at >= %s::date - interval '1 day' AND t0.updated_at < %s::date"
            )
            self.source.add(f"        WHERE {where}")
            n_ph = where.count("%s")
        return lines, n_ph

    def read_template(self, io, kind, op, tables):
        tline = self.source.add(
            f'    template = Path("{self.flow.template_sql}").read_text(encoding="utf-8")',
            mark=f"io{self.step}:template",
        )
        self.source.add("    sql = jinja2.Template(template).render(month=args.month)")
        line = self.source.add(f"    rows_{self.step} = db.fetch_all(sql)")
        self.last_rows = f"rows_{self.step}"
        tdir, tfile = self.flow.template_sql.rsplit("/", 1)
        self.truth_io.append(
            {
                "kind": "filesystem",
                "op": "read",
                "levels": {"directory": tdir, "file": tfile},
                "detail": "KPI の SQL テンプレート (Jinja)",
                "status": "fact",
                "evidence": [tline],
            }
        )
        tpl_lines = (
            (self.target / self.flow.template_sql)
            .read_text(encoding="utf-8")
            .splitlines()
        )
        for t in tables:
            tl = next(i for i, line_text in enumerate(tpl_lines, 1) if t in line_text)
            schema, table = t.split(".")
            self.truth_io.append(
                {
                    "kind": kind,
                    "op": op,
                    "levels": {**DB, "schema": schema, "table": table},
                    "detail": io["detail"],
                    "status": "fact",
                    "evidence": [(self.flow.template_sql, tl), line],
                    "note": "SQL は実行時に Jinja で month を埋めて組み立てるが、表名はテンプレートに静的に書かれている",
                }
            )

    def emit_python_step(self, io):
        self.step += 1  # 変数名 rows_N の番号を飛ばす (py の結果名と重ならないように)
        self.source.add("")
        for ln in io["lines"]:
            self.source.add("    " + ln)
        if io["rows"]:
            self.last_rows = io["rows"]
        self.loop_indent = None

    def finish(self):
        self.source.add("")
        self.source.add(f'    print(f"{self.flow.full_id}: ok")')
        self.source.add("    return 0")
        if self.need_render_report:
            self.source.add("")
            self.source.add("")
            self.source.add("def render_report(rows) -> bytes:")
            self.source.add(
                '    """行 (または 1 行) を人が読める帳票にする (サンプルなので文字列化だけ)。"""'
            )
            self.source.add(
                '    return "\\n".join(str(r) for r in (rows if isinstance(rows, list) else [rows])).encode()'
            )
        if any(
            isinstance(io, dict) and io["kind"] == "kvs" and io["op"] == "delete"
            for io in self.flow.io
        ):
            self.source.add("")
            self.source.add("")
            self.source.add("def is_stale(value) -> bool:")
            self.source.add(
                '    return not value or value.get("last_seen", "") < (dt.date.today() - dt.timedelta(days=90)).isoformat()'
            )
        self.source.add("")
        self.source.add("")
        self.source.add('if __name__ == "__main__":')
        self.source.add("    raise SystemExit(main())")


def emit_job_parser(s, f):
    s.add("def parse_args() -> argparse.Namespace:")
    s.add("    ap = argparse.ArgumentParser(description=__doc__)")
    for iid, typ, help_ in f.inputs:
        opt = "--" + iid.replace("_", "-")
        default = " default=dt.date.today().isoformat()," if typ == "DATE" else ""
        s.add(
            f'    ap.add_argument("{opt}",{default} help="{help_}")', mark=f"arg:{iid}"
        )
    s.add(
        '    ap.add_argument("--dry-run", action="store_true", help="書き込みと外部呼び出しをせず件数だけ出す")',
        mark="arg:dry_run",
    )
    s.add("    return ap.parse_args()")
    s.add("")
    s.add("")


def emit_project_imports(s, kinds, uses_notify):
    s.add(SETTINGS_IMPORT)
    libs = [
        LIBS[k][3]
        for k in ("rdb", "kvs", "object_storage", "external_api", "queue")
        if k in kinds
    ]
    if uses_notify:
        libs.append("notify")
    if libs:
        s.add(f"from jobs.lib import {', '.join(libs)}", mark="import_libs")
    s.add("")
    s.add("")


def emit_third_party_imports(s, f):
    third = []
    if f.template_sql:
        third.append("import jinja2")
    if any(
        isinstance(io, dict)
        and io["kind"] == "filesystem"
        and io["file"].endswith((".yaml", ".yml"))
        for io in f.io
    ):
        third.append("import yaml")
    if third:
        for t in third:
            s.add(t)
        s.add("")


def add_payload_encoding_import(std, f):
    api_after_write = False
    for io in f.io:
        if isinstance(io, dict) and io["kind"] == "filesystem" and io["op"] == "write":
            api_after_write = True
        elif isinstance(io, dict) and io["kind"] == "external_api" and api_after_write:
            std.append("base64")
            break
        elif isinstance(io, dict) and io["kind"] != "object_storage":
            api_after_write = False


def emit_standard_imports(s, f, kinds):
    std = ["argparse", "datetime as dt"]
    if "filesystem" in kinds:
        std.extend(["csv", "json"])
    add_payload_encoding_import(std, f)
    if f.binary:
        std.append("subprocess")
    if any(
        isinstance(io, dict) and io.get("unknown") == "not_traceable_in_repo"
        for io in f.io
    ):
        std.append("os")
    for mod in sorted(std):
        s.add(f"import {mod}")
    if "filesystem" in kinds or f.binary:
        s.add("from pathlib import Path")
    s.add("")


def gen_job(target: Path, f: Flow) -> tuple[Src, list[dict]]:
    """ジョブモジュールを書き、I/O ごとの根拠行を含む「正解の I/O」を返す。"""
    s = Src()
    s.add(f'"""{f.desc}"""', mark="doc")
    s.add(FUTURE_ANNOTATIONS_IMPORT)
    s.add("")
    kinds = {io["kind"] for io in f.io if isinstance(io, dict)}
    uses_notify = "notify" in f.io or "notify_failure" in f.io
    emit_standard_imports(s, f, kinds)
    emit_third_party_imports(s, f)
    emit_project_imports(s, kinds, uses_notify)
    emit_job_parser(s, f)
    s.add("def main() -> int:", mark="main")
    s.add("    args = parse_args()")
    if "rdb" in kinds:
        s.add(
            '    day = getattr(args, "date", None) or getattr(args, "week_start", None) or getattr(args, "month", None)  # 対象日 (窓の終わり)'
        )
    if f.checks:
        s.add(
            "    checks: list[dict] = []  # 検査 1 項目 = 1 行 (audit.data_quality に書く)"
        )
    if f.binary:
        s.add(
            "    # 旧価格計算エンジン (ソースの無いバイナリ) を先に動かして価格表を書かせ、その出力を下で読む。dry-run では動かさない (前回の出力を読む)"
        )
        s.add(IF_WRITES_ENABLED)
        s.add(
            '        subprocess.run(["bin/legacy_pricing", "--out", str(Path(settings.TMP_DIR) / "pricing.out")], check=True)',
            mark="binary",
        )
    writer = JobWriter(target, f, s)
    for io in f.io:
        writer.emit(io)
    writer.finish()
    write(target, f"jobs/{f.id}.py", s.text())
    return s, writer.truth_io


# ---------------------------------------------------------------- 正解 (分析結果 YAML)


def ev(file: str, *lines: int) -> list[dict]:
    return [{"file": file, "line": n} for n in lines]


def called(c: dict, when: str = "always", condition: str | None = None) -> dict:
    """呼び出しの主張に、いつ起きるか (when) を足す。項目の並びは status → when → condition → 残り。"""
    out = {"status": c["status"], "when": when}
    if condition:
        out["condition"] = condition
    out.update({k: v for k, v in c.items() if k != "status"})
    return out


def claim(
    status: str, value: str | None, evidence: list[dict] | None = None, **extra
) -> dict:
    c: dict = {"status": status}
    if value is not None:
        c["value"] = value
    if evidence:
        c["evidence"] = evidence
    c.update(extra)
    return c


def append_external_frames(frames, f, fid, job_file, job_src, common):
    if "notify" in f.io or "notify_failure" in f.io:
        nt = common[JOBS_LIB_NOTIFY_PY]
        frames.append(
            {
                "id": fid("lib_notify"),
                "layer": "program",
                "kind": "module",
                "name": "jobs.lib.notify",
                "source": {"file": JOBS_LIB_NOTIFY_PY, "line": 1},
                "caller": fid("job"),
                "call": called(
                    claim(
                        "fact",
                        None,
                        ev(job_file, job_src.marks["notify"]),
                        note="Flow は --dry-run を渡さない (run_job.sh は受け取った引数をそのまま渡す) ので、--dry-run のときだけ飛ばす枝は閉じていて、いつも呼ぶ",
                    ),
                ),
                "settings": [
                    {
                        "name": "KOTORI_CHAT_WEBHOOK",
                        "kind": "env",
                        "effect": "通知の送り先。未設定なら、何も送らない",
                        "status": "fact",
                        "evidence": ev(JOBS_LIB_NOTIFY_PY, nt.marks["url"]),
                    }
                ],
                "tests": [
                    {
                        "name": "test_post_without_webhook_does_nothing",
                        "kind": "unit",
                        "status": "fact",
                        "evidence": ev(
                            TESTS_TEST_NOTIFY_PY,
                            common[TESTS_TEST_NOTIFY_PY].marks["test"],
                        ),
                    }
                ],
                "summary": claim(
                    "interpretation",
                    "運用チャットの Webhook に文字列を POST する。URL が未設定なら何もしない",
                    ev(JOBS_LIB_NOTIFY_PY, nt.marks["url"], nt.marks["post"]),
                ),
                "io": [
                    {
                        "op": "call",
                        "status": "unknown",
                        "reason": "not_traceable_in_repo",
                        "resource": {"kind": "external_api", "levels": {}},
                        "detail": "チャットの Webhook (POST, JSON の text)",
                        "note": "URL は環境変数 KOTORI_CHAT_WEBHOOK で、リポジトリに無い",
                        "evidence": ev(JOBS_LIB_NOTIFY_PY, nt.marks["url"]),
                    }
                ],
            }
        )
        frames.append(
            {
                "id": fid("requests_notify"),
                "layer": "external",
                "kind": "library",
                "name": "requests",
                "source": {"file": JOBS_LIB_NOTIFY_PY, "line": nt.marks["import"]},
                "caller": fid("lib_notify"),
                "call": called(
                    claim("fact", None, ev(JOBS_LIB_NOTIFY_PY, nt.marks["post"])),
                    "conditional",
                    "KOTORI_CHAT_WEBHOOK が設定されているとき",
                ),
            }
        )
    if f.binary:
        frames.append(
            {
                "id": fid("legacy_pricing"),
                "layer": "program",
                "kind": "binary",
                "name": BIN_LEGACY_PRICING,
                "source": {"file": BIN_LEGACY_PRICING, "line": 1},
                "caller": fid("job"),
                "call": called(
                    claim(
                        "fact",
                        None,
                        ev(job_file, job_src.marks["binary"]),
                        note="Flow は --dry-run を渡さない (run_job.sh は受け取った引数をそのまま渡す) ので、--dry-run のときだけ飛ばす枝は閉じていて、いつも呼ぶ",
                    ),
                ),
                "summary": claim(
                    "unknown",
                    None,
                    reason="binary_or_vendored",
                    note="ソースの無いコンパイル済み成果物 (のつもりで置いた代替ファイル)。var/tmp/pricing.out に価格表を書くことは呼び出し側の読み取りから分かるが、何を読むかは外から読めない",
                ),
            }
        )


def append_library_frames(frames, truth_io, fid, job_file, job_src, common):
    kinds_used = {t["kind"] for t in truth_io}
    for kind in ("rdb", "kvs", "object_storage", "external_api", "queue"):
        if kind not in kinds_used:
            continue
        lib_id, lib_file, ext, _ = LIBS[kind]
        lib_src = common[lib_file]
        frames.append(
            {
                "id": fid(lib_id),
                "layer": "program",
                "kind": "module",
                "name": lib_file.removesuffix(".py").replace("/", "."),
                "source": {"file": lib_file, "line": 1},
                "caller": fid("job"),
                "call": called(
                    claim("fact", None, ev(job_file, job_src.marks["import_libs"]))
                ),
                "summary": claim(
                    "interpretation", lib_src.lines[0].strip('"'), ev(lib_file, 1)
                ),
            }
        )
        frames.append(
            {
                "id": fid(ext),
                "layer": "external",
                "kind": "library",
                "name": ext,
                "source": {"file": lib_file, "line": lib_src.marks["import"]},
                "caller": fid(lib_id),
                "call": called(
                    claim(
                        "fact",
                        None,
                        ev(
                            lib_file,
                            lib_src.marks["connect"]
                            if "connect" in lib_src.marks
                            else lib_src.marks["post"],
                        ),
                    )
                ),
            }
        )


def add_job_io(job_frame, truth_io, job_file):
    job_frame["io"] = []
    for t in truth_io:
        evidence = [
            {"file": e[0], "line": e[1]}
            if isinstance(e, tuple)
            else {"file": job_file, "line": e}
            for e in t["evidence"]
        ]
        io = {
            "op": t["op"],
            "status": t["status"],
            "resource": {"kind": t["kind"], "levels": t["levels"]},
            "detail": t["detail"],
            "evidence": evidence,
        }
        if t["status"] == "unknown":
            io["reason"] = t["reason"]
        if t.get("note"):
            io["note"] = t["note"]
        if t.get("fields"):
            io["fields"] = t["fields"]
        job_frame["io"].append(io)


def append_shell_frame(frames, f, fid, flow_file, flow_src, common):
    script = f"scripts/{f.id}.sh"
    sh = common[script]
    frame = {
        "id": fid("script"),
        "layer": "shell",
        "kind": "script",
        "name": script,
        "source": {"file": script, "line": 1},
        "caller": fid("flow"),
        "call": called(claim("fact", None, ev(flow_file, flow_src.marks["command"]))),
        "summary": claim("interpretation", f.desc, ev(script, 2)),
    }
    if f.id == "db_snapshot":
        frame["settings"] = [
            {
                "name": "KOTORI_ENV",
                "kind": "env",
                "effect": "読む設定ファイル config/<env>.env を選ぶ (接続先とバケット名が変わる)",
                "status": "fact",
                "evidence": ev(script, sh.marks["source_env"]),
                "note": "Flow の env で prod",
            }
        ]
        frame["parameters"] = [
            {
                "name": "env.KOTORI_ENV",
                "value": "読む設定ファイル config/<env>.env を選ぶ。Flow からは prod",
                "status": "fact",
                "evidence": ev(script, sh.marks["source_env"]),
            },
            {
                "name": "env.KOTORI_DATABASE_URL",
                "value": "pg_dump の接続先。config/prod.env で postgresql://kotori@db.internal:5432/kotori (パスワードは実行環境の PGPASSWORD)",
                "status": "fact",
                "evidence": ev(script, sh.marks["pg_dump"]) + ev("config/prod.env", 2),
            },
        ]
        frame["io"] = [
            {
                "op": "read",
                "status": "fact",
                "resource": {
                    "kind": "filesystem",
                    "levels": {"directory": "config", "file": "prod.env"},
                },
                "detail": "接続先とバケット名",
                "evidence": ev(script, sh.marks["source_env"]),
            },
            {
                "op": "read",
                "status": "fact",
                "resource": {"kind": "rdb", "levels": dict(DB)},
                "detail": "pg_dump でデータベース全体 (全スキーマ・全テーブル) を読む",
                "evidence": ev(script, sh.marks["pg_dump"]),
            },
            {
                "op": "write",
                "status": "fact",
                "resource": {
                    "kind": "filesystem",
                    "levels": {
                        "directory": VAR_BACKUP,
                        "file": "kotori_{yyyymmdd}.dump",
                    },
                },
                "detail": "custom 形式のダンプ",
                "evidence": ev(script, sh.marks["pg_dump"]),
            },
            {
                "op": "delete",
                "status": "fact",
                "resource": {
                    "kind": "filesystem",
                    "levels": {"directory": VAR_BACKUP, "file": "kotori_*.dump"},
                },
                "detail": "`-mtime +7` に当たるもの (経過日数を切り捨てて 7 より大きい = 8 日以上前)",
                "evidence": ev(script, sh.marks["prune"]),
            },
            # 外部のコマンドの読み書きは、呼ぶ側の段に書く (プロファイルの context.md の決まり)
            {
                "op": "put",
                "status": "fact",
                "resource": {
                    "kind": "object_storage",
                    "levels": {
                        "bucket": BUCKETS["BACKUPS_BUCKET"],
                        "prefix": "db/{yyyymmdd}/",
                    },
                },
                "detail": "aws s3 cp で、ダンプを日付のプレフィックスに置く。バケット名は config/prod.env の BACKUPS_BUCKET",
                "evidence": ev(script, sh.marks["aws_cp"]),
            },
        ]
        frames.append(frame)
        frames.append(
            {
                "id": fid("pg_dump"),
                "layer": "external",
                "kind": "cli",
                "name": "pg_dump",
                "source": {"file": script, "line": sh.marks["pg_dump"]},
                "caller": fid("script"),
                "call": called(claim("fact", None, ev(script, sh.marks["pg_dump"]))),
            }
        )
        frames.append(
            {
                "id": fid("aws_cli"),
                "layer": "external",
                "kind": "cli",
                "name": "aws s3 cp",
                "source": {"file": script, "line": sh.marks["aws_cp"]},
                "caller": fid("script"),
                "call": called(claim("fact", None, ev(script, sh.marks["aws_cp"]))),
            }
        )
    else:  # rotate_logs
        frame["io"] = [
            {
                "op": "list",
                "status": "fact",
                "resource": {
                    "kind": "filesystem",
                    "levels": {"directory": VAR_LOG_JOBS, "file": "*.log"},
                },
                "detail": "`-mtime +1` に当たるログ (経過日数を切り捨てて 1 より大きい = 2 日以上前) を find で選ぶ",
                "evidence": ev(script, sh.marks["gzip"]),
            },
            {
                "op": "read",
                "status": "fact",
                "resource": {
                    "kind": "filesystem",
                    "levels": {"directory": VAR_LOG_JOBS, "file": "*.log"},
                },
                "detail": "gzip が中身を読んで圧縮する",
                "evidence": ev(script, sh.marks["gzip"]),
            },
            {
                "op": "write",
                "status": "fact",
                "resource": {
                    "kind": "filesystem",
                    "levels": {"directory": VAR_LOG_JOBS, "file": "*.log.gz"},
                },
                "detail": "gzip の出力",
                "evidence": ev(script, sh.marks["gzip"]),
            },
            {
                "op": "delete",
                "status": "fact",
                "resource": {
                    "kind": "filesystem",
                    "levels": {"directory": VAR_LOG_JOBS, "file": "*.log"},
                },
                "detail": "gzip -f は元ファイルを消す",
                "evidence": ev(script, sh.marks["gzip"]),
            },
            {
                "op": "delete",
                "status": "fact",
                "resource": {
                    "kind": "filesystem",
                    "levels": {"directory": VAR_LOG_JOBS, "file": "*.log.gz"},
                },
                "detail": "`-mtime +30` に当たるもの (経過日数を切り捨てて 30 より大きい = 31 日以上前)",
                "evidence": ev(script, sh.marks["prune"]),
            },
        ]
        frames.append(frame)


def append_subflows(frames, flow_frame, f, prefix, fid, flow_file, flow_src, common):
    for sub in f.subflows + ([f.on_error] if f.on_error else []):
        child = FLOW_BY_ID[sub]
        child_flow_src, child_job_src, child_truth = ARTIFACTS[sub]
        note_ev = ev(flow_file, flow_src.marks[f"subflow:{sub}"])
        when = (
            (
                "on_failure",
                "この Flow のいずれかのタスク (Subflow) が失敗したとき (errors)",
            )
            if sub == f.on_error
            else ("always",)
        )
        frames.extend(
            frames_for(
                child,
                child_flow_src,
                child_job_src,
                child_truth,
                common,
                prefix=f"{prefix}{child.id}__",
                caller=fid("flow"),
                call_ev=note_ev,
                call_when=when,
            )
        )
        # 呼ぶ Flow は、それ自体も入口。処理は下に展開してあるが、入口どうしのつながりとしても書く
        flow_frame.setdefault("links", []).append(
            {
                "kind": "trigger",
                "target": sub,
                "entry_id": sub,
                "status": "fact",
                "evidence": note_ev,
            }
        )


def add_flow_parameters(flow_frame, f, flow_file, flow_src):
    params = []
    if f.cron:
        params.append(
            {
                "name": "triggers.schedule.cron",
                "value": f"{f.cron} (Asia/Tokyo)",
                "status": "fact",
                "evidence": ev(flow_file, flow_src.marks["cron"]),
            }
        )
    else:
        params.append(
            {
                "name": "triggers",
                "value": "無し (他の Flow から Subflow として呼ばれる)",
                "status": "fact",
                "evidence": ev(flow_file, 1),
            }
        )
    for iid, typ, help_ in f.inputs:
        params.append(
            {
                "name": f"inputs.{iid}",
                "value": f"{typ}。{help_}",
                "status": "fact",
                "evidence": ev(flow_file, flow_src.marks[f"input:{iid}"]),
            }
        )
    if f.concurrency:
        params.append(
            {
                "name": "concurrency",
                "value": "limit 1, behavior CANCEL",
                "status": "fact",
                "evidence": ev(flow_file, flow_src.marks["concurrency"]),
            }
        )
    flow_frame["parameters"] = params


def frames_for(
    f: Flow,
    flow_src: Src,
    job_src: Src | None,
    truth_io: list[dict],
    common: dict[str, Src],
    prefix: str = "",
    caller: str | None = None,
    call_ev: list[dict] | None = None,
    call_when: tuple = ("always",),
) -> list[dict]:
    """1 つの Flow のフレーム列。prefix を付けると Subflow として親の結果に埋め込める。"""
    fid = lambda x: f"{prefix}{x}"  # noqa: E731
    flow_file = f.flow_file
    frames: list[dict] = []
    flow_frame = {
        "id": fid("flow"),
        "layer": "scheduler",
        "kind": "subflow" if prefix else "flow",
        "name": f.full_id,
        "source": {"file": flow_file, "line": 1},
        "caller": caller,
    }
    if caller:
        flow_frame["call"] = called(
            claim("fact", None, call_ev, note="Subflow として呼ばれる (wait: true)"),
            *call_when,
        )
    flow_frame["summary"] = claim(
        "interpretation", f.desc, ev(flow_file, flow_src.marks["description"])
    )
    add_flow_parameters(flow_frame, f, flow_file, flow_src)
    frames.append(flow_frame)

    if f.kind == "orchestrator":
        append_subflows(frames, flow_frame, f, prefix, fid, flow_file, flow_src, common)
        return frames

    if f.kind == "shell":
        append_shell_frame(frames, f, fid, flow_file, flow_src, common)
        return frames

    # python ジョブ: flow → run_job.sh → jobs/<id>.py → lib → 外部ライブラリ
    rj = common[SCRIPTS_RUN_JOB_SH]
    job_file = f"jobs/{f.id}.py"
    frames.append(
        {
            "id": fid("run_job"),
            "layer": "shell",
            "kind": "script",
            "name": SCRIPTS_RUN_JOB_SH,
            "source": {"file": SCRIPTS_RUN_JOB_SH, "line": 1},
            "caller": fid("flow"),
            "call": called(
                claim("fact", None, ev(flow_file, flow_src.marks["command"]))
            ),
            "guards": [
                {
                    "kind": "other",
                    "value": "$(id -un) = $KOTORI_RUN_USER",
                    "status": "fact",
                    "evidence": ev(SCRIPTS_RUN_JOB_SH, rj.marks["run_user"]),
                    "note": "実行ユーザーの確認。KOTORI_RUN_USER が設定されているときだけ行い、違えば 77 で終わる",
                }
            ],
            "settings": [
                {
                    "name": "KOTORI_ENV",
                    "kind": "env",
                    "effect": "読む設定ファイル config/<env>.env を選ぶ (接続先とバケット名が変わる)",
                    "status": "fact",
                    "evidence": ev(SCRIPTS_RUN_JOB_SH, rj.marks["env_file"]),
                },
                {
                    "name": "KOTORI_RUN_USER",
                    "kind": "env",
                    "effect": "設定されていれば、実行ユーザーを確かめる。未設定なら確かめない",
                    "status": "fact",
                    "evidence": ev(SCRIPTS_RUN_JOB_SH, rj.marks["run_user"]),
                },
            ],
            "summary": claim(
                "interpretation",
                "config/<env>.env を読み、python3 -m jobs.<job> を実行して標準出力をジョブごとのログに追記する共通ランナー",
                ev(SCRIPTS_RUN_JOB_SH, 2, rj.marks["python"]),
            ),
            "parameters": [
                {
                    "name": "JOB",
                    "value": f"{f.id} (第 1 引数。実行するモジュール jobs.{f.id} とログ名になる)",
                    "status": "fact",
                    "evidence": ev(flow_file, flow_src.marks["command"])
                    + ev(SCRIPTS_RUN_JOB_SH, 5),
                },
                {
                    "name": "env.KOTORI_ENV",
                    "value": "読む設定ファイル config/<env>.env を選ぶ。Flow の env で prod",
                    "status": "fact",
                    "evidence": ev(flow_file, flow_src.marks["env"])
                    + ev(SCRIPTS_RUN_JOB_SH, rj.marks["env_file"]),
                },
            ],
            "io": [
                {
                    "op": "read",
                    "status": "fact",
                    "resource": {
                        "kind": "filesystem",
                        "levels": {"directory": "config", "file": "prod.env"},
                    },
                    "detail": "source で読む (接続先・バケット名)",
                    "evidence": ev(SCRIPTS_RUN_JOB_SH, rj.marks["source_env"]),
                },
                {
                    "op": "append",
                    "status": "fact",
                    "resource": {
                        "kind": "filesystem",
                        "levels": {"directory": VAR_LOG_JOBS, "file": f"{f.id}.log"},
                    },
                    "detail": "開始・終了の行と、ジョブの標準出力 (tee -a)",
                    "evidence": ev(
                        SCRIPTS_RUN_JOB_SH, rj.marks["log_start"], rj.marks["python"]
                    ),
                },
            ],
        }
    )
    job_frame: dict = {
        "id": fid("job"),
        "layer": "program",
        "kind": "module",
        "name": f"jobs.{f.id}",
        "source": {"file": job_file, "line": 1},
        "caller": fid("run_job"),
        "call": called(
            claim(
                "fact",
                None,
                ev(SCRIPTS_RUN_JOB_SH, rj.marks["python"]),
                note=f"JOB={f.id} なので jobs.{f.id} が動く",
            )
        ),
        "summary": claim(
            "interpretation",
            f.desc,
            ev(job_file, job_src.marks["doc"], job_src.marks["main"]),
        ),
    }
    params = [
        {
            "name": "--dry-run",
            "value": "書き込みと外部呼び出しをせず件数だけ出す",
            "status": "fact",
            "evidence": ev(job_file, job_src.marks["arg:dry_run"]),
        }
    ]
    for iid, typ, help_ in f.inputs:
        params.append(
            {
                "name": "--" + iid.replace("_", "-"),
                "value": f"{help_} (Flow の inputs.{iid} から)",
                "status": "fact",
                "evidence": ev(job_file, job_src.marks[f"arg:{iid}"]),
            }
        )
    job_frame["parameters"] = params
    if "check_rule" in job_src.marks:
        job_frame["rules"] = [
            {
                "kind": "validation",
                "value": "検査ごとに、読んだ行が 1 件でもあれば ok、1 件も無ければ ng とする",
                "status": "fact",
                "evidence": ev(job_file, job_src.marks["check_rule"]),
            }
        ]
    add_job_io(job_frame, truth_io, job_file)
    frames.append(job_frame)
    append_library_frames(frames, truth_io, fid, job_file, job_src, common)
    append_external_frames(frames, f, fid, job_file, job_src, common)
    return frames


def result_for(
    f: Flow,
    flow_src: Src,
    job_src: Src | None,
    truth_io: list[dict],
    common: dict[str, Src],
    target_meta: dict,
) -> dict:
    frames = frames_for(f, flow_src, job_src, truth_io, common)
    frames[0]["caller"] = None
    ev_summary = ev(f.flow_file, flow_src.marks["description"])
    if job_src is not None:
        ev_summary += ev(f"jobs/{f.id}.py", job_src.marks["doc"])
    elif f.kind == "shell":
        ev_summary += ev(f"scripts/{f.id}.sh", 2)
    return {
        "format_version": 1,
        "entry": {
            "id": f.full_id,
            "path": "/" + f.ns.replace(".", "/") + "/" + f.id,
            "name": f.id,
            "layer": "scheduler",
            "source": {"file": f.flow_file, "line": 1},
        },
        "target": target_meta,
        "analyzer": {
            "profile": {"id": PROFILE_ID, "version": PROFILE_VERSION},
            "skill_version": SKILL_VERSION,
            "analyzed_at": ANALYZED_AT,
            "analyst": ANALYST,
            "tests": True,
        },
        "summary": claim("interpretation", f.desc, ev_summary),
        "callstack": frames,
        "notes": "正解データ。対象と同じ仕様から生成したので、根拠の行はすべて実在する。Subflow で呼ぶ Flow の処理は親の結果にも展開してある (共有している処理として集計に出る)",
    }


# ---------------------------------------------------------------- まとめ

FLOW_BY_ID: dict[str, Flow] = {f.full_id: f for f in FLOWS}
ARTIFACTS: dict[str, tuple[Src, Src | None, list[dict]]] = {}


def content_hash(root: Path) -> str:
    """対象ディレクトリの内容から決まる 40 桁の識別子 (git のコミットの代わり。対象はこのリポジトリの一部で独立した git 履歴を持たないため)。"""
    h = hashlib.sha1(usedforsecurity=False)
    for p in sorted(x for x in root.rglob("*") if x.is_file()):
        h.update(p.relative_to(root).as_posix().encode())
        h.update(b"\0")
        h.update(p.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def target_readme() -> str:
    by_ns: dict[str, list[Flow]] = {}
    for f in FLOWS:
        by_ns.setdefault(f.ns, []).append(f)
    rows = "\n".join(
        f"| `{ns}` | {len(fs)} | {', '.join(x.id for x in fs)} |"
        for ns, fs in by_ns.items()
    )
    return f"""# ことり書店 (kotori-books) のバッチ

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
tests/                          単体テスト (pytest。通知の部品だけ)
jobs/settings.py                接続先の既定値とバケット名・ディレクトリ
config/prod.env                 本番の設定 (秘密は含まない)。config/digests.yaml はダイジェストの対象
sql/reports/*.sql.j2            実行時に組み立てる SQL のテンプレート
bin/legacy_pricing              ソースの無いバイナリの代わり (読めない成果物の例)
```

## Flow の一覧 ({len(FLOWS)} 本)

| namespace | 本数 | flow |
|---|---|---|
{rows}

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
"""


def atlas_readme() -> str:
    return f"""# kotori-books-atlas (分析リポジトリの見本)

隣の `kotori-books/` (架空のオンライン書店のバッチ) を as-built-atlas で分析した状態の、分析リポジトリの資産です。

- `analysis/work-definition.yaml` 対象と範囲。`commit` は対象ディレクトリの内容ハッシュ (対象はこのリポジトリの一部で、独立した git 履歴を持たない)
- `analysis/entry-list.yaml` 入口 {len(FLOWS)} 件 (すべて承認済み)。`abatlas enumerate` の出力そのもの
- `analysis/results/*.yaml` 入口ごとの分析結果 = **正解**。対象と同じ仕様から生成したので、自分のエージェントの分析結果を `abatlas evaluate` で突き合わせる基準になる
- `.env` `ABATLAS_TARGET=../kotori-books`

**使うときは、この 2 つのディレクトリを as-built-atlas の checkout の外へ並べてコピーする** (`abatlas init` が git リポジトリとして初期化し、
中ハーネスと製品別の設定を書き足すため)。手順は as-built-atlas の README。
"""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--out",
        default=str(OSS_ROOT / "examples"),
        help="kotori-books と kotori-books-atlas を書くディレクトリ",
    )
    a = ap.parse_args(argv)
    out = Path(a.out).resolve()
    target = out / TARGET_NAME
    atlas = out / ATLAS_NAME
    for d in (target, atlas / "analysis" / "results"):
        if d.exists():
            shutil.rmtree(d)
    target.mkdir(parents=True)
    (atlas / "analysis" / "results").mkdir(parents=True)

    common = gen_common(target)
    for f in FLOWS:
        flow_src = gen_flow(target, f)
        job_src, truth_io = (None, []) if f.kind != "python" else gen_job(target, f)
        ARTIFACTS[f.full_id] = (flow_src, job_src, truth_io)
    write(target, "README.md", target_readme())

    commit = content_hash(target)
    # 対象の情報は 2 つに分ける。target_meta = 入口の一覧と分析結果に書く「どのコミットを分析したか」。
    # work_target = 作業定義だけに書く (表示名のような、表示のための値はこちらだけに足す。target_meta に足すと、全部の結果に写る)
    target_meta = {
        "repo": f"as-built-atlas/examples/{TARGET_NAME}",
        "clone_path": f"../{TARGET_NAME}",
        "scope": ".",
        "commit": commit,
    }
    work_target = {
        "repo": target_meta["repo"],
        "name": "ことり書店 バッチ",
        **{k: v for k, v in target_meta.items() if k != "repo"},
    }
    write(
        atlas,
        "analysis/work-definition.yaml",
        yaml.safe_dump(
            {
                "format_version": 1,
                "target": work_target,
                "profile": {"id": PROFILE_ID, "dir": f".abatlas/profiles/{PROFILE_ID}"},
                "analysis": {
                    "tests": True,
                    "entry_file_patterns": [r"flows/.+\.ya?ml"],
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
    )

    # 入口一覧: プロファイルの既定の抽出器をそのまま実行して作る (決定的)。全件を承認済みにする
    profile_path = OSS_ROOT / "profiles" / PROFILE_ID / "profile.yaml"
    profile = load_yaml(profile_path)
    ex = dict(profile["extractors"][0])
    ex.pop("hint", None)
    ex["rationale"] = (
        "Flow 定義は flows/<namespace の '.' を '/' に>/<id>.yaml に 1 ファイル 1 Flow。プロファイルの既定パラメータのまま使える"
    )
    entry_list = {
        "format_version": 1,
        "target": target_meta,
        "profile": {"id": PROFILE_ID, "version": profile["version"]},
        "extractors": [ex],
        "entries": [],
    }
    el_path = atlas / "analysis" / "entry-list.yaml"
    el_path.write_text(
        yaml.safe_dump(entry_list, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    enumerated = enumerate_entries(el_path, profile_path, write=False)
    for e in enumerated["entries"]:
        e["status"] = "approved"
        e["note"] = "見本なので全件承認"
    enumerated["enumerated_at"] = ANALYZED_AT
    el_path.write_text(
        yaml.safe_dump(enumerated, allow_unicode=True, sort_keys=False, width=200),
        encoding="utf-8",
    )
    if {e["id"] for e in enumerated["entries"]} != set(FLOW_BY_ID):
        raise ValueError("抽出器が仕様と違う入口を出した")

    for f in FLOWS:
        flow_src, job_src, truth_io = ARTIFACTS[f.full_id]
        res = result_for(f, flow_src, job_src, truth_io, common, target_meta)
        write(
            atlas,
            f"analysis/results/{f.full_id}.yaml",
            "# 正解データ (examples/generator/kotori_books.py が生成)。手で直さず、生成スクリプトを直す\n"
            + yaml.safe_dump(res, allow_unicode=True, sort_keys=False, width=160),
        )
    write(atlas, "analysis/reviews/.gitkeep", "")
    write(
        atlas,
        "analysis/dbt/models/repo/README.md",
        "# analysis/dbt/models/repo\n\nこの分析リポジトリ独自の mart を置く場所 (見本では空)。\n",
    )
    write(
        atlas,
        ".env",
        "\n".join(
            [
                "# docker compose の設定 (このリポジトリのもの。upgrade で触らない)",
                f"ABATLAS_TARGET=../{TARGET_NAME}",
                "# 配布物のイメージ。既定は ghcr.io/suwa-sh/as-built-atlas:latest (公開前はローカルで同じタグを build する)",
                "#ABATLAS_IMAGE=ghcr.io/suwa-sh/as-built-atlas:latest",
                "#ABATLAS_PORT=8765",
            ]
        )
        + "\n",
    )
    write(
        atlas,
        ".gitignore",
        "# 派生物 (build が作り直す)\nanalysis/data/\n*.duckdb\n__pycache__/\n",
    )
    write(atlas, "README.md", atlas_readme())
    n_io = sum(len(ARTIFACTS[f.full_id][2]) for f in FLOWS)
    print(
        f"generated: flows={len(FLOWS)} io(job)={n_io} commit={commit} → {target} / {atlas}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
