"""再利用の確定と検査で共有する入力。旧結果の来歴は変更しない。"""

import hashlib
import json
import os
import re
from pathlib import Path
from tempfile import NamedTemporaryFile

import yaml

from . import REPO_ROOT, result_file_name
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
            "scope": self.work["target"].get("scope", "."),
            "analyzed_commit": result["target"]["commit"],
            "effective_commit": self.history.tip,
            "result_digest": digest(result),
            "conditions_digest": digest([self.conditions, self.entries.get(eid)]),
        }

    def eligible_files(self, result):
        files = set(references(result))
        changed = self.history.changes(result["target"]["commit"])
        return files.issubset(self.history.files()) and files.isdisjoint(changed)

    def verified(self, record, result):
        if schema_errors("reuse", record):
            return False
        eid = result["entry"]["id"]
        binding = self.binding(result)
        if any(record[key] != value for key, value in binding.items()):
            return False
        target = result["target"]
        if (
            target["repo"] != binding["repo"]
            or target.get("scope", ".") != binding["scope"]
        ):
            return False
        if self.entries.get(eid, {}).get("status") != "approved" or not self.compatible(
            result
        ):
            return False
        if self._checked_checkout is None:
            self._checked_checkout = self.history.checkout_matches()
        return self._checked_checkout and self.eligible_files(result)


def save_record(path, record):
    path.parent.mkdir(exist_ok=True)
    with NamedTemporaryFile(
        mode="w", dir=path.parent, delete=False, encoding="utf-8"
    ) as temp:
        try:
            yaml.safe_dump(record, temp, allow_unicode=True, sort_keys=False)
            temp.flush()
            os.replace(temp.name, path)
        finally:
            Path(temp.name).unlink(missing_ok=True)


def verified_result(assets, work, result, profile_path=None, contexts=None):
    path = record_path(assets, result["entry"]["id"])
    if not path.is_file():
        return False
    from .build import profile_dir

    if contexts is None:
        contexts = {}
    if "context" not in contexts:
        pp = profile_path or profile_dir(assets.parent) / "profile.yaml"
        entries = load_yaml(assets / "entry-list.yaml")
        target = entries["target"]
        if any(
            target.get(k, ".") != work["target"].get(k, ".")
            for k in ("repo", "scope", "commit")
        ):
            return False
        contexts["context"] = ReuseContext(assets, work, entries, pp)
    return contexts["context"].verified(load_yaml(path), result)
