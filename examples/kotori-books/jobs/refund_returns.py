"""承認済みの返品について決済 API に返金を要求し、shop.returns と shop.payments に結果を書く。返金完了はメール API で顧客に知らせる"""
from __future__ import annotations

import argparse
import datetime as dt

from jobs import settings
from jobs.lib import db, http


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
        FROM shop.returns t0
        JOIN shop.payments t1 ON t1.return_id = t0.id
        JOIN shop.customers t2 ON t2.id = t1.customer_id
        WHERE t0.updated_at >= %s::date - interval '1 day' AND t0.updated_at < %s::date
        """,
        (day, day,),
    )

    for row in rows_1:
        if args.dry_run:
            continue
        http.post_json(settings.PAYMENT_API_HOST, "/v1/refunds", row)

    if not args.dry_run:
        db.execute_many(
            "UPDATE shop.returns SET status = 'refunded', refunded_at = now() WHERE id = %s",
            [(row["id"]) for row in rows_1],
        )

    db.execute_many(
        "INSERT INTO shop.payments (order_id, kind, amount, provider_ref, created_at) VALUES (%s, %s, %s, %s, %s)",
        [tuple(r.get(c) for c in ('order_id', 'kind', 'amount', 'provider_ref', 'created_at')) for r in rows_1] if not args.dry_run else [],
    )

    for row in rows_1:
        if args.dry_run:
            continue
        http.post_json(settings.MAIL_API_HOST, "/v3/mail/send", row)

    db.execute_many(
        "INSERT INTO audit.mail_log (sent_at, template, customer_id, provider_message_id) VALUES (%s, %s, %s, %s)",
        [tuple(r.get(c) for c in ('sent_at', 'template', 'customer_id', 'provider_message_id')) for r in rows_1] if not args.dry_run else [],
    )

    print(f"daily.sales.refund_returns: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
