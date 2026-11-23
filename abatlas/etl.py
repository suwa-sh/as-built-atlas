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
  io_fields.csv   I/O が触る列 (使い方ごとに use_read / use_write / use_filter。set_to = 書く値)
  links.csv       フレームから、ほかの入口へのつながり (target_entry_id = 入口の一覧と突き合わせた結果。無ければ空)
  guards.csv      フレームで行う権限の確認
  settings.csv    フレームの動きを変える設定
  rules.csv       フレームにある業務のルール
  tests.csv       フレームを通るテスト
  target_files.csv  対象の範囲 (scope) にあるファイル。対象の clone が読めるときだけ (読めなければ空)
  data_dictionary.csv  データの辞書 (列ごとの区分。sensitive = 個人情報の流れに出す区分か)
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

from . import file_name_collisions, result_file_name, scope_of
from .schemas import load_yaml, schema_errors, resource_kinds, vocab
from .validate import entry_ids_of, validate_analysis_result, within_problems

LEVEL_COLUMNS = [
    "host",
    "dbms",
    "database",
    "schema",
    "table",
    "instance",
    "namespace",
    "key_pattern",
    "broker",
    "topic",
    "directory",
    "file",
    "account",
    "bucket",
    "prefix",
    "object",
    "path",
]


def _row_claim(claims: list, evid: list, entry_id: str, where: str, claim: dict | None):
    if not claim:
        return
    ev = claim.get("evidence") or []
    claims.append(
        {
            "entry_id": entry_id,
            "claim_path": where,
            "status": claim.get("status", ""),
            "reason": claim.get("reason", ""),
            "evidence_count": len(ev),
            "note": claim.get("note", ""),
        }
    )
    for e in ev:
        evid.append(
            {
                "entry_id": entry_id,
                "claim_path": where,
                "file": e["file"],
                "line": e["line"],
            }
        )


SKIP_DIRS = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    "dist",
    "build",
    ".next",
    "target",
    "vendor",
}


def _walk_target_files(scope_dir):
    found = []
    for p in scope_dir.rglob("*"):
        rel = p.relative_to(scope_dir)
        if p.is_file() and not any(
            part in SKIP_DIRS or part.startswith(".") for part in rel.parts[:-1]
        ):
            found.append(rel.as_posix())
    return sorted(found)


def _append_target_files(rows, files):
    for f in files or []:
        name = f.rsplit("/", 1)[-1]
        rows["target_files"].append(
            {
                "file": f,
                "top": f.split("/", 1)[0] if "/" in f else "",
                "ext": name.rsplit(".", 1)[-1] if "." in name.lstrip(".") else "",
            }
        )


def _append_dictionary(rows, dictionary, categories):
    for d in sorted(
        (dictionary or {}).get("fields", []), key=lambda x: (x["resource"], x["field"])
    ):
        cat = d.get("category", "")
        rows["data_dictionary"].append(
            {
                "resource_path": d["resource"],
                "field": d["field"],
                "category": cat,
                "category_label": categories.get(cat, {}).get("label", ""),
                "sensitive": str(
                    bool(categories.get(cat, {}).get("sensitive"))
                ).lower(),
                "status": d["status"],
                "note": d.get("note", ""),
            }
        )


def _append_entries(rows, entry_list):
    for e in sorted(entry_list.get("entries", []), key=lambda x: x["id"]):
        for ord_, w in enumerate(e.get("within", []), 1):
            rows["entry_within"].append(
                {"entry_id": e["id"], "ord": ord_, "within_entry_id": w}
            )
        rows["entries"].append(
            {
                "entry_id": e["id"],
                "path": e["path"],
                "name": e.get("name", ""),
                "layer": e["layer"],
                "status": e["status"],
                "extractor": e.get("extractor", ""),
                "source_file": e["source"]["file"],
                "source_line": e["source"]["line"],
                "depth": len([p for p in e["path"].split("/") if p]),
            }
        )


