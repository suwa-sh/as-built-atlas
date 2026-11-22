"""実 Git の 2 つの履歴から、変更理由と再利用を入口単位で確かめる。"""

import shutil
import subprocess  # nosec B404 - test Git repositories

import pytest
import yaml

from abatlas import REPO_ROOT
from abatlas.impact import confirm, format_plan, plan
from abatlas.schemas import load_yaml, schema_errors
from abatlas.validate import validate_result_file

EXAMPLES = REPO_ROOT / "examples"
SNAP = "daily.db_snapshot"
SALE = "daily.sales.settle_orders"
CLOSE = "daily.close_day"


def git(path, *args):
    return subprocess.check_output(  # nosec B603, B607 - isolated test Git repository
        [
            "git",
            "-C",
            str(path),
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "user.name=fixture",
            "-c",
            "user.email=fixture@atlas.example",
            "-c",
            "commit.gpgSign=false",
            *args,
        ],
        text=True,
    ).strip()


def snapshot(path):
    git(path, "add", ".")
    git(path, "commit", "-qm", "snapshot")
    return git(path, "rev-parse", "HEAD")


def set_version(assets, sha):
    for name in ("work-definition", "entry-list"):
        path = assets / f"{name}.yaml"
        doc = yaml.safe_load(path.read_text())
        doc["target"]["commit"] = sha
        path.write_text(yaml.safe_dump(doc, allow_unicode=True))


@pytest.fixture
def histories(tmp_path):
    target = tmp_path / "kotori-books"
    atlas = tmp_path / "atlas"
    assets = atlas / "analysis"
    shutil.copytree(EXAMPLES / "kotori-books", target)
    (target / ".gitignore").write_text("generated/\n")
    git(target, "init", "-q")
    old = snapshot(target)
    assets.mkdir(parents=True)
    source = EXAMPLES / "kotori-books-atlas" / "analysis"
    (assets / "results").mkdir()
    for eid in (SNAP, SALE, CLOSE):
        name = f"{eid}.yaml"
        doc = yaml.safe_load((source / "results" / name).read_text())
        doc["target"]["commit"] = old
        (assets / "results" / name).write_text(yaml.safe_dump(doc, allow_unicode=True))
    for name in ("work-definition", "entry-list"):
        shutil.copy(source / f"{name}.yaml", assets)
    shutil.copytree(
        REPO_ROOT / "profiles" / "batch-kestra",
        atlas / ".abatlas/profiles/batch-kestra",
    )
    set_version(assets, old)
    git(atlas, "init", "-q")
    return target, atlas, snapshot(atlas)


def test_plan_and_reuse(histories):
    target, atlas, baseline = histories
    assets = atlas / "analysis"
    path = target / "jobs/settle_orders.py"
    with path.open("a") as f:
        f.write("\n# New behavior\n")
    set_version(assets, snapshot(target))
    report, ctx = plan(atlas, baseline)
    rows = {r["entry_id"]: r for r in report["entries"]}
    assert {e for e, r in rows.items() if r["action"] == "reanalyze"} == {SALE, CLOSE}
    assert rows[CLOSE]["files"] == ["jobs/settle_orders.py"]
    assert rows[CLOSE]["checkpoints"][0]["route"][0] == CLOSE
    assert "再分析 2 件" in format_plan(report)
    assert rows[SNAP]["action"] == "reuse"
    rp = assets / "results" / f"{SNAP}.yaml"
    work = assets / "work-definition.yaml"
    assert any("target/commit" in e for e in validate_result_file(rp, work_path=work))
    with pytest.raises(SystemExit, match="計画"):
        confirm(report, ctx, SNAP, "stale", "確認済み", "tester")
    with pytest.raises(SystemExit, match="候補"):
        confirm(report, ctx, SALE, report["plan_id"], "確認済み", "tester")
    (target / "generated").mkdir()
    (target / "generated" / "cache").write_text("ignored")
    confirm(report, ctx, SNAP, report["plan_id"], "決済を通らない", "tester")
    assert validate_result_file(rp, work_path=work) == []
    assert yaml.safe_load(rp.read_text())["target"]["commit"] != ctx.history.tip
    again, _ = plan(atlas, baseline)
    assert again["plan_id"] == report["plan_id"]
    assert (
        next(r for r in again["entries"] if r["entry_id"] == SNAP)["action"] == "reused"
    )
    path.write_text(path.read_text() + "# dirty\n")
    assert any("target/commit" in e for e in validate_result_file(rp, work_path=work))
    git(target, "restore", "jobs/settle_orders.py")
    doc = yaml.safe_load(rp.read_text())
    doc["summary"]["value"] = "別の結果"
    rp.write_text(yaml.safe_dump(doc, allow_unicode=True))
    assert any("target/commit" in e for e in validate_result_file(rp, work_path=work))


def test_enumerates_fixed_tree_and_reports_renames(histories):
    target, atlas, baseline = histories
    asset = target / "flows/daily/rotate_logs.yaml"
    new = target / "flows/daily/rotated.yaml"
    new.write_text(asset.read_text().replace("rotate_logs", "rotated"))
    asset.unlink()
    set_version(atlas / "analysis", snapshot(target))
    new.unlink()  # 作業コピーの編集を固定ツリーの列挙へ混ぜない
    report, _ = plan(atlas, baseline)
    actions = {r["entry_id"]: r["action"] for r in report["entries"]}
    assert actions["daily.rotated"] == "approve"
    assert actions["daily.rotate_logs"] == "retire"
    assert not report["enumerated"]
    assert set(next(iter(report["changes"].values()))) == {
        "flows/daily/rotate_logs.yaml",
        "flows/daily/rotated.yaml",
    }


def test_second_update_compares_directly_with_analysis(histories):
    target, atlas, base = histories
    work = atlas / "analysis"
    (target / "first.txt").write_text("B")
    set_version(work, snapshot(target))
    first, ctx = plan(atlas, base)
    confirm(first, ctx, SNAP, first["plan_id"], "追加文書のみ", "tester")
    middle = snapshot(atlas)
    (target / "second.txt").write_text("C")
    set_version(work, snapshot(target))
    second, ctx = plan(atlas, middle)
    row = next(r for r in second["entries"] if r["entry_id"] == SNAP)
    assert row["action"] == "reuse"
    assert second["changes"][row["analyzed_commit"]] == ["first.txt", "second.txt"]
    confirm(second, ctx, SNAP, second["plan_id"], "両方が文書", "tester")
    (atlas / ".agents/memory/desired-state").mkdir(parents=True)
    (atlas / ".agents/memory/desired-state/analysis-conventions.md").write_text(
        "分析規約を変更"
    )
    assert validate_result_file(
        work / "results" / f"{SNAP}.yaml", work_path=work / "work-definition.yaml"
    )


def test_reuse_record_requires_the_confirmation():
    record = load_yaml(REPO_ROOT / "tests/fixtures/reuse-housekeeping.yaml")
    assert not schema_errors("reuse", record)
    del record["reason"]
    assert schema_errors("reuse", record)
