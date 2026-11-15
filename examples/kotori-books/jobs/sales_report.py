"""確定済み注文の明細を商品別・日別に集計して mart.daily_sales に入れ替え、CSV を S3 に置く"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
from pathlib import Path

from jobs import settings
from jobs.lib import db, storage, notify


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--date", default=dt.date.today().isoformat(), help="処理対象日 (省略時は実行日)")
    ap.add_argument("--dry-run", action="store_true", help="書き込みと外部呼び出しをせず件数だけ出す")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    day = getattr(args, "date", None) or getattr(args, "week_start", None) or getattr(args, "month", None)  # 対象日 (窓の終わり)

    rows_1 = db.fetch_all(
        """
        SELECT o.ordered_at::date AS sales_date, oi.product_id, p.category_id,
               SUM(oi.quantity) AS quantity, SUM(oi.quantity * oi.unit_price) AS amount
        FROM shop.orders o
        JOIN shop.order_items oi ON oi.order_id = o.id
        JOIN shop.products p ON p.id = oi.product_id
        WHERE o.status = 'settled' AND o.ordered_at >= %s::date - interval '1 day' AND o.ordered_at < %s::date
        GROUP BY 1, 2, 3
        """,
        (day, day,),
    )

    if not args.dry_run:
        db.execute("DELETE FROM mart.daily_sales WHERE sales_date = %s", (day,))

    db.execute_many(
        "INSERT INTO mart.daily_sales (sales_date, product_id, category_id, quantity, amount) VALUES (%s, %s, %s, %s, %s)",
        [tuple(r.get(c) for c in ('sales_date', 'product_id', 'category_id', 'quantity', 'amount')) for r in rows_1] if not args.dry_run else [],
    )

    out = Path(settings.EXPORT_DIR) / "sales" / f"daily_sales_{args.date}.csv"
    if not args.dry_run:
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", newline="", encoding="utf-8") as fh:
            csv.writer(fh).writerows(r.values() for r in rows_1)

    if not args.dry_run:
        storage.put_object(settings.REPORTS_BUCKET, "daily/sales/" + out.name, out.read_bytes())
    if not args.dry_run:
        notify.post(f"daily.sales.sales_report: done")

    print(f"daily.sales.sales_report: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