def _append_result(rows, r, eid, profile):
    an = r["analyzer"]
    rows["results"].append(
        {
            "entry_id": eid,
            "path": r["entry"]["path"],
            "layer": r["entry"]["layer"],
            "target_repo": r["target"]["repo"],
            "target_commit": r["target"]["commit"],
            "effective_commit": r["target"]["commit"],
            "update_status": "analyzed",
            "target_scope": r["target"].get("scope", "."),
            "profile_id": an["profile"]["id"],
            "profile_version": an["profile"]["version"],
            # 分析の決まり (context.md) は版ごとに変わる。古い版の結果は、今の決まりと範囲が違うことがある (例: 包む入口の処理を含んだまま)
            "profile_stale": ""
            if profile is None
            else str(an["profile"]["version"] != str(profile.get("version"))).lower(),
            "skill_version": an["skill_version"],
            "model": an.get("model", ""),
            "analyzed_at": an["analyzed_at"],
            "analyst": an.get("analyst", ""),
            "reviewed_findings_open": (an.get("reviewed") or {}).get(
                "findings_open", ""
            ),
            "run_cost_usd": (an.get("run") or {}).get("cost_usd", ""),
            "run_duration_s": (an.get("run") or {}).get("duration_s", ""),
            "run_by": (an.get("run") or {}).get("by", ""),
            "summary_status": r["summary"]["status"],
            "summary": r["summary"].get("value", ""),
            "frame_count": len(r["callstack"]),
            "tests_analyzed": str(bool(an.get("tests"))).lower(),
            "aspects_analyzed": str(_has_aspects(an["skill_version"])).lower(),
        }
    )
    _row_claim(rows["claims"], rows["evidence"], eid, "summary", r["summary"])


def _append_frame(rows, f, eid, fid, seq, profile, boundary, splittable):
    call = f.get("call") or {}
    summary = f.get("summary") or {}
    rows["frames"].append(
        {
            "entry_id": eid,
            "frame_id": fid,
            "seq": seq,
            "layer": f["layer"],
            "kind": f.get("kind", ""),
            "name": f["name"],
            "source_file": f["source"]["file"],
            "source_line": f["source"]["line"],
            "caller_id": f.get("caller") or "",
            "call_status": call.get("status", ""),
            "call_reason": call.get("reason", ""),
            "summary_status": summary.get("status", ""),
            "summary": summary.get("value", ""),
            "summary_reason": summary.get("reason", ""),
            "call_when": call.get("when", ""),
            "call_condition": call.get("condition", ""),
            # 外との境の層か (リポジトリに定義が無い処理)。プロファイルを渡さなければ、判定しない (空)
            "boundary": "" if profile is None else str(f["layer"] in boundary).lower(),
            # 別の入口に分けられる層か (プロファイルの split_from に挙がった層)。プロファイルを渡さなければ、判定しない (空)
            "splittable": ""
            if profile is None
            else str(f["layer"] in splittable).lower(),
        }
    )


def _append_links(rows, f, eid, fid, w, by_id, by_path):
    for i, ln in enumerate(f.get("links", [])):
        rows["links"].append(
            {
                "entry_id": eid,
                "frame_id": fid,
                "idx": i,
                "kind": ln["kind"],
                "target": ln["target"],
                "target_entry_id": _link_target(ln, by_id, by_path),
                "status": ln["status"],
                "reason": ln.get("reason", ""),
                "note": ln.get("note", ""),
            }
        )
        _row_claim(rows["claims"], rows["evidence"], eid, f"{w}/links/{i}", ln)


def _append_frame_claims(rows, f, eid, fid, w):
    for name, keys in FRAME_LISTS.items():
        for i, c in enumerate(f.get(name, [])):
            rows[name].append(
                {
                    "entry_id": eid,
                    "frame_id": fid,
                    "idx": i,
                    **{k: c.get(k, "") for k in keys},
                    "status": c["status"],
                    "reason": c.get("reason", ""),
                    "note": c.get("note", ""),
                }
            )
            _row_claim(rows["claims"], rows["evidence"], eid, f"{w}/{name}/{i}", c)
    _row_claim(rows["claims"], rows["evidence"], eid, f"{w}/call", f.get("call"))
    _row_claim(rows["claims"], rows["evidence"], eid, f"{w}/summary", f.get("summary"))
    for i, p in enumerate(f.get("parameters", [])):
        rows["parameters"].append(
            {
                "entry_id": eid,
                "frame_id": fid,
                "idx": i,
                "name": p["name"],
                "value": p.get("value", ""),
                "status": p["status"],
                "reason": p.get("reason", ""),
            }
        )
        _row_claim(rows["claims"], rows["evidence"], eid, f"{w}/parameters/{i}", p)


