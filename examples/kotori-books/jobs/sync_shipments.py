"""配送中の出荷の追跡情報を配送業者 API から取り、shop.shipments の状態を更新する"""
from __future__ import annotations

import argparse
import datetime as dt

from jobs import settings
from jobs.lib import db, http


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
        FROM shop.shipments t0
        WHERE t0.updated_at >= %s::date - interval '1 day' AND t0.updated_at < %s::date
        """,
        (day, day,),
    )

    for row in rows_1:
        row.update(http.get_json(settings.CARRIER_API_HOST, f"/v2/tracking/{row['tracking_no']}"))

    if not args.dry_run:
        db.execute_many(
            "UPDATE shop.shipments SET status = %s, last_event_at = %s WHERE id = %s",
            [(row["status"], row["last_event_at"], row["id"]) for row in rows_1],
        )

    print(f"hourly.sync_shipments: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
