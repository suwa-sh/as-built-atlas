"""購入回数と最終購入日から顧客をセグメント (new / active / dormant / churned) に分け、mart.customer_segments を入れ替える"""
from __future__ import annotations

import argparse
import datetime as dt

from jobs import settings
from jobs.lib import db


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
        SELECT c.id AS customer_id, COUNT(o.id) AS orders_count, MAX(o.ordered_at) AS last_ordered_at,
               CASE WHEN COUNT(o.id) = 0 THEN 'new'
                    WHEN MAX(o.ordered_at) >= %s::date - interval '90 days' THEN 'active'
                    WHEN MAX(o.ordered_at) >= %s::date - interval '365 days' THEN 'dormant'
                    ELSE 'churned' END AS segment
        FROM shop.customers c
        LEFT JOIN shop.orders o ON o.customer_id = c.id AND o.status = 'settled'
        GROUP BY c.id
        """,
        (day, day,),
    )

    rows_2 = [{"segment_date": day, **r} for r in rows_1]

    if not args.dry_run:
        db.execute("DELETE FROM mart.customer_segments WHERE segment_date = %s", (day,))

    db.execute_many(
        "INSERT INTO mart.customer_segments (segment_date, customer_id, segment, orders_count, last_ordered_at) VALUES (%s, %s, %s, %s, %s)",
        [tuple(r.get(c) for c in ('segment_date', 'customer_id', 'segment', 'orders_count', 'last_ordered_at')) for r in rows_2] if not args.dry_run else [],
    )

    print(f"daily.customer.segment_customers: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
