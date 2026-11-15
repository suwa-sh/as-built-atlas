"""2 年より古い注文を JSON Lines にして S3 のアーカイブに置き、DB から削除する"""
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
    ap.add_argument("--date", default=dt.date.today().isoformat(), help="処理対象日 (省略時は実行日)")
    ap.add_argument("--dry-run", action="store_true", help="書き込みと外部呼び出しをせず件数だけ出す")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    day = getattr(args, "date", None) or getattr(args, "week_start", None) or getattr(args, "month", None)  # 対象日 (窓の終わり)

    rows_1 = db.fetch_all(
        """
        SELECT o.id, o.customer_id, o.ordered_at, o.status,
               json_agg(json_build_object('product_id', oi.product_id, 'quantity', oi.quantity, 'unit_price', oi.unit_price)) AS items
        FROM shop.orders o
        JOIN shop.order_items oi ON oi.order_id = o.id
        WHERE o.ordered_at < %s::date - interval '2 years'
        GROUP BY o.id
        """,
        (day,),
    )

    out = Path(settings.EXPORT_DIR) / "archive" / f"orders_{args.date[:7].replace('-', '')}.jsonl"
    if not args.dry_run:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("".join(json.dumps(r, ensure_ascii=False, default=str) + "\n" for r in rows_1), encoding="utf-8")

    if not args.dry_run:
        storage.put_object(settings.EXPORTS_BUCKET, "archive/orders/" + out.name, out.read_bytes())

    if not args.dry_run:
        db.execute("DELETE FROM shop.order_items WHERE order_id = ANY(%s)", ([row["id"] for row in rows_1],))

    if not args.dry_run:
        db.execute("DELETE FROM shop.orders WHERE id = ANY(%s)", ([row["id"] for row in rows_1],))

    print(f"weekly.archive_old_orders: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
