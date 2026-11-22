"""対象 Git の差分を、分析する入口と確認理由に変換する。"""

from collections import defaultdict
from pathlib import Path

import yaml

from . import analysis_dir, result_file_name
from .build import PROFILE_FILE, profile_dir
from .diff import _git, results_at
from .enumerate import enumerate_entries
from .impact_evidence import checkpoints, linked_entries, references
from .impact_git import TargetHistory, commit
from .reuse import CONVENTIONS, ReuseContext, digest, record_path, save_record
from .schemas import load_yaml, schema_errors

WORK_FILE = "work-definition.yaml"

ENTRIES_FILE = "entry-list.yaml"

LABEL = {
    "analyze": "追加分析",
    "reanalyze": "再分析",
    "approve": "承認待ち",
    "retire": "廃止確認",
    "rejected": "却下済み",
    "reuse": "再利用候補",
    "reused": "再利用確認済み",
    "current": "分析済み",
}


def _valid(name, doc):
    problems = schema_errors(name, doc)
    if problems:
        raise SystemExit(f"impact: {name} の形式を確認してください: {problems[0]}")
    return doc


def _at(repo, rev, filename, schema):
    return _valid(
        schema, yaml.safe_load(_git(repo, "show", f"{rev}:./analysis/{filename}"))
    )


def _same_subject(a, b):
    return (a["repo"], a.get("scope", ".")) == (b["repo"], b.get("scope", "."))


def _rules_changed(repo, baseline, pp, old_work, work, before, after):
    if (
        old_work["profile"] != work["profile"]
        or before["extractors"] != after["extractors"]
    ):
        return True
    paths = [CONVENTIONS]
    if pp.is_relative_to(repo):
        paths.extend(str(x.relative_to(repo)) for x in (pp, pp.with_name("context.md")))
    return bool(
        _git(repo, "diff", "--name-only", baseline, "--", *paths)
        or _git(repo, "ls-files", "--others", "--exclude-standard", "--", *paths)
    )


def _links_changed(result, before, after):
    related = linked_entries(result) | set(
        after[result["entry"]["id"]].get("within", [])
    )
    return any(before.get(eid) != after.get(eid) for eid in related)


def _row(entry, action, reason, **fields):
    return {
        "entry_id": entry["id"],
        "path": entry["path"],
        "action": action,
        "reason": reason,
        **fields,
    }


def _existing(ctx, before, entry, result, rules_changed):
    eid = entry["id"]
    if not _same_subject(ctx.work["target"], result["target"]):
        return _row(entry, "reanalyze", "前回の結果の対象リポジトリまたは範囲が違う")
    old_sha = result["target"]["commit"]
    changed = ctx.history.changes(old_sha)
    hits = set(references(result)).intersection(changed)
    if hits and not rules_changed and ctx.compatible(result):
        return _row(
            entry,
            "reanalyze",
            "変更ファイルが前回の定義場所または根拠にある",
            analyzed_commit=old_sha,
            files=sorted(hits),
            checkpoints=checkpoints(result, hits),
        )
    if rules_changed or not ctx.compatible(result):
        return _row(
            entry,
            "reanalyze",
            "分析規約・抽出設定・プロファイル・分析 skill・テストの選択を確認",
        )
    if entry != before.get(eid) or _links_changed(result, before, ctx.entries):
        return _row(
            entry, "reanalyze", "入口の定義・承認・包む入口・リンク先が変わった"
        )
    if not ctx.eligible_files(result):
        return _row(
            entry, "reanalyze", "指定した版に通常ファイルとして照合できない根拠がある"
        )
    return _row(
        entry,
        "reuse",
        "前回の根拠と分析条件が一致。未記録の影響を確認",
        analyzed_commit=old_sha,
    )


def _updated_result(ctx, entry, current):
    # 新しく分析した結果だけを既完了にできる。以前の版の編集は再利用しない。
    target = current["target"]
    if (
        _same_subject(target, ctx.work["target"])
        and target["commit"] == ctx.work["target"]["commit"]
        and ctx.compatible(current)
    ):
        return _row(entry, "current", "今回の版の分析結果がある")
    return _row(entry, "reanalyze", "現在の結果が基準の分析コミットと違う")


