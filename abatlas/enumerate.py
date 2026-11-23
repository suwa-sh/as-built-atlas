"""列挙ツール: 入口一覧 (entry-list) の extractors を実行し、候補を entries に書き戻す。

- 各抽出器を子プロセスで実行し、標準出力の JSON Lines を schema で検証する
- 既存の entries の status (approved / rejected) と note は、同じ id なら引き継ぐ。
  ただし、人が判断した後に、同じ id の指す先 (階層パス、層、定義のファイル) が変わったら、candidate に戻す
- 同じ id が、2 つの抽出器から違う入口 (指す先が違う) として出たら止まる (指す先が同じなら、先に書いた抽出器の候補を残す)
- 列挙は決定的: 同じ対象コミット・同じ設定なら同じ entries になる (順序は id 順)
- プロファイルが within (入口が別の入口の中で動く関係) を宣言していれば、entries[].within を埋める
"""

from __future__ import annotations

import json
import shlex
import subprocess  # nosec B404 - executes subprocesses with argument lists
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .schemas import load_yaml, schema_errors
from .validate import _resolve_scope, rejected_wrappers, validate_entry_list, within_of

CORE_EXTRACTORS = {
    "structured-query": [sys.executable, "-m", "abatlas.extractors.structured_query"],
    "glob": [sys.executable, "-m", "abatlas.extractors.file_glob"],
    "nested-keys": [sys.executable, "-m", "abatlas.extractors.nested_keys"],
    "ast": [sys.executable, "-m", "abatlas.extractors.ast_query"],
    "listed": [sys.executable, "-m", "abatlas.extractors.listed"],
}


def _command(run: str, profile_dir: Path | None, entry_list_dir: Path) -> list[str]:
    """run を実行コマンドにする。

    - 'abatlas-extract <kind>' はコア同梱の抽出器
    - 相対パスは、プロファイル同梱の抽出器として profile_dir から解決する (profile.schema.json の契約)。
      profile_dir が無いか、そこに無ければ entry-list のディレクトリ (分析リポジトリ独自の抽出器) から解決する
    """
    parts = shlex.split(run)
    if parts and parts[0] == "abatlas-extract":
        if len(parts) < 2 or parts[1] not in CORE_EXTRACTORS:
            raise SystemExit(
                f"unknown core extractor: {run} (known: {sorted(CORE_EXTRACTORS)})"
            )
        return CORE_EXTRACTORS[parts[1]] + parts[2:]
    exe = Path(parts[0])
    if not exe.is_absolute():
        candidates = []
        if profile_dir is not None:
            candidates.append((profile_dir / exe).resolve())
        candidates.append((entry_list_dir / exe).resolve())
        found = next((c for c in candidates if c.is_file()), None)
        if found is None:
            raise SystemExit(
                f"extractor '{run}' が見つからない (探した場所: {', '.join(str(c) for c in candidates)})"
            )
        exe = found
    return [str(exe)] + parts[1:]


def _target(entry: dict) -> tuple[str, str, str]:
    """入口が指す先: 階層パス、層、定義のファイル。これが同じなら、同じ入口として扱う。

    行は含めない (対象のコミットを進めると、行はずれる)。説明の文 (attributes) も含めない (書き直すたびに、言い回しが変わる)。
    """
    return (entry["path"], entry["layer"], entry["source"]["file"])


def _show(target: tuple[str, str, str]) -> str:
    return f"'{target[0]}' (層 {target[1]}、{target[2]})"


def run_extractor(
    ex: dict, scope: Path, profile_dir: Path | None, entry_list_dir: Path
) -> list[dict]:
    cmd = _command(ex["run"], profile_dir, entry_list_dir) + [
        "--scope",
        str(scope),
        "--layer",
        ex["layer"],
        "--params",
        json.dumps(ex.get("params", {}), ensure_ascii=False),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)  # nosec B603 - extractor selected by the local analysis profile
    except OSError as e:
        # 実行権限が無い、先頭行のインタプリタが無い、など。起動できないことも、抽出器の失敗として止める
        raise SystemExit(
            f"extractor '{ex['name']}' を起動できない ({e.strerror or e}): {' '.join(cmd)}"
        )
    for line in proc.stderr.splitlines():
        print(f"  [{ex['name']}] {line}", file=sys.stderr)
    if proc.returncode != 0:
        raise SystemExit(
            f"extractor '{ex['name']}' failed (exit {proc.returncode}): {' '.join(cmd)}"
        )
    out = []
    for n, line in enumerate(proc.stdout.splitlines(), 1):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError as e:
            raise SystemExit(
                f"extractor '{ex['name']}' line {n}: JSON として読めない: {e}"
            )
        errs = schema_errors("entry-candidate", rec)
        if errs:
            raise SystemExit(
                f"extractor '{ex['name']}' line {n}: 契約違反: " + "; ".join(errs)
            )
        rec["extractor"] = ex["name"]
        out.append(rec)
    return out


def _validated_scope(entry_list, profile, entry_list_path, scope_override=None):
    # within はこの後で作り直すので、前回の値は検査から外す (宣言を変えた後の列挙が、古い within で止まらないように)
    before = [
        {k: v for k, v in e.items() if k != "within"} if isinstance(e, dict) else e
        for e in entry_list.get("entries", [])
    ]
    pre = validate_entry_list(
        {**entry_list, "entries": before},
        {**profile, "within": []} if profile else None,
    )
    if pre:
        raise SystemExit("entry-list が不正:\n  " + "\n  ".join(pre))
    scope = scope_override or _resolve_scope(
        entry_list["target"], entry_list_path.parent
    )
    if scope is None or not scope.is_dir():
        raise SystemExit(f"target.clone_path/scope が見つからない: {scope}")
    return scope