def _append_resource(rows, io, eid, fid, i, kinds):
    kind = io["resource"]["kind"]
    levels = io["resource"].get("levels", {})
    ops = kinds.get(kind, {}).get("ops", [])
    rank = next((n for n, o in enumerate(ops) if o["id"] == io["op"]), len(ops))
    letter = next(
        (o["letter"] for o in ops if o["id"] == io["op"]),
        io["op"][:1].upper(),
    )
    direction = next(
        (o.get("direction", "out") for o in ops if o["id"] == io["op"]),
        "out",
    )
    row = {
        "entry_id": eid,
        "frame_id": fid,
        "idx": i,
        "op": io["op"],
        "op_letter": letter,
        "op_rank": rank,
        "op_direction": direction,
        "kind": kind,
        "kind_label": kinds.get(kind, {}).get("label", kind),
    }
    for c in LEVEL_COLUMNS:
        row["lv_" + c] = levels.get(c, "")
    # データを 1 本のパスにしたもの (階層 × 階層の行列の列キー)
    known = [
        levels[level]
        for level in kinds.get(kind, {}).get("levels", [])
        if level in levels
    ]
    row["resource_path"] = "/" + kind + ("/" + "/".join(known) if known else "")
    row.update(
        {
            "detail": io.get("detail", ""),
            "status": io["status"],
            "reason": io.get("reason", ""),
            "note": io.get("note", ""),
        }
    )
    rows["io"].append(row)
    return kind, row


def _append_fields(rows, io, eid, fid, i, kind, row):
    for j, fl in enumerate(io.get("fields", [])):
        rows["io_fields"].append(
            {
                "entry_id": eid,
                "frame_id": fid,
                "io_idx": i,
                "idx": j,
                "name": fl["name"],
                **{
                    "use_" + u: str(u in fl["use"]).lower()
                    for u in ("read", "write", "filter")
                },
                "set_to": fl.get("set_to", ""),
                "resource_path": row["resource_path"],
                "kind": kind,
                "io_status": io["status"],
            }
        )


def _entry_list_problems(entry_list, profile):
    problems = [
        f"entry-list.yaml: {e}" for e in schema_errors("entry-list", entry_list)
    ]
    if not problems:
        ids = [e["id"] for e in entry_list["entries"]]
        if len(ids) != len(set(ids)):
            problems.append("entry-list.yaml: entries の id が重複している")
        else:
            problems.extend(
                p.replace("entry-list: ", "entry-list.yaml: ", 1)
                for p in within_problems(entry_list["entries"], profile)
            )
    return problems


def _read_results(analysis_repo, entry_list, profile, scope_dir, problems):
    results = []
    seen: dict[str, str] = {}
    for p in sorted((analysis_repo / "results").glob("*.yaml")):
        r = load_yaml(p)
        errs = result_errors(r, profile, scope_dir, entry_ids_of(entry_list))
        if errs:
            problems.extend(f"{p.name}: {e}" for e in errs)
            continue
        eid = r["entry"]["id"]
        expected = result_file_name(eid)  # 1 入口 = 1 ファイル。名前は id から決まる
        if p.name != expected:
            problems.append(
                f"{p.name}: entry.id {eid} のファイル名は {expected} でなければならない"
            )
        if eid in seen:
            problems.append(
                f"{p.name}: entry.id {eid} は {seen[eid]} と重複している (進行状況とコストが二重に数えられる)"
            )
        seen.setdefault(eid, p.name)
        results.append(r)
    return results


