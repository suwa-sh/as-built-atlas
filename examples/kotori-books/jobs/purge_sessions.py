"""90 日以上使われていないセッションを Redis から消し、同じ期間放置されたカートを shop.carts から削除する"""
from __future__ import annotations

import argparse
import datetime as dt

from jobs import settings
from jobs.lib import db, cache


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="書き込みと外部呼び出しをせず件数だけ出す")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    day = getattr(args, "date", None) or getattr(args, "week_start", None) or getattr(args, "month", None)  # 対象日 (窓の終わり)

    rows_1 = [cache.get(key) for key in cache.scan("session:*")]

    if not args.dry_run:
        cache.delete(*[key for key in cache.scan("session:*") if is_stale(cache.get(key))])

    if not args.dry_run:
        db.execute("DELETE FROM shop.carts WHERE updated_at < now() - interval '90 days'", ())

    print(f"monthly.purge_sessions: ok")
    return 0


def is_stale(value) -> bool:
    return not value or value.get("last_seen", "") < (dt.date.today() - dt.timedelta(days=90)).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
