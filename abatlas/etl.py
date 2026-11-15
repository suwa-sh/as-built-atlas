"""ETL: 分析リポジトリの entry-list.yaml と results/*.yaml を seed CSV に分解する。

決定論: 同じ入力なら同じ CSV (行は id 順、列は固定)。seed は派生物で、いつでも作り直せる。

出力 (out_dir 配下):
  entries.csv     入口一覧 (承認状態を含む)
  results.csv     分析結果 1 件 = 1 行 (入口ごとの分析器・対象コミット・概要)
  frames.csv      コールスタックのフレーム (seq = callstack の並び順)
  io.csv          フレームの I/O (データの段を lv_<段> の列に展開。op_letter / op_rank は語彙の 1 文字と並び順)
  parameters.csv  フレームのパラメータ
  claims.csv      すべての主張 (品質 mart 用: 状態・理由・根拠件数)
  evidence.csv    主張ごとの根拠 (file:line)
  entry_within.csv  入口を包む入口 (entry-list の entries[].within。ord = 外側からの順)
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

from . import file_name_collisions, result_file_name
from .schemas import load_yaml, schema_errors, resource_kinds
from .validate import within_problems

LEVEL_COLUMNS = ["host", "dbms", "database", "schema", "table", "instance", "namespace", "key_pattern",
                 "broker", "topic", "directory", "file", "account", "bucket", "prefix", "object", "path"]


def _row_claim(claims: list, evid: list, entry_id: str, where: str, claim: dict | None):
    if not claim:
        return
    ev = claim.get("evidence") or []
    claims.append({
        "entry_id": entry_id,
        "claim_path": where,
        "status": claim.get("status", ""),
        "reason": claim.get("reason", ""),
        "evidence_count": len(ev),
        "note": claim.get("note", ""),
    })
    for e in ev:
        evid.append({"entry_id": entry_id, "claim_path": where, "file": e["file"], "line": e["line"]})


def build_rows(entry_list: dict, results: list[dict], profile: dict | None = None) -> dict[str, list[dict]]:
    """profile を渡すと、結果ごとに「今のプロファイルの版と違う版で分析したか」(profile_stale) を付ける。"""
    rows = {k: [] for k in COLUMNS}
    for e in sorted(entry_list.get("entries", []), key=lambda x: x["id"]):
        for ord_, w in enumerate(e.get("within", []), 1):
            rows["entry_within"].append({"entry_id": e["id"], "ord": ord_, "within_entry_id": w})
        rows["entries"].append({
            "entry_id": e["id"], "path": e["path"], "name": e.get("name", ""), "layer": e["layer"],
            "status": e["status"], "extractor": e.get("extractor", ""),
            "source_file": e["source"]["file"], "source_line": e["source"]["line"],
            "depth": len([p for p in e["path"].split("/") if p]),
        })
    kinds = resource_kinds()
    for r in sorted(results, key=lambda x: x["entry"]["id"]):
        eid = r["entry"]["id"]
        an = r["analyzer"]
        rows["results"].append({
            "entry_id": eid, "path": r["entry"]["path"], "layer": r["entry"]["layer"],
            "target_repo": r["target"]["repo"], "target_commit": r["target"]["commit"], "target_scope": r["target"].get("scope", "."),
            "profile_id": an["profile"]["id"], "profile_version": an["profile"]["version"],
            # 分析の決まり (context.md) は版ごとに変わる。古い版の結果は、今の決まりと範囲が違うことがある (例: 包む入口の処理を含んだまま)
            "profile_stale": "" if profile is None else str(an["profile"]["version"] != str(profile.get("version"))).lower(),
            "skill_version": an["skill_version"], "model": an.get("model", ""), "analyzed_at": an["analyzed_at"], "analyst": an.get("analyst", ""),
            "reviewed_findings_open": (an.get("reviewed") or {}).get("findings_open", ""),
            "run_cost_usd": (an.get("run") or {}).get("cost_usd", ""), "run_duration_s": (an.get("run") or {}).get("duration_s", ""),
            "run_by": (an.get("run") or {}).get("by", ""),
            "summary_status": r["summary"]["status"], "summary": r["summary"].get("value", ""),
            "frame_count": len(r["callstack"]),
        })
        _row_claim(rows["claims"], rows["evidence"], eid, "summary", r["summary"])
        for seq, f in enumerate(r["callstack"]):
            fid = f["id"]
            w = f"callstack/{fid}"
            rows["frames"].append({
                "entry_id": eid, "frame_id": fid, "seq": seq, "layer": f["layer"], "kind": f.get("kind", ""), "name": f["name"],
                "source_file": f["source"]["file"], "source_line": f["source"]["line"],
                "caller_id": f.get("caller") or "",
                "call_status": (f.get("call") or {}).get("status", ""), "call_reason": (f.get("call") or {}).get("reason", ""),
                "summary_status": (f.get("summary") or {}).get("status", ""), "summary": (f.get("summary") or {}).get("value", ""),
                "summary_reason": (f.get("summary") or {}).get("reason", ""),
            })
            _row_claim(rows["claims"], rows["evidence"], eid, f"{w}/call", f.get("call"))
            _row_claim(rows["claims"], rows["evidence"], eid, f"{w}/summary", f.get("summary"))
            for i, p in enumerate(f.get("parameters", [])):
                rows["parameters"].append({"entry_id": eid, "frame_id": fid, "idx": i, "name": p["name"], "value": p.get("value", ""),
                                           "status": p["status"], "reason": p.get("reason", "")})
                _row_claim(rows["claims"], rows["evidence"], eid, f"{w}/parameters/{i}", p)
            for i, io in enumerate(f.get("io", [])):
                kind = io["resource"]["kind"]
                levels = io["resource"].get("levels", {})
                ops = kinds.get(kind, {}).get("ops", [])
                rank = next((n for n, o in enumerate(ops) if o["id"] == io["op"]), len(ops))
                letter = next((o["letter"] for o in ops if o["id"] == io["op"]), io["op"][:1].upper())
                direction = next((o.get("direction", "out") for o in ops if o["id"] == io["op"]), "out")
                row = {"entry_id": eid, "frame_id": fid, "idx": i, "op": io["op"], "op_letter": letter, "op_rank": rank, "op_direction": direction,
                       "kind": kind, "kind_label": kinds.get(kind, {}).get("label", kind)}
                for c in LEVEL_COLUMNS:
                    row["lv_" + c] = levels.get(c, "")
                # データを 1 本のパスにしたもの (階層 × 階層の行列の列キー)
                known = [levels[l] for l in kinds.get(kind, {}).get("levels", []) if l in levels]
                row["resource_path"] = "/" + kind + ("/" + "/".join(known) if known else "")
                row.update({"detail": io.get("detail", ""), "status": io["status"], "reason": io.get("reason", ""), "note": io.get("note", "")})
                rows["io"].append(row)
                _row_claim(rows["claims"], rows["evidence"], eid, f"{w}/io/{i}", io)
    return rows


COLUMNS = {
    "entries": ["entry_id", "path", "name", "layer", "status", "extractor", "source_file", "source_line", "depth"],
    "results": ["entry_id", "path", "layer", "target_repo", "target_commit", "target_scope", "profile_id", "profile_version", "profile_stale", "skill_version", "model",
                "analyzed_at", "analyst", "reviewed_findings_open", "run_cost_usd", "run_duration_s", "run_by", "summary_status", "summary", "frame_count"],
    "frames": ["entry_id", "frame_id", "seq", "layer", "kind", "name", "source_file", "source_line", "caller_id", "call_status", "call_reason",
               "summary_status", "summary", "summary_reason"],
    "io": ["entry_id", "frame_id", "idx", "op", "op_letter", "op_rank", "op_direction", "kind", "kind_label", *["lv_" + c for c in LEVEL_COLUMNS],
           "resource_path", "detail", "status", "reason", "note"],
    "parameters": ["entry_id", "frame_id", "idx", "name", "value", "status", "reason"],
    "claims": ["entry_id", "claim_path", "status", "reason", "evidence_count", "note"],
    "evidence": ["entry_id", "claim_path", "file", "line"],
    "entry_within": ["entry_id", "ord", "within_entry_id"],
}


def write_seeds(rows: dict[str, list[dict]], out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, cols in COLUMNS.items():
        p = out_dir / f"{name}.csv"
        with p.open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, lineterminator="\n")
            w.writeheader()
            for r in rows[name]:
                w.writerow({c: r.get(c, "") for c in cols})
        written.append(p)
    return written


def _op_errors(result: dict) -> list[str]:
    """I/O の操作 (op) がデータの種類の語彙にあるか (schema は op を文字列としか言えないので、ETL でも種類と突き合わせる)。"""
    kinds = resource_kinds()
    out = []
    for f in result.get("callstack", []):
        for i, io in enumerate(f.get("io", [])):
            kind = io["resource"]["kind"]
            ops = [o["id"] for o in kinds.get(kind, {}).get("ops", [])]
            if kind not in kinds:
                out.append(f"callstack/{f['id']}/io/{i}: データの種類 '{kind}' が語彙に無い")
            elif io["op"] not in ops:
                out.append(f"callstack/{f['id']}/io/{i}: 操作 '{io['op']}' は {kind} では使えない (使えるのは {ops})")
    return out


def run_etl(analysis_repo: Path, out_dir: Path, profile: dict | None = None) -> dict[str, int]:
    """entry-list と results/*.yaml を schema で検証してから seed を書く。違反があれば何も書かない。

    入口を包む入口 (entries[].within) は、指す入口の実在と循環も見る。profile を渡すと、宣言から決まる値との一致も見る
    (古い一覧のまま集計して、欠けた・誤った関係を画面に出さないため)。
    """
    entry_list = load_yaml(analysis_repo / "entry-list.yaml")
    problems = [f"entry-list.yaml: {e}" for e in schema_errors("entry-list", entry_list)]
    if not problems:
        ids = [e["id"] for e in entry_list["entries"]]
        if len(ids) != len(set(ids)):
            problems.append("entry-list.yaml: entries の id が重複している")
        else:
            problems.extend(p.replace("entry-list: ", "entry-list.yaml: ", 1) for p in within_problems(entry_list["entries"], profile))
    results = []
    seen: dict[str, str] = {}
    for p in sorted((analysis_repo / "results").glob("*.yaml")):
        r = load_yaml(p)
        errs = schema_errors("analysis-result", r)
        errs += _op_errors(r)
        if errs:
            problems.extend(f"{p.name}: {e}" for e in errs)
            continue
        eid = r["entry"]["id"]
        expected = result_file_name(eid)  # 1 入口 = 1 ファイル。名前は id から決まる
        if p.name != expected:
            problems.append(f"{p.name}: entry.id {eid} のファイル名は {expected} でなければならない")
        if eid in seen:
            problems.append(f"{p.name}: entry.id {eid} は {seen[eid]} と重複している (進行状況とコストが二重に数えられる)")
        seen.setdefault(eid, p.name)
        results.append(r)
    for name, group in sorted(file_name_collisions({e["id"] for e in entry_list.get("entries", [])}).items()):
        problems.append(f"entry-list.yaml: id {group} は同じ結果ファイル名 '{name}' になる (片方の結果しか置けない)")
    if problems:
        raise SystemExit("etl: 入力が schema に違反しているので書かない:\n  " + "\n  ".join(problems[:20]))
    rows = build_rows(entry_list, results, profile)
    write_seeds(rows, out_dir)
    counts = {k: len(v) for k, v in rows.items()}
    stale = sorted(r["entry_id"] for r in rows["results"] if r["profile_stale"] == "true")
    if profile is not None:
        counts["stale_results"] = len(stale)
    if stale:
        print(f"etl: warn: 今のプロファイルの版 ({profile.get('version')}) と違う版で分析した結果が {len(stale)} 件ある: {', '.join(stale[:10])}{' …' if len(stale) > 10 else ''}。"
              " 分析の決まりが変わっていれば、範囲が今の決まりと違う (例: 包む入口の処理を含んだまま)。再分析する", file=sys.stderr)
    return counts