def _collect_candidates(entry_list, scope, profile_path, entry_list_path):
    found: dict[str, dict] = {}
    profile_dir = profile_path.parent if profile_path else None
    for ex in entry_list["extractors"]:
        recs = run_extractor(ex, scope, profile_dir, entry_list_path.parent)
        if not recs and not ex.get("params", {}).get("allow_empty"):
            raise SystemExit(
                f"extractor '{ex['name']}' が入口を 1 件も出さなかった (glob やパラメータの誤りの可能性)。"
                " 空が正しいなら params.allow_empty: true を書く。既存の一覧は変更しない"
            )
        for rec in recs:
            if rec["id"] in found:
                first = found[rec["id"]]
                a, b = _target(first), _target(rec)
                la, lb = first["source"]["line"], rec["source"]["line"]
                if a != b or la != lb:
                    # 別の入口が同じ id になっている。片方を黙って捨てると、その入口は一覧にも承認にも現れない。
                    # 1 回の列挙の中では行はずれないので、行も比べる (同じファイルの別の行の定義は、別の入口かもしれない)
                    raise SystemExit(
                        f"id '{rec['id']}' が 2 つの抽出器から、違う入口として出た: {first['extractor']} は {_show(a)} の {la} 行、{rec['extractor']} は {_show(b)} の {lb} 行。"
                        " 別の入口なら、どちらかの id を変える。同じ入口なら、片方の設定から外す。既存の一覧は変更しない"
                    )
                print(
                    f"  warn: id '{rec['id']}' が複数の抽出器から出た ({first['extractor']} と {rec['extractor']})。先に書いた抽出器の候補を残す",
                    file=sys.stderr,
                )
                continue
            found[rec["id"]] = rec
    return found


def _merge_previous_decisions(previous, found):
    entries = []
    for eid in sorted(found):
        rec = found[eid]
        old = previous.get(eid, {})
        # 人が判断した後に、同じ id の指す先 (階層パスか、定義のファイル) が変わったら、判断をやり直してもらう。
        # 行だけの違いは、同じ入口として扱う (対象のコミットを進めると、行はずれる)
        if old.get("status", "candidate") != "candidate" and _target(old) != _target(
            rec
        ):
            print(
                f"  info: 入口 '{eid}' は、{old['status']} の後に指す先が変わった ({_show(_target(old))} → {_show(_target(rec))})。"
                " candidate に戻す (承認し直す)",
                file=sys.stderr,
            )
            old = {}
        entry = {
            "id": rec["id"],
            "path": rec["path"],
            "layer": rec["layer"],
            "source": rec["source"],
            "extractor": rec["extractor"],
            "status": old.get("status", "candidate"),
        }
        if rec.get("name"):
            entry["name"] = rec["name"]
        if rec.get("attributes"):
            entry["attributes"] = rec["attributes"]
        if old.get("note"):
            entry["note"] = old["note"]
        entries.append(entry)
    return entries


def _apply_within_and_report_removals(entries, previous, found, profile):
    within = within_of(entries, profile)
    for entry in entries:
        if entry["id"] in within:
            entry["within"] = within[entry["id"]]
    gone = sorted(set(previous) - set(found))
    for g in gone:
        print(
            f"  info: 前回あった入口 '{g}' が今回は列挙されなかった (一覧から外す)",
            file=sys.stderr,
        )


def enumerate_entries(
    entry_list_path: Path,
    profile_path: Path | None = None,
    write: bool = True,
    *,
    scope_override: Path | None = None,
) -> dict:
    entry_list = load_yaml(entry_list_path)
    profile = load_yaml(profile_path) if profile_path else None
    scope = _validated_scope(entry_list, profile, entry_list_path, scope_override)

    previous = {e["id"]: e for e in entry_list.get("entries", [])}
    found = _collect_candidates(entry_list, scope, profile_path, entry_list_path)

    entries = _merge_previous_decisions(previous, found)
    # 入口が別の入口の中で動く関係 (プロファイルの within の宣言から決める。プロファイルを渡さなければ付けない)
    _apply_within_and_report_removals(entries, previous, found, profile)

    # 決定論: entries の内容が前回と同じなら enumerated_at も据え置く (差分ゼロを保つ)
    if entries != entry_list.get("entries") or "enumerated_at" not in entry_list:
        entry_list["enumerated_at"] = (
            datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        )
    entry_list["entries"] = entries
    post = validate_entry_list(entry_list, profile)
    if post:
        raise SystemExit("列挙結果が不正:\n  " + "\n  ".join(post))
    for wid, n in rejected_wrappers(entries).items():
        print(
            f"  warn: 包む入口 '{wid}' は rejected。中で動く {n} 件の入口はこれを辿らないので、その処理はどの入口の結果にも現れない"
            " (データを読まない枠なら問題ない。理由を note に書く)",
            file=sys.stderr,
        )
    if write:
        entry_list_path.write_text(
            yaml.safe_dump(entry_list, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
    n_app = sum(1 for e in entries if e["status"] == "approved")
    print(
        f"enumerate: entries={len(entries)} approved={n_app} candidate={sum(1 for e in entries if e['status'] == 'candidate')} rejected={sum(1 for e in entries if e['status'] == 'rejected')}",
        file=sys.stderr,
    )
    return entry_list