def _other_target_entries(analysis_repo, results, reused):
    wd_path = analysis_repo / "work-definition.yaml"
    work = load_yaml(wd_path) if wd_path.is_file() else {}
    work_target = (work or {}).get("target")
    contexts = {}
    other_target = []  # 作業定義と、対象 (リポジトリ、範囲、コミット) が違う結果。止めずに知らせる
    if isinstance(work_target, dict):
        for r in results:
            rt = r["target"]
            if (rt.get("repo"), scope_of(rt), rt.get("commit")) != (
                work_target.get("repo"),
                scope_of(work_target),
                work_target.get("commit"),
            ):
                from .reuse import verified_result

                if verified_result(analysis_repo, work, r, contexts=contexts):
                    reused[r["entry"]["id"]] = work_target["commit"]
                else:
                    other_target.append(r["entry"]["id"])
    return other_target


def _report_counts(rows, other_target, profile):
    counts = {k: len(v) for k, v in rows.items()}
    if other_target:
        counts["other_target_results"] = len(other_target)
        print(
            f"etl: warn: 作業定義と、対象 (リポジトリ、範囲、コミット) が違う結果が {len(other_target)} 件ある: {', '.join(sorted(other_target)[:10])}{' …' if len(other_target) > 10 else ''}。"
            " 止めずに集計する (対象を更新した後、入口を 1 件ずつ分析し直す間も、画面で見られるように)。入口ごとのコミットは、入口の概要の表の target_commit で分かる。"
            " validate result --work は、この違いを指摘する",
            file=sys.stderr,
        )
    stale = sorted(
        r["entry_id"] for r in rows["results"] if r["profile_stale"] == "true"
    )
    if profile is not None:
        counts["stale_results"] = len(stale)
    if stale:
        print(
            f"etl: warn: 今のプロファイルの版 ({profile.get('version')}) と違う版で分析した結果が {len(stale)} 件ある: {', '.join(stale[:10])}{' …' if len(stale) > 10 else ''}。"
            " 分析の決まりが変わっていれば、範囲が今の決まりと違う (例: 包む入口の処理を含んだまま)。再分析する",
            file=sys.stderr,
        )
    return counts


def target_files(scope_dir: Path | None) -> list[str]:
    """対象の範囲にあるファイル (範囲からの相対パス、並べ替え済み)。範囲が読めなければ空。

    git の管理下なら、管理されているファイルだけ (生成物や依存を除ける)。そうでなければ、隠しフォルダと、よくある生成物・依存のフォルダを除いて歩く。
    """
    if scope_dir is None or not scope_dir.is_dir():
        return []
    import subprocess  # nosec B404 - executes subprocesses with argument lists

    try:
        out = subprocess.run(  # nosec B603, B607 - Git CLI to list tracked paths
            ["git", "-C", str(scope_dir), "ls-files", "-z"],
            capture_output=True,
            check=True,
            timeout=120,
        ).stdout
        files = [
            f
            for f in out.decode("utf-8", "replace").split("\0")
            if f and (scope_dir / f).is_file()
        ]  # 索引にあっても、消したファイルは除く
        if files:
            return sorted(files)
    except (OSError, subprocess.SubprocessError):
        pass
    return _walk_target_files(scope_dir)


ASPECTS_SINCE = (
    0,
    4,
)  # 分析 skill がこの版から、呼び出しの条件・列・つながり・権限の確認・設定・業務のルールを書く


def _has_aspects(skill_version: str) -> bool:
    """分析 skill の版が、足した観点を分析する版か。読めない版 (見本の 0.0.0-fixture など) は、数字の部分だけで比べる。"""
    nums = []
    for part in skill_version.split(".")[:2]:
        digits = "".join(ch for ch in part if ch.isdigit())
        nums.append(int(digits) if digits else 0)
    return tuple(nums + [0] * (2 - len(nums))) >= ASPECTS_SINCE


def _link_target(link: dict, by_id: dict, by_path: dict) -> str:
    """つながりの行き先を、入口の一覧と突き合わせる。entry_id があればそれ (一覧に無ければ空)。無ければ target が id か階層パスと一致する入口。"""
    if "entry_id" in link:
        return link["entry_id"] if link["entry_id"] in by_id else ""
    t = link["target"]
    return t if t in by_id else by_path.get(t, "")


