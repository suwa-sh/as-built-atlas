"""分析結果の、版の間の差分。分析リポジトリの git の履歴にある前の結果と、いまの結果を比べる。

対象が変わった後に分析し直したとき、「どの入口の、何が変わったか」を出す。比べるのは、中身のキーで、根拠の行番号や説明の文は見ない
(対象の行がずれただけ、言い回しが変わっただけの違いを、差分に出さないため)。呼び出しの条件も、いつ起きるか (when) の変化だけを見て、
条件の文 (condition) は見ない (分析のたびに言い回しが変わる文なので)。業務のルールは、内容の文のほかに見分けるものが無いので、文で比べる
(言い回しが変わると、消えて足された、と出る)。同じキーのものが増減したときは、その個数の分だけ出す。決定論: 同じ入力なら同じ出力。
"""

from __future__ import annotations

import subprocess  # nosec B404 - executes subprocesses with argument lists
from collections import Counter
from pathlib import Path

import yaml

from . import ANALYSIS_DIR, analysis_dir
from .etl import build_rows
from .schemas import load_yaml, schema_errors

# 比べる観点 → (集計の入力の表, 1 件を表すキーの列, 人が読む呼び名)
ASPECTS = [
    ("entry", ("path", "layer"), "入口 (階層パスと層)"),
    (
        "frames",
        ("layer", "name", "source_file", "caller_name"),
        "処理の段 (最後は呼び出し元)",
    ),
    ("io", ("kind", "resource_path", "op"), "読み書き"),
    (
        "io_fields",
        ("resource_path", "name", "use_read", "use_write", "use_filter", "set_to"),
        "列",
    ),
    ("conditions", ("name", "call_when"), "呼び出しの条件"),
    ("links", ("kind", "target"), "つながり"),
    ("guards", ("kind", "value"), "権限の確認"),
    ("settings", ("name", "kind"), "設定"),
    ("rules", ("kind", "value"), "業務のルール"),
    ("tests", ("name", "kind"), "テスト"),
]


def _keys(result: dict) -> dict[str, Counter]:
    rows = build_rows({"entries": []}, [result])
    rows["entry"] = [
        {"path": result["entry"]["path"], "layer": result["entry"]["layer"]}
    ]
    names = {f["frame_id"]: f["name"] for f in rows["frames"]}
    for f in rows["frames"]:
        f["caller_name"] = names.get(
            f["caller_id"], ""
        )  # 呼び出し元は、id ではなく名前で比べる (id は、分析のたびに付け直される)
    rows["conditions"] = [
        f for f in rows["frames"] if f["call_when"] in ("conditional", "on_failure")
    ]
    return {
        name: Counter(tuple(str(r[c]) for c in cols) for r in rows[name])
        for name, cols, _ in ASPECTS
    }  # 個数も持つ (同じ読み書きが 1 か所増えた、を出すため)


def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(["git", "-C", str(repo), *args], capture_output=True)  # nosec B603, B607 - Git CLI with separate revision and path arguments
    if out.returncode != 0:
        raise SystemExit(
            f"diff: git {' '.join(args)} が失敗した: {out.stderr.decode('utf-8', 'replace').strip()}"
        )
    return out.stdout.decode("utf-8")


def results_at(repo: Path, rev: str) -> dict[str, dict]:
    """git の版 rev にある分析結果 (入口の id → 結果)。形式に合わないファイルは、読まずに止める。"""
    tree = _git(
        repo, "rev-parse", "--verify", "--end-of-options", f"{rev}^{{tree}}"
    ).strip()
    base = f"{ANALYSIS_DIR}/results/"
    names = [
        n
        for n in _git(
            repo, "ls-tree", "-r", "--name-only", tree, "--", base
        ).splitlines()
        if n.endswith(".yaml")
    ]
    out = {}
    for n in names:
        doc = yaml.safe_load(
            _git(repo, "show", f"{tree}:./{n}")
        )  # ./ = 分析リポジトリのルートから (git のルートが上にあっても読める)
        errs = schema_errors("analysis-result", doc)
        if errs:
            raise SystemExit(f"diff: {rev} の {n} が、いまの形式で読めない: {errs[0]}")
        out[doc["entry"]["id"]] = doc
    return out


