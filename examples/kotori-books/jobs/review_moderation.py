"""未審査のレビューを外部の判定 API にかけ、結果で公開 / 保留を決める"""
from __future__ import annotations

import argparse
import datetime as dt
import os

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
        FROM shop.reviews t0
        WHERE t0.updated_at >= %s::date - interval '1 day' AND t0.updated_at < %s::date
        """,
        (day, day,),
    )

    for row in rows_1:
        if args.dry_run:
            continue
        http.post_json(os.environ["KOTORI_MODERATION_API_HOST"], "/v1/classify", row)

    if not args.dry_run:
        db.execute_many(
            "UPDATE shop.reviews SET status = %s, moderated_at = now() WHERE id = %s",
            [(row["status"], row["id"]) for row in rows_1],
        )

    print(f"daily.customer.review_moderation: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
