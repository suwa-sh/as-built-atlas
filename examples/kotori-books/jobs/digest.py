"""config/digests.yaml に列挙された日次レポートの CSV を集めて 1 本のダイジェストにし、S3 に置いてチャットに要約を流す"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
from pathlib import Path

import yaml

from jobs import settings
from jobs.lib import storage, notify


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--date", default=dt.date.today().isoformat(), help="処理対象日 (省略時は実行日)")
    ap.add_argument("--dry-run", action="store_true", help="書き込みと外部呼び出しをせず件数だけ出す")
    return ap.parse_args()


def main() -> int:
    args = parse_args()

    rows_1 = yaml.safe_load((Path("config") / "digests.yaml").read_text(encoding="utf-8"))["digests"]

    rows_2 = []
    for row in rows_1:  # config/digests.yaml の各エントリ (dir, title)
        for p in sorted((Path(settings.EXPORT_DIR) / row["dir"]).glob(f"*_{args.date}.csv")):
            rows_2.append({"title": row["title"], "file": p.name, "body": p.read_text(encoding="utf-8")})

    out = Path(settings.EXPORT_DIR) / "digest" / f"digest_{args.date}.md"
    if not args.dry_run:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(render_report(rows_2))

    if not args.dry_run:
        storage.put_object(settings.REPORTS_BUCKET, "daily/digest/" + out.name, out.read_bytes())
    if not args.dry_run:
        notify.post(f"daily.digest: done")

    print(f"daily.digest: ok")
    return 0


def render_report(rows) -> bytes:
    """行 (または 1 行) を人が読める帳票にする (サンプルなので文字列化だけ)。"""
    return "\n".join(str(r) for r in (rows if isinstance(rows, list) else [rows])).encode()


if __name__ == "__main__":
    raise SystemExit(main())
