"""在庫が発注点を下回った SKU の発注案を warehouse.purchase_orders に作り、仕入先担当にメールで知らせる"""
from __future__ import annotations

import argparse
import datetime as dt

from jobs import settings
from jobs.lib import db, http


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="書き込みと外部呼び出しをせず件数だけ出す")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    day = getattr(args, "date", None) or getattr(args, "week_start", None) or getattr(args, "month", None)  # 対象日 (窓の終わり)

    rows_1 = db.fetch_all(
        """
        SELECT t0.*
        FROM warehouse.stock t0
        JOIN shop.products t1 ON t1.stock_id = t0.id
        JOIN warehouse.suppliers t2 ON t2.id = t1.supplier_id
        WHERE t0.updated_at >= %s::date - interval '1 day' AND t0.updated_at < %s::date
        """,
        (day, day,),
    )

    db.execute_many(
        "INSERT INTO warehouse.purchase_orders (supplier_id, sku, quantity, status, created_at) VALUES (%s, %s, %s, %s, %s)",
        [tuple(r.get(c) for c in ('supplier_id', 'sku', 'quantity', 'status', 'created_at')) for r in rows_1] if not args.dry_run else [],
    )

    for row in rows_1:
        if args.dry_run:
            continue
        http.post_json(settings.MAIL_API_HOST, "/v3/mail/send", row)

    db.execute_many(
        "INSERT INTO audit.mail_log (sent_at, template, customer_id, provider_message_id) VALUES (%s, %s, %s, %s)",
        [tuple(r.get(c) for c in ('sent_at', 'template', 'customer_id', 'provider_message_id')) for r in rows_1] if not args.dry_run else [],
    )

    print(f"daily.inventory.reorder_alerts: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
