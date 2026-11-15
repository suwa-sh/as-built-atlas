"""キュー mail.requests を 10 分ごとに読み、メール API で送って audit.mail_log に記録する"""
from __future__ import annotations

import argparse
import datetime as dt

from jobs import settings
from jobs.lib import db, http, mq


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="書き込みと外部呼び出しをせず件数だけ出す")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    day = getattr(args, "date", None) or getattr(args, "week_start", None) or getattr(args, "month", None)  # 対象日 (窓の終わり)

    rows_1 = list(mq.consume("mail.requests")) if not args.dry_run else mq.peek("mail.requests")  # dry-run では ACK しない

    for row in rows_1:
        if args.dry_run:
            continue
        http.post_json(settings.MAIL_API_HOST, "/v3/mail/send", row)

    db.execute_many(
        "INSERT INTO audit.mail_log (sent_at, template, customer_id, provider_message_id) VALUES (%s, %s, %s, %s)",
        [tuple(r.get(c) for c in ('sent_at', 'template', 'customer_id', 'provider_message_id')) for r in rows_1] if not args.dry_run else [],
    )

    print(f"hourly.mail_queue_worker: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
