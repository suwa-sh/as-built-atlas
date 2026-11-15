"""24 時間以上放置されたカートの持ち主にリマインドメールを送る。1 顧客 1 日 1 通に制限する"""
from __future__ import annotations

import argparse
import datetime as dt

from jobs import settings
from jobs.lib import db, cache, http


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="書き込みと外部呼び出しをせず件数だけ出す")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    day = getattr(args, "date", None) or getattr(args, "week_start", None) or getattr(args, "month", None)  # 対象日 (窓の終わり)

    rows_1 = [cache.get(key) for key in cache.scan("cart:*")]

    rows_2 = [c for c in rows_1 if c and c["updated_at"] < (dt.datetime.now() - dt.timedelta(hours=24)).isoformat()]  # 24 時間以上放置

    rows_3 = db.fetch_all(
        """
        SELECT id AS customer_id, email FROM shop.customers
        WHERE id = ANY(%s) AND mail_opt_in
        """,
        ([c["customer_id"] for c in rows_2],),
    )

    rows_4 = [row for row in rows_3 if not cache.get(f"ratelimit:mail:{row['customer_id']}")]  # 既に印のある行を除く

    for row in rows_4:
        if args.dry_run:
            continue
        http.post_json(settings.MAIL_API_HOST, "/v3/mail/send", row)

    if not args.dry_run:
        for row in rows_4:
            cache.set(f"ratelimit:mail:{row['customer_id']}", row)

    if not args.dry_run:
        for row in rows_4:
            cache.expire(f"ratelimit:mail:{row['customer_id']}", 24 * 3600)

    db.execute_many(
        "INSERT INTO audit.mail_log (sent_at, template, customer_id, provider_message_id) VALUES (%s, %s, %s, %s)",
        [tuple(r.get(c) for c in ('sent_at', 'template', 'customer_id', 'provider_message_id')) for r in rows_4] if not args.dry_run else [],
    )

    print(f"daily.customer.send_cart_reminders: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
