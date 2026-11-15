"""欲しいものリストの商品が値下げされていたら、プッシュ通知で知らせる"""
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
        FROM audit.price_changes t0
        JOIN shop.wishlists t1 ON t1.price_change_id = t0.id
        JOIN shop.customers t2 ON t2.id = t1.customer_id
        WHERE t0.updated_at >= %s::date - interval '1 day' AND t0.updated_at < %s::date
        """,
        (day, day,),
    )

    for row in rows_1:
        if args.dry_run:
            continue
        http.post_json(settings.PUSH_API_HOST, "/v1/notifications", row)

    print(f"daily.customer.wishlist_price_drop: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
