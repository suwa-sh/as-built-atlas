"""キュー stock.changed を 5 分ごとに読み、在庫数と Redis の在庫キャッシュへ反映する"""
from __future__ import annotations

import argparse
import datetime as dt

from jobs import settings
from jobs.lib import db, cache, mq


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="書き込みと外部呼び出しをせず件数だけ出す")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    day = getattr(args, "date", None) or getattr(args, "week_start", None) or getattr(args, "month", None)  # 対象日 (窓の終わり)

    rows_1 = list(mq.consume("stock.changed")) if not args.dry_run else mq.peek("stock.changed")  # dry-run では ACK しない

    if not args.dry_run:
        db.execute_many(
            "UPDATE warehouse.stock SET on_hand = on_hand + %s, updated_at = now() WHERE id = %s",
            [(row["delta"], row["id"]) for row in rows_1],
        )

    db.execute_many(
        "INSERT INTO warehouse.stock_movements (sku, delta, reason, moved_at) VALUES (%s, %s, %s, %s)",
        [tuple(r.get(c) for c in ('sku', 'delta', 'reason', 'moved_at')) for r in rows_1] if not args.dry_run else [],
    )

    if not args.dry_run:
        for row in rows_1:
            cache.set(f"stock:{row['sku']}", row)

    print(f"hourly.consume_stock_events: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
