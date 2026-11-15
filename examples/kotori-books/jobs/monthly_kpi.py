"""月次 KPI (売上・顧客数・継続率) を sql/reports/ のテンプレートから組み立てた SQL で集計し、mart.monthly_kpi と Excel (S3) に出す"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
from pathlib import Path

import jinja2

from jobs import settings
from jobs.lib import db, storage


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--month", help="対象月 (YYYY-MM)")
    ap.add_argument("--dry-run", action="store_true", help="書き込みと外部呼び出しをせず件数だけ出す")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    day = getattr(args, "date", None) or getattr(args, "week_start", None) or getattr(args, "month", None)  # 対象日 (窓の終わり)

    template = Path("sql/reports/monthly_kpi.sql.j2").read_text(encoding="utf-8")
    sql = jinja2.Template(template).render(month=args.month)
    rows_1 = db.fetch_all(sql)

    db.execute_many(
        "INSERT INTO mart.monthly_kpi (month, kpi_name, kpi_value) VALUES (%s, %s, %s)",
        [tuple(r.get(c) for c in ('month', 'kpi_name', 'kpi_value')) for r in rows_1] if not args.dry_run else [],
    )

    out = Path(settings.EXPORT_DIR) / "monthly" / f"kpi_{args.month}.xlsx"
    if not args.dry_run:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(render_report(rows_1))

    if not args.dry_run:
        storage.put_object(settings.REPORTS_BUCKET, "monthly/kpi/" + out.name, out.read_bytes())

    print(f"monthly.monthly_kpi: ok")
    return 0


def render_report(rows) -> bytes:
    """行 (または 1 行) を人が読める帳票にする (サンプルなので文字列化だけ)。"""
    return "\n".join(str(r) for r in (rows if isinstance(rows, list) else [rows])).encode()


if __name__ == "__main__":
    raise SystemExit(main())
