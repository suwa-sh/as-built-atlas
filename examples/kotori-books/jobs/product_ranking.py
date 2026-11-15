"""直近 7 日の販売数から商品ランキングを作り、mart.product_ranking を入れ替えて Redis に上位 100 件を置く"""
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
        SELECT oi.product_id, p.category_id, SUM(oi.quantity) AS units_7d,
               RANK() OVER (PARTITION BY p.category_id ORDER BY SUM(oi.quantity) DESC) AS rank
        FROM shop.order_items oi
        JOIN shop.orders o ON o.id = oi.order_id
        JOIN shop.products p ON p.id = oi.product_id
        WHERE o.status = 'settled' AND o.ordered_at >= %s::date - interval '7 days' AND o.ordered_at < %s::date
        GROUP BY oi.product_id, p.category_id
        """,
        (day, day,),
    )

    rows_2 = [{"ranking_date": day, **r} for r in rows_1 if r["rank"] <= 100]  # カテゴリごとに上位 100 件

    if not args.dry_run:
        db.execute("DELETE FROM mart.product_ranking WHERE ranking_date = %s", (day,))

    db.execute_many(
        "INSERT INTO mart.product_ranking (ranking_date, rank, product_id, category_id, units_7d) VALUES (%s, %s, %s, %s, %s)",
        [tuple(r.get(c) for c in ('ranking_date', 'rank', 'product_id', 'category_id', 'units_7d')) for r in rows_2] if not args.dry_run else [],
    )

    if not args.dry_run:
        for row in rows_2:
            cache.set(f"ranking:daily:{row['category_id']}", row)

    if not args.dry_run:
        for row in rows_2:
            cache.expire(f"ranking:daily:{row['category_id']}", 36 * 3600)

    print(f"daily.sales.product_ranking: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
