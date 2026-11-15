"""前日の入出庫 (stock_movements) を在庫数に反映し、日次の在庫スナップショットを mart に書く。Redis の在庫キャッシュも更新する"""
from __future__ import annotations

import argparse
import datetime as dt

from jobs import settings
from jobs.lib import db, cache


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
        SELECT s.id, s.sku, s.reserved, SUM(m.delta) AS delta, s.on_hand + SUM(m.delta) AS on_hand
        FROM warehouse.stock s
        JOIN warehouse.stock_movements m ON m.sku = s.sku
        WHERE m.moved_at >= %s::date - interval '1 day' AND m.moved_at < %s::date
        GROUP BY s.id, s.sku, s.reserved, s.on_hand
        """,
        (day, day,),
    )

    rows_2 = [{"snapshot_date": day, **r} for r in rows_1]

    if not args.dry_run:
        db.execute_many(
            "UPDATE warehouse.stock SET on_hand = on_hand + %s, updated_at = now() WHERE id = %s",
            [(row["delta"], row["id"]) for row in rows_2],
        )

    db.execute_many(
        "INSERT INTO mart.inventory_snapshot (snapshot_date, sku, on_hand, reserved) VALUES (%s, %s, %s, %s)",
        [tuple(r.get(c) for c in ('snapshot_date', 'sku', 'on_hand', 'reserved')) for r in rows_2] if not args.dry_run else [],
    )

    if not args.dry_run:
        for row in rows_2:
            cache.set(f"stock:{row['sku']}", row)

    print(f"daily.inventory.reconcile_stock: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
