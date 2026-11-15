"""audit.report_definitions に登録された SQL (利用部門が管理画面から登録する) を月初に実行し、結果を定義ごとの CSV にして S3 に置く"""
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
    ap.add_argument("--month", help="対象月 (YYYY-MM)")
    ap.add_argument("--dry-run", action="store_true", help="書き込みと外部呼び出しをせず件数だけ出す")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    day = getattr(args, "date", None) or getattr(args, "week_start", None) or getattr(args, "month", None)  # 対象日 (窓の終わり)

    rows_1 = db.fetch_all(
        """
        SELECT t0.*
        FROM audit.report_definitions t0
        WHERE t0.enabled = true
        """
    )

    rows_2 = []
    for defn in rows_1:
        rows_2.append({"report_name": defn["name"], "rows": db.fetch_all(defn["sql"])})  # 定義に保存された SQL をそのまま実行する

    if not args.dry_run:
        for row in rows_2:
            out = Path(settings.EXPORT_DIR) / "custom" / f"{row['report_name']}_{args.month}.csv"
            out.parent.mkdir(parents=True, exist_ok=True)
            with out.open("w", newline="", encoding="utf-8") as fh:
                csv.writer(fh).writerows(r.values() for r in (row["rows"] if "rows" in row else [row]))
            storage.put_object(settings.REPORTS_BUCKET, "monthly/custom/" + out.name, out.read_bytes())

    print(f"monthly.custom_reports: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
