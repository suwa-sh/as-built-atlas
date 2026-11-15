"""突合の評価: 分析結果を正解 (または別の分析結果) と突き合わせ、適合率 / 再現率を出す。

  abatlas evaluate <results> --truth <truth> [--json]

- `<results>` / `<truth>` はディレクトリ (中の *.yaml すべて) かファイル 1 つ。入口 id で対応付ける
- 照合のキー (表記ゆれを少し吸収する):
    フレーム:   (layer, source.file)
    I/O:        (kind, op, 段の値の組)。値は前後の空白と末尾の '/' を落とし、host / dbms / bucket / account は小文字に。
                rdb で schema が無く table に '.' があれば schema と table に分ける
    パラメータ: (フレームのキー, 名前)
- 一致した I/O どうしで 状態 (fact / interpretation / unknown) と unknown の理由の一致も数える (同じキーが複数あれば多重集合で照合し、並び順に依らない)
- 文 (summary / detail / note) は比べない (言い回しは機械では比べられない)
- 正解にだけある入口は「未分析」として、その全項目を正解だけ (FN) に数える。結果にだけある入口は「正解に無い」として、その全項目を結果だけ (FP) に数える。
  総合の適合率・再現率はこれらを含む (1 件だけ分析して 100% にはならない)

- 数え方は 2 通り出す。既定は重複込み (同じキーが 2 回書いてあれば 2 つ)。`distinct` は重複を除く (同じ入口の中で同じキーは 1 つ)。
  同じ処理を呼び出し元ごとに何度書くかは分析者で揺れるので、「どのデータに触れるか」が合っているかは `distinct` で見る

適合率 (precision) = 一致 / 結果にある数、再現率 (recall) = 一致 / 正解にある数。
終了コード (重複込みの数え方で決める): 0 = 完全一致 (未分析・正解に無い入口も無い) / 1 = 不一致あり / 2 = 入力が読めない・比べられる入口が無い。
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from .schemas import load_yaml

LOWER_LEVELS = {"host", "dbms", "bucket", "account", "broker"}
SECTIONS = ("frames", "io", "parameters")


def load_results(path: Path) -> dict[str, dict]:
    """ディレクトリの *.yaml (またはファイル 1 つ) を入口 id で引く。形が違うファイルと入口 id の重複は入力エラー (黙って飛ばさない)。"""
    files = sorted(path.glob("*.yaml")) if path.is_dir() else [path]
    out: dict[str, dict] = {}
    seen: dict[str, Path] = {}
    problems: list[str] = []
    for p in files:
        try:
            r = load_yaml(p)
        except Exception as ex:  # YAML として読めない
            problems.append(f"{p}: 読めない: {ex}")
            continue
        if not isinstance(r, dict) or not isinstance(r.get("entry"), dict) or "id" not in r["entry"] or not isinstance(r.get("callstack"), list):
            problems.append(f"{p}: 分析結果の形 (entry.id と callstack) ではない")
            continue
        eid = r["entry"]["id"]
        if eid in seen:
            problems.append(f"{p}: 入口 id '{eid}' が {seen[eid].name} と重複している")
            continue
        seen[eid] = p
        out[eid] = r
    if problems:
        raise SystemExit(f"{path}: 突合できない入力がある:\n  " + "\n  ".join(problems))
    return out


def _norm(level: str, value) -> str:
    v = str(value).strip().replace("//", "/")
    if len(v) > 1:
        v = v.rstrip("/")
    return v.lower() if level in LOWER_LEVELS else v


def normalize_levels(kind: str, levels: dict | None) -> tuple:
    lv = dict(levels or {})
    if kind == "rdb" and "table" in lv and "schema" not in lv and "." in str(lv["table"]):
        lv["schema"], lv["table"] = str(lv["table"]).split(".", 1)
    return tuple(sorted((k, _norm(k, v)) for k, v in lv.items() if v not in (None, "")))


def frame_key(frame: dict) -> tuple:
    return (frame["layer"], frame["source"]["file"])


def io_key(io: dict) -> tuple:
    kind = io["resource"]["kind"]
    return (kind, io["op"], normalize_levels(kind, io["resource"].get("levels")))


def _io_items(result: dict) -> list[tuple[tuple, dict]]:
    return [(io_key(io), io) for f in result["callstack"] for io in f.get("io", [])]


def _param_keys(result: dict) -> Counter:
    return Counter((frame_key(f), p["name"].strip()) for f in result["callstack"] for p in f.get("parameters", []))


def _pr(tp: int, fp: int, fn: int) -> dict:
    return {"tp": tp, "fp": fp, "fn": fn,
            "precision": round(tp / (tp + fp), 3) if tp + fp else None,
            "recall": round(tp / (tp + fn), 3) if tp + fn else None}


def _match(a: Counter, b: Counter) -> tuple[int, int, int]:
    tp = sum(min(n, b[k]) for k, n in a.items())
    return tp, sum(a.values()) - tp, sum(b.values()) - tp


def _match_distinct(a: Counter, b: Counter) -> tuple[int, int, int]:
    """重複を除いた照合: 同じ入口の中で同じキーは何度書いてあっても 1 つに数える。"""
    sa, sb = set(a), set(b)
    return len(sa & sb), len(sa - sb), len(sb - sa)


def _section_keys(result: dict, section: str) -> Counter:
    if section == "frames":
        return Counter(frame_key(f) for f in result["callstack"])
    if section == "io":
        return Counter(k for k, _ in _io_items(result))
    return _param_keys(result)


def compare_entry(result: dict, truth: dict) -> dict:
    fr_r, fr_t = Counter(frame_key(f) for f in result["callstack"]), Counter(frame_key(f) for f in truth["callstack"])
    frames = _pr(*_match(fr_r, fr_t))
    frames["missing"] = sorted(f"{k[0]} {k[1]}" for k in (fr_t - fr_r))
    frames["extra"] = sorted(f"{k[0]} {k[1]}" for k in (fr_r - fr_t))

    items_r, items_t = _io_items(result), _io_items(truth)
    io_r, io_t = Counter(k for k, _ in items_r), Counter(k for k, _ in items_t)
    io = _pr(*_match(io_r, io_t))
    # 同じデータに触れているが操作が違う (キーの kind と段は同じで op だけ違う)
    data_r = Counter((k[0], k[2]) for k in (io_r - io_t).elements())
    data_t = Counter((k[0], k[2]) for k in (io_t - io_r).elements())
    io["op_mismatch"] = sum(min(n, data_t[k]) for k, n in data_r.items())
    io["missing"] = sorted(_fmt_io(k) for k in (io_t - io_r).elements())
    io["extra"] = sorted(_fmt_io(k) for k in (io_r - io_t).elements())
    # 一致した I/O の状態と理由 (同じキーの中では (status) と (status, reason) の多重集合で照合する。並び順に依らない)
    st_r = Counter((k, x["status"]) for k, x in items_r)
    st_t = Counter((k, x["status"]) for k, x in items_t)
    sr_r = Counter((k, x["status"], x.get("reason") if x["status"] == "unknown" else None) for k, x in items_r)
    sr_t = Counter((k, x["status"], x.get("reason") if x["status"] == "unknown" else None) for k, x in items_t)
    matched = sum(min(n, io_t[k]) for k, n in io_r.items())
    status_agree = sum(min(n, st_t[k]) for k, n in st_r.items())
    reason_agree = sum(min(n, sr_t[k]) for k, n in sr_r.items())
    io["status_agree"] = status_agree
    io["status_and_reason_agree"] = reason_agree
    io["matched"] = matched

    params = _pr(*_match(_param_keys(result), _param_keys(truth)))
    unknown_r = Counter(c.get("reason") for c in _claims(result) if c.get("status") == "unknown")
    unknown_t = Counter(c.get("reason") for c in _claims(truth) if c.get("status") == "unknown")
    out = {"frames": frames, "io": io, "parameters": params}
    for section in SECTIONS:
        out[section]["distinct"] = _pr(*_match_distinct(_section_keys(result, section), _section_keys(truth, section)))
    out["unknown_reasons"] = {"result": dict(sorted(unknown_r.items())), "truth": dict(sorted(unknown_t.items()))}
    return out


def _claims(result: dict):
    yield result.get("summary") or {}
    for f in result["callstack"]:
        for k in ("call", "summary"):
            if f.get(k):
                yield f[k]
        yield from f.get("parameters", [])
        yield from f.get("io", [])


def _fmt_io(k: tuple) -> str:
    kind, op, levels = k
    return f"{kind} {op} " + "/".join(v for _, v in levels)


def evaluate(results_path: Path, truth_path: Path) -> dict:
    results, truth = load_results(results_path), load_results(truth_path)
    both = sorted(set(results) & set(truth))
    unanalyzed, not_in_truth = sorted(set(truth) - set(results)), sorted(set(results) - set(truth))
    per_entry = {eid: compare_entry(results[eid], truth[eid]) for eid in both}
    totals = {}
    for section in SECTIONS:
        tp = sum(e[section]["tp"] for e in per_entry.values())
        fp = sum(e[section]["fp"] for e in per_entry.values()) + sum(_count(results[eid], section) for eid in not_in_truth)
        fn = sum(e[section]["fn"] for e in per_entry.values()) + sum(_count(truth[eid], section) for eid in unanalyzed)
        totals[section] = _pr(tp, fp, fn)
        # 重複を除いた合計: 入口ごとに重複を除いてから足す (未分析・正解に無い入口の項目も、重複を除いて分母に入れる)
        totals[section]["distinct"] = _pr(
            sum(e[section]["distinct"]["tp"] for e in per_entry.values()),
            sum(e[section]["distinct"]["fp"] for e in per_entry.values()) + sum(len(_section_keys(results[eid], section)) for eid in not_in_truth),
            sum(e[section]["distinct"]["fn"] for e in per_entry.values()) + sum(len(_section_keys(truth[eid], section)) for eid in unanalyzed))
    totals["io"]["op_mismatch"] = sum(e["io"]["op_mismatch"] for e in per_entry.values())
    totals["io"]["matched"] = sum(e["io"]["matched"] for e in per_entry.values())
    totals["io"]["status_agree"] = sum(e["io"]["status_agree"] for e in per_entry.values())
    totals["io"]["status_and_reason_agree"] = sum(e["io"]["status_and_reason_agree"] for e in per_entry.values())
    return {
        "entries": {"compared": len(both), "unanalyzed": unanalyzed, "not_in_truth": not_in_truth},
        "totals": totals,
        "per_entry": per_entry,
    }


def _count(result: dict, section: str) -> int:
    """入口 1 件の中の項目数 (未分析・正解に無い入口を分母に入れるため)。"""
    if section == "frames":
        return len(result["callstack"])
    if section == "io":
        return sum(len(f.get("io", [])) for f in result["callstack"])
    return sum(len(f.get("parameters", [])) for f in result["callstack"])


def _pct(x) -> str:
    return "-" if x is None else f"{x * 100:.0f}%"


def format_report(rep: dict) -> str:
    t = rep["totals"]
    e = rep["entries"]
    lines = [f"突合: 比べた入口 {e['compared']} 件 / 未分析 (正解にだけある) {len(e['unanalyzed'])} 件 / 正解に無い {len(e['not_in_truth'])} 件"
             + (" (未分析の入口の項目は「正解だけ」に、正解に無い入口の項目は「結果だけ」に含めている)" if e["unanalyzed"] or e["not_in_truth"] else ""), ""]
    lines.append("| 項目 | 一致 | 結果だけ | 正解だけ | 適合率 | 再現率 |")
    lines.append("|---|---|---|---|---|---|")
    for name, label in (("frames", "フレーム (layer + 定義ファイル)"), ("io", "I/O (種類 + 操作 + 段)"), ("parameters", "パラメータ (フレーム + 名前)")):
        x = t[name]
        lines.append(f"| {label} | {x['tp']} | {x['fp']} | {x['fn']} | {_pct(x['precision'])} | {_pct(x['recall'])} |")
    lines.append("")
    lines.append("重複を除いた比較 (同じ入口の中で同じキーは、何度書いてあっても 1 つに数える。同じ処理を書く回数の違いに左右されない):")
    lines.append("")
    lines.append("| 項目 | 一致 | 結果だけ | 正解だけ | 適合率 | 再現率 |")
    lines.append("|---|---|---|---|---|---|")
    for name, label in (("frames", "フレーム"), ("io", "I/O"), ("parameters", "パラメータ")):
        x = t[name]["distinct"]
        lines.append(f"| {label} | {x['tp']} | {x['fp']} | {x['fn']} | {_pct(x['precision'])} | {_pct(x['recall'])} |")
    io = t["io"]
    lines.append("")
    lines.append(f"一致した I/O {io['matched']} 件のうち、状態 (事実 / 解釈 / 不明) も一致 {io['status_agree']} 件、不明の理由まで一致 {io['status_and_reason_agree']} 件。"
                 f" 同じデータで操作だけ違うもの {io['op_mismatch']} 件")
    lines.append("")
    lines.append("| 入口 | フレーム 再現率 | I/O 適合率 | I/O 再現率 | I/O 適合率 (重複なし) | I/O 再現率 (重複なし) | 正解だけにある I/O |")
    lines.append("|---|---|---|---|---|---|---|")
    for eid, x in rep["per_entry"].items():
        miss = ", ".join(x["io"]["missing"][:3]) + (" …" if len(x["io"]["missing"]) > 3 else "")
        d = x["io"]["distinct"]
        lines.append(f"| {eid} | {_pct(x['frames']['recall'])} | {_pct(x['io']['precision'])} | {_pct(x['io']['recall'])} | {_pct(d['precision'])} | {_pct(d['recall'])} | {miss} |")
    if e["unanalyzed"]:
        lines.append("")
        lines.append("未分析: " + ", ".join(e["unanalyzed"]))
    if e["not_in_truth"]:
        lines.append("正解に無い: " + ", ".join(e["not_in_truth"]))
    return "\n".join(lines)


def main_cli(results: str, truth: str, as_json: bool) -> int:
    rp, tp = Path(results), Path(truth)
    for p in (rp, tp):
        if not p.exists():
            raise SystemExit(f"{p} が無い")
    rep = evaluate(rp, tp)
    print(json.dumps(rep, ensure_ascii=False, indent=2) if as_json else format_report(rep))
    return exit_code(rep)


def exit_code(rep: dict) -> int:
    """0 = 完全一致、1 = 不一致あり (結果だけ / 正解だけ / 状態の不一致 / 未分析 / 正解に無い)、2 = 比べられる入口が無い。"""
    if not rep["entries"]["compared"]:
        return 2
    t = rep["totals"]
    if rep["entries"]["unanalyzed"] or rep["entries"]["not_in_truth"]:
        return 1
    if any(t[s]["fp"] or t[s]["fn"] for s in ("frames", "io", "parameters")):
        return 1
    if t["io"]["status_and_reason_agree"] != t["io"]["matched"]:
        return 1
    return 0