def _decision(ctx, before, entry, old, current, rules_changed):
    if entry["status"] == "rejected":
        return _row(
            entry, "retire" if current else "rejected", "入口の承認状態が rejected"
        )
    if entry["status"] == "candidate":
        return _row(entry, "approve", "入口を追加または再承認してから分析")
    if current is None:
        return _row(entry, "analyze", "承認済みで現在の結果が無い")
    if pending := ctx.pending(current):
        return _row(
            entry,
            "reanalyze",
            pending["reason"],
            **{
                k: pending[k]
                for k in ("files", "analyzed_commit", "checkpoints")
                if k in pending
            },
        )
    if old != current:
        return _updated_result(ctx, entry, current)
    row = _existing(ctx, before, entry, old, rules_changed)
    if (
        row["action"] == "reuse"
        and old["target"]["commit"] == ctx.work["target"]["commit"]
    ):
        return _row(entry, "current", "今回の版の分析結果がある")
    return row


def _planned_entry(ctx, eid, entry, before, result, changed_rules):
    rp = ctx.assets / "results" / result_file_name(eid)
    current = _valid("analysis-result", load_yaml(rp)) if rp.is_file() else None
    if current and current["entry"]["id"] != eid:
        raise SystemExit(f"impact: {rp.name} の entry.id が {eid} と違います")
    row = _decision(ctx, before, entry, result, current, changed_rules)
    if row["action"] == "reuse":
        row["binding"] = ctx.binding(current)
        if ctx.confirmed(current):
            row["action"] = "reused"
            row["reason"] = "今回の版で再利用を確認済み"
    return row


def _saved_conditions(repo, rev, ctx, current_list):
    # 過去版の形式・ファイルが読めない入口は、現在の形式で再分析する。
    files = [f"analysis/{name}" for name in (WORK_FILE, ENTRIES_FILE)]
    present = _git(repo, "ls-tree", "-z", "--name-only", rev, "--", *files).split("\0")
    if not set(files).issubset(present):
        return {}, True, None
    try:
        work, prior = (
            yaml.safe_load(_git(repo, "show", f"{rev}:./{path}")) for path in files
        )
    except yaml.YAMLError:
        return {}, True, None
    if schema_errors("work-definition", work) or schema_errors("entry-list", prior):
        return {}, True, None
    changed = _rules_changed(
        repo,
        rev,
        profile_dir(repo) / PROFILE_FILE,
        work,
        ctx.work,
        prior,
        current_list,
    )
    return {e["id"]: e for e in prior["entries"]}, changed, work["target"]


def _analysis_conditions(repo, baseline, eid, revs, ctx, current_list, source_sha):
    """結果を保存した分析コミットまで戻って、後から変えた規約と承認を比べる。"""
    filename = result_file_name(eid)
    rev = _git(
        repo, "log", "-1", "--format=%H", baseline, "--", f"analysis/results/{filename}"
    ).strip()
    if rev not in revs:
        revs[rev] = _saved_conditions(repo, rev, ctx, current_list)
    entries, changed, target = revs[rev]
    if (
        not target
        or target["commit"] != source_sha
        or not _same_subject(target, ctx.work["target"])
    ):
        return {}, True
    return entries, changed


def _worklist(repo, baseline, ctx, old_work, before, changed_rules, current_list):
    results = results_at(repo, baseline, strict_names=True)
    changes = {
        old_work["target"]["commit"]: ctx.history.changes(old_work["target"]["commit"])
    }
    rows = []
    # shallow 境界では、それ以前に保存された結果もここで作成されたように見える。
    boundary_file = Path(
        _git(
            repo, "rev-parse", "--path-format=absolute", "--git-path", "shallow"
        ).strip()
    )
    boundaries = (
        boundary_file.read_text().splitlines() if boundary_file.is_file() else []
    )
    revisions = {rev: ({}, True, None) for rev in boundaries}
    for eid, entry in sorted(ctx.entries.items()):
        entry_before, entry_rules_changed = before, changed_rules
        result = results.get(eid)
        if result and _same_subject(ctx.work["target"], result["target"]):
            sha = result["target"]["commit"]
            changes[sha] = ctx.history.changes(sha)
            entry_before, earlier_change = _analysis_conditions(
                repo, baseline, eid, revisions, ctx, current_list, sha
            )
            entry_rules_changed = changed_rules or earlier_change
        row = _planned_entry(ctx, eid, entry, entry_before, result, entry_rules_changed)
        rows.append(row)
    for eid in sorted((before.keys() | results.keys()) - ctx.entries.keys()):
        rows.append(
            _row(
                before.get(eid) or results[eid]["entry"],
                "retire",
                "今回の全件列挙で入口が消失。旧結果とリンク元を確認",
            )
        )
    return rows, changes


