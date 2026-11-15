"""Redis のカートを毎時なめて、放置カートの件数と金額を audit.cart_snapshots に書く"""
from __future__ import annotations

import argparse
import datetime as dt

from jobs import settings
from jobs.lib import db, cache


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="書き込みと外部呼び出しをせず件数だけ出す")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    day = getattr(args, "date", None) or getattr(args, "week_start", None) or getattr(args, "month", None)  # 対象日 (窓の終わり)

    rows_1 = [cache.get(key) for key in cache.scan("cart:*")]

    db.execute_many(
        "INSERT INTO audit.cart_snapshots (taken_at, carts_total, carts_abandoned, amount_abandoned) VALUES (%s, %s, %s, %s)",
        [tuple(r.get(c) for c in ('taken_at', 'carts_total', 'carts_abandoned', 'amount_abandoned')) for r in rows_1] if not args.dry_run else [],
    )

    print(f"hourly.abandoned_carts_snapshot: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
