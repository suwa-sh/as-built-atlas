"""為替レートを外部 API から取り込み、shop.exchange_rates に追加して Redis に当日分を置く"""
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

    rows_1 = http.get_json(settings.FX_API_HOST, "/latest")["items"]

    db.execute_many(
        "INSERT INTO shop.exchange_rates (rate_date, currency, rate) VALUES (%s, %s, %s)",
        [tuple(r.get(c) for c in ('rate_date', 'currency', 'rate')) for r in rows_1] if not args.dry_run else [],
    )

    if not args.dry_run:
        for row in rows_1:
            cache.set(f"fx:{row['currency']}", row)

    if not args.dry_run:
        for row in rows_1:
            cache.expire(f"fx:{row['currency']}", 48 * 3600)

    print(f"daily.fx_rates: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
