"""入口の採否と差分の作業を一度に承認する。"""

from collections import Counter

import yaml

from . import analysis_dir, result_file_name
from .build import PROFILE_FILE, profile_dir
from .impact import ENTRIES_FILE, WORK_FILE, _valid, plan_inputs, worklist
from .impact_git import commit
from .reuse import ReuseContext, digest, save_record
from .schemas import load_yaml, schema_errors
from .validate import validate_entry_list, validate_result_at, validate_review


def _initial_action(status, existing):
    if status == "approved":
        return "reanalyze" if existing else "analyze"
    if status == "rejected":
        return "retire" if existing else "rejected"
    return "approve"


def _initial(repo, work, entries):
    assets = analysis_dir(repo)
    existing = {}
    for path in (assets / "results").glob("*.yaml"):
        result = _valid("analysis-result", load_yaml(path))
        eid = result["entry"]["id"]
        if path.name != result_file_name(eid):
            raise SystemExit(f"batch: {path.name} の入口 ID と名前を合わせてください")
        existing[eid] = result["entry"]
    ctx = ReuseContext(assets, work, entries, profile_dir(repo) / PROFILE_FILE)
    prior = entries.get("approval", {})
    if existing and (
        prior.get("target_commit") != ctx.history.tip
        or prior.get("baseline") is not None
    ):
        raise SystemExit(
            "batch: 既存の結果があります。--from で前回の分析コミットを指定してください"
        )
    rows = []
    for eid, entry in sorted((existing | ctx.entries).items()):
        status = ctx.entries.get(eid, {}).get("status", "rejected")
        action = _initial_action(status, eid in existing)
        rows.append(
            {
                "entry_id": eid,
                "path": entry["path"],
                "action": action,
                "reason": "初回作業を再計画。保存済みの結果を今回の条件で読み直す"
                if eid in existing
                else "初回の入口一覧",
            }
        )
    return {"entries": rows, "changes": {}, "baseline": None}, ctx


def _decisions(draft, entries):
    indexed = {e["id"]: e for e in entries}
    decisions = {}
    for group in draft.get("decisions", []):
        for eid in group["entries"]:
            if eid in decisions or eid not in indexed:
                raise SystemExit(
                    f"batch: decisions の {eid} が重複または列挙外です。下書きを直してください"
                )
            decisions[eid] = group
            if group["action"] in ("include", "exclude"):
                indexed[eid]["status"] = (
                    "approved" if group["action"] == "include" else "rejected"
                )
    return decisions


def _conditions(ctx, entries):
    return digest([ctx.work, ctx.conditions, entries["profile"], entries["entries"]])


def _asset_digest(assets, directory, eid):
    path = assets / directory / result_file_name(eid)
    return digest(load_yaml(path)) if path.is_file() else None


def _carry_unfinished(ctx, entries, rows):
    if ctx.approval.get("target_commit") != ctx.history.tip:
        return
    same_conditions = ctx.approval["conditions_digest"] == _conditions(ctx, entries)
    profile = profile_dir(ctx.assets.parent) / PROFILE_FILE
    for row in rows:
        job = ctx.jobs.get(row["entry_id"])
        if row["action"] == "current" and job:
            if not same_conditions or not _finished(ctx, job, profile):
                row.update(
                    action="reanalyze",
                    reason="前の承認の条件またはレビューの完了を再確認",
                )


def _tasks(report, decisions):
    for row in report["entries"]:
        group = decisions.get(row["entry_id"])
        if group is None:
            continue
        if group["action"] == "reanalyze":
            if row["action"] in ("approve", "rejected", "retire"):
                raise SystemExit(
                    f"batch: {row['entry_id']} は分析対象外です。入口の採否を確認してください"
                )
            if row["action"] != "analyze":
                row["action"] = "reanalyze"
                row.pop("binding", None)
        row["reason"] = group["reason"]


def _unresolved(draft, rows):
    ids = {r["entry_id"] for r in rows}
    questions = []
    for q in draft.get("questions", []):
        if not set(q["entries"]) <= ids:
            raise SystemExit(
                "batch: questions に列挙外の入口があります。入口 ID を確かめてください"
            )
        if not q.get("answer"):
            questions.append(q)
    covered = {eid for q in questions for eid in q["entries"]}
    pending = [
        r["entry_id"]
        for r in rows
        if r["action"] == "approve" and r["entry_id"] not in covered
    ]
    if pending:
        questions.append(
            {
                "entries": pending,
                "question": "未整理の候補です。AIが根拠を調べて採否案を埋めてください",
            }
        )
    return questions


def preview(repo, revision, draft):
    repo = repo.resolve()
    _valid("batch-draft", draft)
    work, saved, entries = plan_inputs(repo)
    decisions = _decisions(draft, entries["entries"])
    report, ctx = (
        worklist(repo, revision, work, saved, entries)
        if revision
        else _initial(repo, work, entries)
    )
    rows = report["entries"]
    _carry_unfinished(ctx, entries, rows)
    _tasks(report, decisions)
    for row in rows:
        row["previous_result"] = _asset_digest(ctx.assets, "results", row["entry_id"])
        row["previous_review"] = _asset_digest(ctx.assets, "reviews", row["entry_id"])
    questions = _unresolved(draft, rows)
    token = digest(
        [
            report["baseline"],
            ctx.history.tip,
            saved,
            _conditions(ctx, entries),
            report["changes"],
            rows,
            draft,
        ]
    )
    result = {
        "plan_id": token,
        "baseline": report["baseline"],
        "target_commit": ctx.history.tip,
        "counts": dict(Counter(r["action"] for r in rows)),
        "questions": questions,
        "assessment": draft["assessment"],
        "entry_list_digest": digest(saved),
        "changes": report["changes"],
        "entries": rows,
    }
    return result, ctx, entries


