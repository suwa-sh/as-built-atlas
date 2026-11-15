"""仕入先ごとの週次明細 (入荷と発注) を CSV にまとめ、メールで送る"""
from __future__ import annotations

import argparse
import base64
import csv
import datetime as dt
import json
from pathlib import Path

from jobs import settings
from jobs.lib import db, http


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--week-start", default=dt.date.today().isoformat(), help="週の初日 (月曜)")
    ap.add_argument("--dry-run", action="store_true", help="書き込みと外部呼び出しをせず件数だけ出す")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    day = getattr(args, "date", None) or getattr(args, "week_start", None) or getattr(args, "month", None)  # 対象日 (窓の終わり)

    rows_1 = db.fetch_all(
        """
        SELECT t0.*
        FROM warehouse.suppliers t0
        JOIN warehouse.inbound_receipts t1 ON t1.supplier_id = t0.id
        JOIN warehouse.purchase_orders t2 ON t2.id = t1.purchase_order_id
        WHERE t0.updated_at >= %s::date - interval '1 day' AND t0.updated_at < %s::date
        """,
        (day, day,),
    )

    if not args.dry_run:
        for row in rows_1:
            out = Path(settings.EXPORT_DIR) / "suppliers" / f"{row['supplier_code']}_{args.week_start}.csv"
            out.parent.mkdir(parents=True, exist_ok=True)
            with out.open("w", newline="", encoding="utf-8") as fh:
                csv.writer(fh).writerows(r.values() for r in (row["rows"] if "rows" in row else [row]))
            http.post_json(settings.MAIL_API_HOST, "/v3/mail/send", {**row, "attachment": {"name": out.name, "content_base64": base64.b64encode(out.read_bytes()).decode()}})

    db.execute_many(
        "INSERT INTO audit.mail_log (sent_at, template, customer_id, provider_message_id) VALUES (%s, %s, %s, %s)",
        [tuple(r.get(c) for c in ('sent_at', 'template', 'customer_id', 'provider_message_id')) for r in rows_1] if not args.dry_run else [],
    )

    print(f"weekly.supplier_statements: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
