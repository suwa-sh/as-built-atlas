"""主要テーブルの前日分の行の有無を検査し (0 件なら ng)、検査ごとの結果を audit.data_quality に書いてチャットに通知する"""
from __future__ import annotations

import argparse
import datetime as dt

from jobs import settings
from jobs.lib import db, notify


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--date", default=dt.date.today().isoformat(), help="処理対象日 (省略時は実行日)")
    ap.add_argument("--dry-run", action="store_true", help="書き込みと外部呼び出しをせず件数だけ出す")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    day = getattr(args, "date", None) or getattr(args, "week_start", None) or getattr(args, "month", None)  # 対象日 (窓の終わり)
    checks: list[dict] = []  # 検査 1 項目 = 1 行 (audit.data_quality に書く)

    rows_1 = db.fetch_all(
        """
        SELECT t0.*
        FROM shop.orders t0
        JOIN shop.order_items t1 ON t1.order_id = t0.id
        WHERE t0.updated_at >= %s::date - interval '1 day' AND t0.updated_at < %s::date
        """,
        (day, day,),
    )
    checks.append({"checked_at": dt.datetime.now(), "check_name": "orders_with_items", "status": "ok" if rows_1 else "ng", "detail": f"{len(rows_1)} 行"})

    rows_2 = db.fetch_all(
        """
        SELECT t0.*
        FROM shop.payments t0
        WHERE t0.updated_at >= %s::date - interval '1 day' AND t0.updated_at < %s::date
        """,
        (day, day,),
    )
    checks.append({"checked_at": dt.datetime.now(), "check_name": "payments", "status": "ok" if rows_2 else "ng", "detail": f"{len(rows_2)} 行"})

    rows_3 = db.fetch_all(
        """
        SELECT t0.*
        FROM warehouse.stock t0
        JOIN shop.products t1 ON t1.stock_id = t0.id
        WHERE t0.updated_at >= %s::date - interval '1 day' AND t0.updated_at < %s::date
        """,
        (day, day,),
    )
    checks.append({"checked_at": dt.datetime.now(), "check_name": "stock_with_products", "status": "ok" if rows_3 else "ng", "detail": f"{len(rows_3)} 行"})

    rows_4 = db.fetch_all(
        """
        SELECT t0.*
        FROM mart.daily_sales t0
        WHERE t0.updated_at >= %s::date - interval '1 day' AND t0.updated_at < %s::date
        """,
        (day, day,),
    )
    checks.append({"checked_at": dt.datetime.now(), "check_name": "daily_sales", "status": "ok" if rows_4 else "ng", "detail": f"{len(rows_4)} 行"})

    db.execute_many(
        "INSERT INTO audit.data_quality (checked_at, check_name, status, detail) VALUES (%s, %s, %s, %s)",
        [tuple(r.get(c) for c in ('checked_at', 'check_name', 'status', 'detail')) for r in checks] if not args.dry_run else [],
    )
    if not args.dry_run:
        notify.post(f"daily.data_quality_checks: done")

    print(f"daily.data_quality_checks: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