def _receipt(report, ctx, entries, draft, by):
    jobs = []
    reused = {}
    for row in report["entries"]:
        eid = row["entry_id"]
        if row["action"] in ("analyze", "reanalyze", "retire"):
            jobs.append({k: v for k, v in row.items() if k not in ("path", "binding")})
        elif row["action"] in ("reuse", "reused"):
            record = {
                "format_version": 1,
                **row["binding"],
                "baseline": report["baseline"],
                "reason": draft["assessment"],
                "confirmed_by": by,
            }
            path = ctx.assets / "results" / result_file_name(eid)
            if not ctx.verified(record, load_yaml(path)):
                raise SystemExit(
                    f"batch: {eid} の根拠または分析条件が変わりました。案を作り直してください"
                )
            reused[eid] = record
    return {
        "plan_id": report["plan_id"],
        "baseline": report["baseline"],
        "by": by,
        "target_commit": ctx.history.tip,
        "conditions_digest": _conditions(ctx, entries),
        "draft": draft,
        "jobs": jobs,
        "reuse": reused,
    }


def _already_approved(repo, revision, draft, token, by):
    saved = load_yaml(analysis_dir(repo) / ENTRIES_FILE)
    approval = saved.get("approval", {})
    if approval.get("plan_id") != token:
        return None
    baseline = commit(repo, revision) if revision else None
    if (
        approval["by"] != by.strip()
        or approval["draft"] != draft
        or approval["baseline"] != baseline
    ):
        raise SystemExit("batch: 指定した承認と下書き・確認者・基準コミットが違います")
    return {**approval, "jobs": queue(repo, token)}


def approve(repo, revision, draft, token, by):
    # 同時に届いた承認は、先の確定後の入力で再照合する。
    import fcntl
    import os

    assets = analysis_dir(repo.resolve())
    fd = os.open(assets, os.O_RDONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        previous = _already_approved(repo, revision, draft, token, by)
        if previous is not None:
            return previous
        report, ctx, entries = preview(repo, revision, draft)
        if not by.strip() or report["questions"] or report["plan_id"] != token:
            raise SystemExit(
                "batch: 確認者・未解決の質問・計画 ID を確認し、最新の案で全体を承認してください"
            )
        if not ctx.history.checkout_matches():
            raise SystemExit(
                "batch: 対象を指定コミットの clean checkout に合わせてください"
            )
        receipt = _receipt(report, ctx, entries, draft, by.strip())
        entries["approval"] = {**receipt, "seal": digest(receipt)}
        problems = validate_entry_list(entries, ctx.profile)
        if problems:
            raise SystemExit("batch: " + "\n".join(problems))
        save_record(
            assets / ENTRIES_FILE, entries, expected=report["entry_list_digest"]
        )
        return entries["approval"]
    finally:
        os.close(fd)


def _read_job_output(path):
    # 並行分析で書き込み途中の結果は、次の queue で再確認する。
    try:
        return load_yaml(path)
    except (FileNotFoundError, UnicodeDecodeError, yaml.YAMLError):
        return None


def _reviewed(path, result, previous):
    review = _read_job_output(path)
    if digest(review) == previous or validate_review(review, result):
        return False
    stamp = result["analyzer"].get("reviewed", {})
    return (
        review["machine_check"] == "ok"
        and bool(stamp.get("by"))
        and "findings_open" in stamp
        and stamp.get("by") == review.get("reviewer")
        and stamp.get("at") == review["reviewed_at"]
        and all(
            f["severity"] != "high" or f.get("resolved") for f in review["findings"]
        )
    )


def _finished(ctx, job, profile):
    eid = job["entry_id"]
    name = result_file_name(eid)
    path = ctx.assets / "results" / name
    review = ctx.assets / "reviews" / name
    if job["action"] == "retire":
        return not any(
            (ctx.assets / part / name).exists()
            for part in ("results", "reviews", "reuse")
        )
    result = _read_job_output(path)
    if (
        schema_errors("analysis-result", result)
        or digest(result) == job["previous_result"]
        or result["entry"]["id"] != eid
    ):
        return False
    if result.get("target", {}).get("commit") != ctx.work["target"]["commit"]:
        return False
    return (
        not validate_result_at(result, path, profile, ctx.assets / WORK_FILE)
        and ctx.compatible(result)
        and _reviewed(review, result, job["previous_review"])
    )


def queue(repo, token):
    repo = repo.resolve()
    work, saved, entries = plan_inputs(repo)
    profile = profile_dir(repo) / PROFILE_FILE
    ctx = ReuseContext(analysis_dir(repo), work, entries, profile)
    approval = saved.get("approval", {})
    if (
        approval.get("plan_id") != token
        or approval.get("conditions_digest") != _conditions(ctx, entries)
        or saved["entries"] != entries["entries"]
        or not ctx.history.checkout_matches()
    ):
        raise SystemExit(
            "batch: 承認時の入口・対象・規約と照合できません。最新の案を確認してください"
        )
    for eid, record in approval["reuse"].items():
        path = ctx.assets / "results" / result_file_name(eid)
        if not path.is_file() or not ctx.verified(record, load_yaml(path)):
            raise SystemExit(
                f"batch: 再利用した {eid} の入力が変わりました。案を更新してください"
            )
    return [j for j in approval["jobs"] if not _finished(ctx, j, profile)]
