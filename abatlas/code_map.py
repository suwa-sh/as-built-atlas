"""固定コミットの通常ファイルを入口の抽出器とは別に列挙し、定義ファイルの取りこぼしを調べる。"""

from pathlib import PurePosixPath
import re


def code_map(history, patterns):
    files = history.files()
    if not files or "." in files:
        raise SystemExit(
            "code-map: target.scope に通常ファイルを含むディレクトリを指定してください"
        )
    expected = set()
    for pattern in patterns:
        match = re.compile(pattern).fullmatch
        paths = {path for path in files if match(path)}
        if not paths:
            raise SystemExit(
                f"analysis.entry_file_patterns: {pattern!r} に一致するファイルがありません。"
                "対象コミット・scope と式を確認してください"
            )
        expected.update(paths)
    return {
        "target_commit": history.tip,
        "scope": history.scope.as_posix(),
        "files": sorted(files),
        "entry_file_patterns": patterns,
        "expected_entry_files": sorted(expected),
    }


def reconcile_entries(report, entries):
    by_file = {}
    for entry in entries:
        path = PurePosixPath(entry["source"]["file"]).as_posix()
        by_file.setdefault(path, []).append(entry["id"])
    return {
        "entries_by_file": by_file,
        "missing_entry_files": sorted(
            set(report["expected_entry_files"]) - by_file.keys()
        ),
    }


def format_code_map(report):
    expected = set(report["expected_entry_files"])
    lines = [
        f"{report['target_commit']}  scope={report['scope']}  ファイル {len(report['files'])} 件",
        f"入口を照合する定義ファイル {len(expected)} 件"
        if expected
        else "入口を照合する規則は未設定",
    ]
    missing = set(report.get("missing_entry_files", []))
    for path in report["files"]:
        kind = "入口定義" if path in expected else "ファイル"
        ids = report.get("entries_by_file", {}).get(path, [])
        lines.append("\t".join(["入口未列挙" if path in missing else kind, path, *ids]))
    if "missing_entry_files" in report:
        lines.append(f"入口未列挙 {len(missing)} 件")
    return "\n".join(lines)
