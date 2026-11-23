"""再利用の確定と検査で共有する入力。旧結果の来歴は変更しない。"""

import hashlib
import json
import os
import re
from pathlib import Path
from tempfile import NamedTemporaryFile

import yaml

from . import REPO_ROOT, result_file_name, scope_of, slash_path
from .impact_evidence import references
from .impact_git import TargetHistory
from .schemas import load_yaml, schema_errors

CONVENTIONS = ".agents/memory/desired-state/analysis-conventions.md"
SKILL = ".agents/skills/abatlas-analyze-entry/SKILL.md"


def digest(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()
    ).hexdigest()


def record_path(assets, eid):
    assets = assets.resolve()
    path = assets / "reuse" / result_file_name(eid)
    if (
        not path.resolve().is_relative_to(assets.resolve())
        or path.resolve() != path.absolute()
    ):
        raise SystemExit("reuse: 分析資産への通常のパスを指定してください")
    return path


def _skill_series(assets):
    path = assets.parent / SKILL
    text = (path if path.is_file() else REPO_ROOT / SKILL).read_text()
    match = re.search(r"^- skill_version: (\d+\.\d+)\.\d+", text, re.M)
    if not match:
        raise SystemExit("impact: 分析 skill の skill_version を読めません")
    return match[1]


class ReuseContext:
    def __init__(self, assets, work, entries, profile_path):
        self.assets = assets
        self.approval = entries.get("approval", {})
        if self.approval:
            from .validate import approval_errors

            problems = schema_errors(
                "batch-approval", self.approval
            ) or approval_errors(self.approval)
            if problems:
                raise SystemExit(problems[0])
        self.jobs = {j["entry_id"]: j for j in self.approval.get("jobs", [])}
        self.work = work
        self.entries = {e["id"]: e for e in entries["entries"]}
        self.profile = load_yaml(profile_path)
        self.history = TargetHistory(work["target"], assets)
        self.skill = _skill_series(assets)
        self.conditions = digest(
            {
                "tests": bool(work.get("analysis", {}).get("tests")),
                "profile": self.profile,
                "skill": self.skill,
                "extractors": entries["extractors"],
                "rules": [
                    p.read_text() if p.is_file() else None
                    for p in (
                        profile_path.with_name("context.md"),
                        assets.parent / CONVENTIONS,
                    )
                ],
                # 昇格した部品やリンク先の承認も分析の境界を変えうる。
                "boundaries": [
                    (
                        eid,
                        e["status"],
                        e["layer"],
                        e["path"],
                        e["source"]["file"],
                        e.get("within", []),
                    )
                    for eid, e in sorted(self.entries.items())
                ],
            }
        )
        self._checked_checkout = None

    def compatible(self, result):
        analyzer = result["analyzer"]
        return (
            analyzer["profile"]
            == {"id": self.profile["id"], "version": self.profile["version"]}
            and ".".join(analyzer["skill_version"].split(".")[:2]) == self.skill
            and bool(analyzer.get("tests"))
            == bool(self.work.get("analysis", {}).get("tests"))
        )

    def binding(self, result):
        eid = result["entry"]["id"]
        return {
            "entry_id": eid,
            "repo": self.work["target"]["repo"],
            "scope": scope_of(self.work["target"]),
            "analyzed_commit": result["target"]["commit"],
            "effective_commit": self.history.tip,
            "result_digest": digest(result),
            "conditions_digest": digest([self.conditions, self.entries.get(eid)]),
        }

    def eligible_files(self, result):
        files = set(references(result))
        changed = self.history.changes(result["target"]["commit"])
        return files.issubset(self.history.files()) and files.isdisjoint(changed)

    def pending(self, result):
        if self.approval.get("target_commit") != self.history.tip:
            return None
        eid = result["entry"]["id"]
        job = self.jobs.get(eid)
        if job and job["previous_result"] == digest(result):
            return job
        return None

    def confirmed(self, result):
        eid = result["entry"]["id"]
        if self.pending(result):
            return False
        record = self.approval.get("reuse", {}).get(eid)
        if record and self.verified(record, result):
            return True
        path = record_path(self.assets, eid)
        return path.is_file() and self.verified(load_yaml(path), result)

    def verified(self, record, result):
        if schema_errors("reuse", record):
            return False
        eid = result["entry"]["id"]
        binding = self.binding(result)
        recorded = {**record, "scope": slash_path(record["scope"])}
        if any(recorded[key] != value for key, value in binding.items()):
            return False
        target = result["target"]
        if target["repo"] != binding["repo"] or scope_of(target) != binding["scope"]:
            return False
        if self.entries.get(eid, {}).get("status") != "approved" or not self.compatible(
            result
        ):
            return False
        if self._checked_checkout is None:
            self._checked_checkout = self.history.checkout_matches()
        return self._checked_checkout and self.eligible_files(result)


def save_record(path, record, *, expected=None):
    path.parent.mkdir(exist_ok=True)
    with NamedTemporaryFile(
        mode="w", dir=path.parent, delete=False, encoding="utf-8"
    ) as temp:
        try:
            yaml.safe_dump(record, temp, allow_unicode=True, sort_keys=False)
            temp.flush()
            if path.is_file():
                os.fchmod(temp.fileno(), path.stat().st_mode & 0o777)
            if expected is not None and (
                not path.is_file() or digest(load_yaml(path)) != expected
            ):
                raise SystemExit(
                    "batch: 作業中に入口一覧が変わりました。最新の案を確認してください"
                )
            os.replace(temp.name, path)
        finally:
            Path(temp.name).unlink(missing_ok=True)


def _target_key(target):
    return (target.get("repo", "."), scope_of(target), target.get("commit", "."))


def verified_result(assets, work, result, profile_path=None, contexts=None):
    path = record_path(assets, result["entry"]["id"])
    from .build import profile_dir

    if contexts is None:
        contexts = {}
    if "entries" not in contexts:
        ep = assets / "entry-list.yaml"
        contexts["entries"] = load_yaml(ep) if ep.is_file() else {}
    entries = contexts["entries"]
    if not path.is_file() and not entries.get("approval", {}).get("reuse"):
        return False
    if "context" not in contexts:
        pp = profile_path or profile_dir(assets.parent) / "profile.yaml"
        target = entries["target"]
        if _target_key(target) != _target_key(work["target"]):
            return False
        contexts["context"] = ReuseContext(assets, work, entries, pp)
    return contexts["context"].confirmed(result)