# フレームが持つ主張の並び (名前 → その行に写す項目)
FRAME_LISTS = {
    "guards": ["kind", "value"],
    "settings": ["name", "kind", "effect"],
    "rules": ["kind", "value"],
    "tests": ["name", "kind"],
}


def build_rows(
    entry_list: dict,
    results: list[dict],
    profile: dict | None = None,
    dictionary: dict | None = None,
    files: list[str] | None = None,
) -> dict[str, list[dict]]:
    """profile を渡すと、結果ごとに「今のプロファイルの版と違う版で分析したか」(profile_stale) を付ける。dictionary はデータの辞書 (無ければ空の表)。"""
    rows = {k: [] for k in COLUMNS}
    categories = vocab("data-categories")["categories"]
    _append_target_files(rows, files)
    _append_dictionary(rows, dictionary, categories)
    _append_entries(rows, entry_list)
    kinds = resource_kinds()
    by_id = {e["id"]: e for e in entry_list.get("entries", [])}
    by_path = {e["path"]: e["id"] for e in entry_list.get("entries", [])}
    boundary = {
        t["id"]
        for t in (profile or {}).get("layers", [])
        if t.get("role") == "boundary"
    }
    splittable = {
        s for t in (profile or {}).get("layers", []) for s in t.get("split_from", [])
    }
    for r in sorted(results, key=lambda x: x["entry"]["id"]):
        eid = r["entry"]["id"]
        _append_result(rows, r, eid, profile)
        for seq, f in enumerate(r["callstack"]):
            fid = f["id"]
            w = f"callstack/{fid}"
            _append_frame(rows, f, eid, fid, seq, profile, boundary, splittable)
            _append_links(rows, f, eid, fid, w, by_id, by_path)
            _append_frame_claims(rows, f, eid, fid, w)
            for i, io in enumerate(f.get("io", [])):
                kind, row = _append_resource(rows, io, eid, fid, i, kinds)
                _append_fields(rows, io, eid, fid, i, kind, row)
                _row_claim(rows["claims"], rows["evidence"], eid, f"{w}/io/{i}", io)
    return rows


