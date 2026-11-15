"""前日の未確定注文を決済 API で売上確定 (capture) し、shop.orders と shop.payments を更新する。確定した注文はキュー orders.settled に流す"""
from __future__ import annotations

import argparse
import datetime as dt

from jobs import settings
from jobs.lib import db, http, mq


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
        SELECT t0.*
        FROM shop.orders t0
        JOIN shop.payments t1 ON t1.order_id = t0.id
        WHERE t0.updated_at >= %s::date - interval '1 day' AND t0.updated_at < %s::date
        """,
        (day, day,),
    )

    for row in rows_1:
        if args.dry_run:
            continue
        http.post_json(settings.PAYMENT_API_HOST, "/v1/captures", row)

    if not args.dry_run:
        db.execute_many(
            "UPDATE shop.orders SET status = 'settled', settled_at = now() WHERE id = %s",
            [(row["id"]) for row in rows_1],
        )

    db.execute_many(
        "INSERT INTO shop.payments (order_id, kind, amount, provider_ref, created_at) VALUES (%s, %s, %s, %s, %s)",
        [tuple(r.get(c) for c in ('order_id', 'kind', 'amount', 'provider_ref', 'created_at')) for r in rows_1] if not args.dry_run else [],
    )

    if not args.dry_run:
        mq.publish("orders.settled", {"ids": [r["id"] for r in rows_1]})

    print(f"daily.sales.settle_orders: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
