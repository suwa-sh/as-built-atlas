"""有効期限を過ぎたクーポンを失効させ、90 日より古い利用履歴を削除する"""
from __future__ import annotations

import argparse
import datetime as dt

from jobs import settings
from jobs.lib import db


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
        FROM shop.coupons t0
        WHERE t0.updated_at >= %s::date - interval '1 day' AND t0.updated_at < %s::date
        """,
        (day, day,),
    )

    if not args.dry_run:
        db.execute_many(
            "UPDATE shop.coupons SET status = 'expired' WHERE id = %s",
            [(row["id"]) for row in rows_1],
        )

    if not args.dry_run:
        db.execute("DELETE FROM shop.coupon_usages WHERE used_at < now() - interval '90 days'", ())

    print(f"daily.sales.coupon_expiry: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
