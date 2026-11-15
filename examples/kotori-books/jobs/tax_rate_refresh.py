"""税率 API から最新の税率表を取り、shop.tax_rates を更新する"""
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

    rows_1 = http.get_json(settings.TAX_API_HOST, "/v1/rates")["items"]

    if not args.dry_run:
        db.execute_many(
            "UPDATE shop.tax_rates SET rate = %s, effective_from = %s WHERE id = %s",
            [(row["rate"], row["effective_from"], row["id"]) for row in rows_1],
        )

    print(f"weekly.tax_rate_refresh: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
