"""仕入先が置いた入荷 CSV (var/inbox/suppliers/) を取り込み、入荷と入庫を記録する。処理したファイルは done/ に移す"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
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

    files_1 = sorted((Path(settings.INBOX_DIR) / "suppliers").glob("*.csv"))

    rows_2 = []
    for p in files_1:
        with p.open(encoding="utf-8") as fh:
            rows_2.extend({**r, "source_file": p.name} for r in csv.DictReader(fh))

    rows_3 = db.fetch_all(
        """
        SELECT id, code FROM warehouse.suppliers
        """
    )

    codes = {s['code']: s['id'] for s in rows_3}
    rows_4 = [{**r, "supplier_id": codes[r["source_file"].split("_")[0]]} for r in rows_2]  # ファイル名 <code>_<日付>.csv

    db.execute_many(
        "INSERT INTO warehouse.inbound_receipts (supplier_id, sku, quantity, received_at, source_file) VALUES (%s, %s, %s, %s, %s)",
        [tuple(r.get(c) for c in ('supplier_id', 'sku', 'quantity', 'received_at', 'source_file')) for r in rows_4] if not args.dry_run else [],
    )

    rows_5 = [{"sku": r["sku"], "delta": int(r["quantity"]), "reason": "inbound", "moved_at": r["received_at"]} for r in rows_4]

    db.execute_many(
        "INSERT INTO warehouse.stock_movements (sku, delta, reason, moved_at) VALUES (%s, %s, %s, %s)",
        [tuple(r.get(c) for c in ('sku', 'delta', 'reason', 'moved_at')) for r in rows_5] if not args.dry_run else [],
    )

    if not args.dry_run:
        for p in files_1:
            p.rename(Path(settings.INBOX_DIR) / "suppliers/done" / p.name)

    print(f"daily.inventory.import_supplier_feeds: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
