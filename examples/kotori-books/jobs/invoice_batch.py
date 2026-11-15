"""法人顧客の前月分の請求書 (PDF) を顧客ごとのディレクトリに作り、メールで送る"""
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
    ap.add_argument("--month", help="対象月 (YYYY-MM)")
    ap.add_argument("--dry-run", action="store_true", help="書き込みと外部呼び出しをせず件数だけ出す")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    day = getattr(args, "date", None) or getattr(args, "week_start", None) or getattr(args, "month", None)  # 対象日 (窓の終わり)

    rows_1 = db.fetch_all(
        """
        SELECT t0.*
        FROM shop.customers t0
        JOIN shop.orders t1 ON t1.customer_id = t0.id
        JOIN shop.addresses t2 ON t2.id = t1.address_id
        WHERE t0.updated_at >= %s::date - interval '1 day' AND t0.updated_at < %s::date
        """,
        (day, day,),
    )

    if not args.dry_run:
        for row in rows_1:
            out = Path(settings.EXPORT_DIR) / "invoices" / f"{row['customer_code']}/invoice_{args.month}.pdf"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(render_report(row))
            http.post_json(settings.MAIL_API_HOST, "/v3/mail/send", {**row, "attachment": {"name": out.name, "content_base64": base64.b64encode(out.read_bytes()).decode()}})

    db.execute_many(
        "INSERT INTO audit.mail_log (sent_at, template, customer_id, provider_message_id) VALUES (%s, %s, %s, %s)",
        [tuple(r.get(c) for c in ('sent_at', 'template', 'customer_id', 'provider_message_id')) for r in rows_1] if not args.dry_run else [],
    )

    print(f"monthly.invoice_batch: ok")
    return 0


def render_report(rows) -> bytes:
    """行 (または 1 行) を人が読める帳票にする (サンプルなので文字列化だけ)。"""
    return "\n".join(str(r) for r in (rows if isinstance(rows, list) else [rows])).encode()


if __name__ == "__main__":
    raise SystemExit(main())
