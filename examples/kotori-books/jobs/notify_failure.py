"""他の Flow の errors から呼ばれ、失敗した Flow の名前と実行 ID をチャットに通知する"""
from __future__ import annotations

import argparse
import datetime as dt

from jobs import settings
from jobs.lib import notify


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--flow-id", help="失敗した Flow")
    ap.add_argument("--execution-id", help="失敗した実行の ID")
    ap.add_argument("--dry-run", action="store_true", help="書き込みと外部呼び出しをせず件数だけ出す")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    if not args.dry_run:
        notify.post(f"[kotori] {args.flow_id} が失敗しました (execution {args.execution_id})")

    print(f"lib.notify_failure: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
