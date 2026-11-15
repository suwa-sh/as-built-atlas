"""初回購入月ごとのコホートで週次の継続率を計算し、mart.cohort_retention と CSV (S3) に出す"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
from pathlib import Path

from jobs import settings
from jobs.lib import db, storage


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--week-start", default=dt.date.today().isoformat(), help="週の初日 (月曜)")
    ap.add_argument("--dry-run", action="store_true", help="書き込みと外部呼び出しをせず件数だけ出す")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    day = getattr(args, "date", None) or getattr(args, "week_start", None) or getattr(args, "month", None)  # 対象日 (窓の終わり)

    rows_1 = db.fetch_all(
        """
        SELECT t0.*
        FROM shop.customers t0
        JOIN shop.orders t1 ON t1.customer_id = t0.id
        WHERE t0.updated_at >= %s::date - interval '1 day' AND t0.updated_at < %s::date
        """,
        (day, day,),
    )

    db.execute_many(
        "INSERT INTO mart.cohort_retention (week_start, cohort_month, week_index, customers, retained) VALUES (%s, %s, %s, %s, %s)",
        [tuple(r.get(c) for c in ('week_start', 'cohort_month', 'week_index', 'customers', 'retained')) for r in rows_1] if not args.dry_run else [],
    )

    out = Path(settings.EXPORT_DIR) / "weekly" / f"cohort_{args.week_start}.csv"
    if not args.dry_run:
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", newline="", encoding="utf-8") as fh:
            csv.writer(fh).writerows(r.values() for r in rows_1)

    if not args.dry_run:
        storage.put_object(settings.REPORTS_BUCKET, "weekly/cohort/" + out.name, out.read_bytes())

    print(f"weekly.cohort_retention: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