COLUMNS = {
    "entries": [
        "entry_id",
        "path",
        "name",
        "layer",
        "status",
        "extractor",
        "source_file",
        "source_line",
        "depth",
    ],
    "results": [
        "entry_id",
        "path",
        "layer",
        "target_repo",
        "target_commit",
        "effective_commit",
        "update_status",
        "target_scope",
        "profile_id",
        "profile_version",
        "profile_stale",
        "skill_version",
        "model",
        "analyzed_at",
        "analyst",
        "reviewed_findings_open",
        "run_cost_usd",
        "run_duration_s",
        "run_by",
        "summary_status",
        "summary",
        "frame_count",
        "tests_analyzed",
        "aspects_analyzed",
    ],
    "frames": [
        "entry_id",
        "frame_id",
        "seq",
        "layer",
        "kind",
        "name",
        "source_file",
        "source_line",
        "caller_id",
        "call_status",
        "call_reason",
        "summary_status",
        "summary",
        "summary_reason",
        "call_when",
        "call_condition",
        "boundary",
        "splittable",
    ],
    "io": [
        "entry_id",
        "frame_id",
        "idx",
        "op",
        "op_letter",
        "op_rank",
        "op_direction",
        "kind",
        "kind_label",
        *["lv_" + c for c in LEVEL_COLUMNS],
        "resource_path",
        "detail",
        "status",
        "reason",
        "note",
    ],
    "parameters": ["entry_id", "frame_id", "idx", "name", "value", "status", "reason"],
    "claims": ["entry_id", "claim_path", "status", "reason", "evidence_count", "note"],
    "evidence": ["entry_id", "claim_path", "file", "line"],
    "entry_within": ["entry_id", "ord", "within_entry_id"],
    "io_fields": [
        "entry_id",
        "frame_id",
        "io_idx",
        "idx",
        "name",
        "use_read",
        "use_write",
        "use_filter",
        "set_to",
        "resource_path",
        "kind",
        "io_status",
    ],
    "links": [
        "entry_id",
        "frame_id",
        "idx",
        "kind",
        "target",
        "target_entry_id",
        "status",
        "reason",
        "note",
    ],
    "guards": [
        "entry_id",
        "frame_id",
        "idx",
        "kind",
        "value",
        "status",
        "reason",
        "note",
    ],
    "settings": [
        "entry_id",
        "frame_id",
        "idx",
        "name",
        "kind",
        "effect",
        "status",
        "reason",
        "note",
    ],
    "rules": [
        "entry_id",
        "frame_id",
        "idx",
        "kind",
        "value",
        "status",
        "reason",
        "note",
    ],
    "tests": [
        "entry_id",
        "frame_id",
        "idx",
        "name",
        "kind",
        "status",
        "reason",
        "note",
    ],
    "target_files": ["file", "top", "ext"],
    "data_dictionary": [
        "resource_path",
        "field",
        "category",
        "category_label",
        "sensitive",
        "status",
        "note",
    ],
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


def result_errors(
    result: dict,
    profile: dict | None = None,
    scope_dir: Path | None = None,
    entry_ids: set[str] | None = None,
) -> list[str]:
    """分析結果 1 件の検査。検査のコマンド (validate result) と同じ検査を通す (形式、呼び出しの木、語彙、列、プロファイルの層との突き合わせ)。

    scope_dir (対象の範囲のフォルダ) を渡すと、根拠のファイルの実在と行数も見る。対象の clone が読めない場所では渡さない (その検査だけを省く)。
    """
    return validate_analysis_result(result, profile, scope_dir, entry_ids)


def run_etl(
    analysis_repo: Path,
    out_dir: Path,
    profile: dict | None = None,
    scope_dir: Path | None = None,
) -> dict[str, int]:
    """entry-list と results/*.yaml を検査してから seed を書く。違反があれば何も書かない。

    分析結果は、検査のコマンド (validate result) と同じ検査を通す。検査で落ちる結果が、集計には通ることが無いようにするため。違いは 2 つ:
    根拠のファイルの実在と行数は、対象の clone が読めるときだけ見る (読めない場所でも集計できるように)。対象 (リポジトリ、範囲、コミット) が作業定義と違う結果は、止めずに知らせる
    (対象を更新した後、入口を 1 件ずつ分析し直す間も、集計して画面で見られるように)。

    入口を包む入口 (entries[].within) は、指す入口の実在と循環も見る。profile を渡すと、宣言から決まる値との一致も見る
    (古い一覧のまま集計して、欠けた・誤った関係を画面に出さないため)。
    """
    entry_list = load_yaml(analysis_repo / "entry-list.yaml")
    from .dictionary import (
        FILE as DICT_FILE,
        dictionary_problems,
    )  # 循環を避けるため、ここで読む (dictionary は build_rows を使う)

    dictionary = (
        load_yaml(analysis_repo / DICT_FILE)
        if (analysis_repo / DICT_FILE).is_file()
        else None
    )
    dict_problems = dictionary_problems(dictionary) if dictionary is not None else []
    problems = _entry_list_problems(entry_list, profile)
    results = _read_results(analysis_repo, entry_list, profile, scope_dir, problems)
    reused = {}
    other_target = _other_target_entries(analysis_repo, results, reused)
    for name, group in sorted(
        file_name_collisions({e["id"] for e in entry_list.get("entries", [])}).items()
    ):
        problems.append(
            f"entry-list.yaml: id {group} は同じ結果ファイル名 '{name}' になる (片方の結果しか置けない)"
        )
    problems.extend(dict_problems)
    if problems:
        raise SystemExit(
            "etl: 入力が検査に通らないので書かない (分析結果は validate result と同じ検査):\n  "
            + "\n  ".join(problems[:20])
        )
    rows = build_rows(entry_list, results, profile, dictionary, target_files(scope_dir))
    stale = set(other_target)
    for row in rows["results"]:
        eid = row["entry_id"]
        if eid in reused:
            row.update(effective_commit=reused[eid], update_status="reused")
        elif eid in stale:
            row.update(effective_commit="", update_status="stale")
    write_seeds(rows, out_dir)
    counts = _report_counts(rows, other_target, profile)
    counts["reused_results"] = len(reused)
    return counts
