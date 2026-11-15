"""旧価格計算エンジン (bin/legacy_pricing、バイナリ) を実行し、出力の価格表で shop.product_prices を更新する。変更は audit.price_changes に残す"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import subprocess
from pathlib import Path

from jobs import settings
from jobs.lib import db


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="書き込みと外部呼び出しをせず件数だけ出す")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    day = getattr(args, "date", None) or getattr(args, "week_start", None) or getattr(args, "month", None)  # 対象日 (窓の終わり)
    # 旧価格計算エンジン (ソースの無いバイナリ) を先に動かして価格表を書かせ、その出力を下で読む。dry-run では動かさない (前回の出力を読む)
    if not args.dry_run:
        subprocess.run(["bin/legacy_pricing", "--out", str(Path(settings.TMP_DIR) / "pricing.out")], check=True)

    rows_1 = [dict(zip(("sku", "new_price"), l.split("\t"))) for l in (Path(settings.TMP_DIR) / "pricing.out").read_text(encoding="utf-8").splitlines()]

    rows_2 = db.fetch_all(
        """
        SELECT t0.*
        FROM shop.product_prices t0
        WHERE t0.updated_at >= %s::date - interval '1 day' AND t0.updated_at < %s::date
        """,
        (day, day,),
    )

    if not args.dry_run:
        db.execute_many(
            "UPDATE shop.product_prices SET price = %s, updated_at = now() WHERE id = %s",
            [(row["price"], row["id"]) for row in rows_2],
        )

    db.execute_many(
        "INSERT INTO audit.price_changes (changed_at, product_id, old_price, new_price, source) VALUES (%s, %s, %s, %s, %s)",
        [tuple(r.get(c) for c in ('changed_at', 'product_id', 'old_price', 'new_price', 'source')) for r in rows_2] if not args.dry_run else [],
    )

    print(f"weekly.legacy_price_sync: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