def plan_inputs(repo):
    assets = analysis_dir(repo)
    work = _valid("work-definition", load_yaml(assets / WORK_FILE))
    path = assets / ENTRIES_FILE
    saved = _valid("entry-list", load_yaml(path))
    if saved["target"]["commit"] != work["target"]["commit"] or not _same_subject(
        saved["target"], work["target"]
    ):
        raise SystemExit(
            "impact: 入口一覧の target.repo/scope/commit を作業定義に合わせてください"
        )
    pp = profile_dir(repo) / PROFILE_FILE

    history = TargetHistory(work["target"], assets)
    with history.snapshot() as scope:
        entries = enumerate_entries(path, pp, write=False, scope_override=scope)
    return work, saved, entries


def plan(repo, revision):
    repo = repo.resolve()
    work, saved, entries = plan_inputs(repo)
    return worklist(repo, revision, work, saved, entries)


def worklist(repo, revision, work, saved, entries):
    baseline = commit(repo, revision)
    old_work = _at(repo, baseline, WORK_FILE, "work-definition")
    old_list = _at(repo, baseline, ENTRIES_FILE, "entry-list")
    if not _same_subject(old_work["target"], work["target"]):
        raise SystemExit(
            "impact: 前回と今回の repo/scope が違います。全件を分析してください"
        )
    pp = profile_dir(repo) / PROFILE_FILE
    ctx = ReuseContext(analysis_dir(repo), work, entries, pp)
    before = {e["id"]: e for e in old_list["entries"]}
    changed_rules = _rules_changed(
        repo, baseline, pp, old_work, work, old_list, entries
    )
    rows, changes = _worklist(
        repo, baseline, ctx, old_work, before, changed_rules, entries
    )
    report = {
        "baseline": baseline,
        "target_commit": ctx.history.tip,
        "changes": changes,
        "entries": rows,
        "enumerated": saved["entries"] == entries["entries"],
    }
    # 再利用の確定自体は別の入口の確認を無効にしない。
    report["plan_id"] = digest(
        [
            baseline,
            ctx.history.tip,
            ctx.conditions,
            changes,
            [
                {**row, "action": "reuse", "reason": ""} if "binding" in row else row
                for row in rows
            ],
        ]
    )
    return report, ctx


def confirm(report, ctx, eid, plan_id, reason, by):
    if not reason.strip() or not by.strip():
        raise SystemExit("reuse: 判断の理由と確認者を指定してください")
    if report["plan_id"] != plan_id or not report["enumerated"]:
        raise SystemExit(
            "reuse: 計画が変わったか入口一覧が未更新です。列挙・承認後に impact をやり直してください"
        )
    row = next((r for r in report["entries"] if r["entry_id"] == eid), {})
    if row.get("action") not in ("reuse", "reused"):
        raise SystemExit(f"reuse: {eid} は今回の再利用候補にありません")
    record = {
        "format_version": 1,
        **row["binding"],
        "baseline": report["baseline"],
        "reason": reason.strip(),
        "confirmed_by": by.strip(),
    }
    rp = ctx.assets / "results" / result_file_name(eid)
    if not ctx.verified(record, load_yaml(rp)):
        raise SystemExit(
            "reuse: 対象を指定の版で clean checkout し、結果と根拠を確認して impact をやり直してください"
        )
    save_record(record_path(ctx.assets, eid), record)


def format_plan(report):
    lines = [f"対象 {report['target_commit']}  計画 {report['plan_id']}"]
    groups = defaultdict(list)
    for row in report["entries"]:
        groups[row["action"]].append(row)
    for action, members in groups.items():
        lines.append(f"\n{LABEL[action]} {len(members)} 件")
        common = defaultdict(list)
        for row in members:
            common[
                (
                    row["reason"],
                    row.get("analyzed_commit", ""),
                    tuple(row.get("files", [])),
                )
            ].append(row)
        for (reason, sha, files), rows in common.items():
            lines.append(
                f"  {reason} {'、'.join(files)} ({len(rows)} 件) {sha}".rstrip()
            )
            for row in rows:
                lines.append(f"    {row['entry_id']}  {row['path']}")
                for point in row.get("checkpoints", []):
                    src = point["source"]
                    lines.append(
                        f"      {' → '.join(point['route'])}  {src['file']}:{src['line']}"
                    )
    lines.append("\n未記録の影響・新規入口の確認対象 (対象コミット間の全変更)")
    for old, files in report["changes"].items():
        lines.append(f"  {old}: {', '.join(files) or '差分なし'}")
    return "\n".join(lines)