def results_now(repo: Path) -> dict[str, dict]:
    out = {}
    for p in sorted((analysis_dir(repo) / "results").glob("*.yaml")):
        doc = load_yaml(p)
        errs = schema_errors("analysis-result", doc)
        if errs:
            raise SystemExit(f"diff: {p.name} が、形式に合わない: {errs[0]}")
        out[doc["entry"]["id"]] = doc
    return out


def diff_results(old: dict[str, dict], new: dict[str, dict]) -> list[dict]:
    """入口ごとの差分。変わっていない入口は出さない。"""
    out = []
    for eid in sorted(set(old) | set(new)):
        if eid not in old:
            out.append(
                {
                    "entry_id": eid,
                    "change": "added",
                    "path": new[eid]["entry"]["path"],
                    "aspects": [],
                }
            )
            continue
        if eid not in new:
            out.append(
                {
                    "entry_id": eid,
                    "change": "removed",
                    "path": old[eid]["entry"]["path"],
                    "aspects": [],
                }
            )
            continue
        a, b = _keys(old[eid]), _keys(new[eid])
        aspects = []
        for name, _, label in ASPECTS:
            added, removed = (
                sorted((b[name] - a[name]).elements()),
                sorted((a[name] - b[name]).elements()),
            )
            if added or removed:
                aspects.append(
                    {"aspect": name, "label": label, "added": added, "removed": removed}
                )
        if aspects:
            out.append(
                {
                    "entry_id": eid,
                    "change": "changed",
                    "path": new[eid]["entry"]["path"],
                    "aspects": aspects,
                    "commit": (
                        old[eid]["target"]["commit"],
                        new[eid]["target"]["commit"],
                    ),
                    "skill": (
                        old[eid]["analyzer"]["skill_version"],
                        new[eid]["analyzer"]["skill_version"],
                    ),
                }
            )
    return out


def _append_change_header(lines, c):
    notes = []
    if c["commit"][0] != c["commit"][1]:
        notes.append(f"対象のコミット {c['commit'][0][:7]} → {c['commit'][1][:7]}")
    if c["skill"][0] != c["skill"][1]:
        notes.append(
            f"分析の skill {c['skill'][0]} → {c['skill'][1]} (観点が増えた分も、差分に出る)"
        )
    lines.append(f"~ {c['path']}" + (f"  ({'、'.join(notes)})" if notes else ""))


def format_diff(changes: list[dict], rev: str) -> str:
    """人が読む形。1 行目は数。入口ごとに、観点 → 足されたもの (+) と消えたもの (-)。"""
    n = {
        k: sum(1 for c in changes if c["change"] == k)
        for k in ("added", "removed", "changed")
    }
    lines = [
        f"diff: {rev} と比べて、分析結果が変わった入口 {n['changed']} 件、足された入口 {n['added']} 件、消えた入口 {n['removed']} 件"
    ]
    for c in changes:
        if c["change"] != "changed":
            lines.append(
                f"{'+' if c['change'] == 'added' else '-'} {c['path']}  (分析結果が{'足された' if c['change'] == 'added' else '消えた'})"
            )
            continue
        _append_change_header(lines, c)
        for a in c["aspects"]:
            lines.append(f"    {a['label']}: +{len(a['added'])} -{len(a['removed'])}")
            lines += [f"      + {' | '.join(k)}" for k in a["added"]] + [
                f"      - {' | '.join(k)}" for k in a["removed"]
            ]
    return "\n".join(lines)


def diff_repo(repo: Path, rev: str) -> str:
    repo = repo.resolve()
    return format_diff(diff_results(results_at(repo, rev), results_now(repo)), rev)
