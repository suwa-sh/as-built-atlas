"""実 Git の 2 つの履歴から、変更理由と再利用を入口単位で確かめる。"""

import json
import shutil
import subprocess  # nosec B404 - test Git repositories

import pytest
import yaml

from abatlas import REPO_ROOT
from abatlas.cli import main
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


def test_code_map_before_discovery_uses_scoped_commit(histories, capsys):
    target, atlas, _ = histories
    (atlas / "analysis/entry-list.yaml").unlink()
    work_path = atlas / "analysis/work-definition.yaml"
    work = load_yaml(REPO_ROOT / "tests/fixtures/work-definition.yaml")
    work["target"].update(
        scope="flows/monthly", commit=git(target, "rev-parse", "HEAD")
    )
    work["analysis"]["entry_file_patterns"] = [r".+\.yaml"]
    work_path.write_text(yaml.safe_dump(work))
    (target / "flows/monthly/new.yaml").touch()
    (target / "flows/monthly/invoice_batch.yaml").unlink()
    args = ["code-map", str(atlas), "--json"]
    assert main(args) == 0
    output = capsys.readouterr().out
    report = json.loads(output)
    assert report["scope"] == "flows/monthly"
    assert report["target_commit"] == work["target"]["commit"]
    assert (
        report["files"]
        == report["expected_entry_files"]
        == [
            "custom_reports.yaml",
            "invoice_batch.yaml",
            "monthly_kpi.yaml",
            "purge_sessions.yaml",
        ]
    )
    assert main(args) == 0
    assert capsys.readouterr().out == output


def test_code_map_reconciles_files_before_approval(histories, capsys):
    from abatlas.batch import approve, preview

    _, atlas, baseline = histories
    ep = atlas / "analysis/entry-list.yaml"
    args = ["code-map", str(atlas), "--json", "--check"]
    assert main(args) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["missing_entry_files"] == []
    assert report["entries_by_file"]["flows/daily/db_snapshot.yaml"] == [SNAP]
    # 保存済みの一覧は全件揃っていても、抽出器から一部の定義が漏れる。
    saved = load_yaml(ep)
    saved["extractors"][0]["params"]["files"] = ["flows/daily/**/*.yaml"]
    ep.write_text(yaml.safe_dump(saved))
    before = ep.read_bytes()
    assert main(args) == 1
    missing = json.loads(capsys.readouterr().out)["missing_entry_files"]
    assert "flows/monthly/invoice_batch.yaml" in missing
    assert "flows/daily/db_snapshot.yaml" not in missing
    draft = {"assessment": "全体案の確認"}
    for revision in (None, baseline):
        with pytest.raises(SystemExit, match="flows/monthly/invoice_batch.yaml"):
            preview(atlas, revision, draft)
        with pytest.raises(SystemExit, match="flows/monthly/invoice_batch.yaml"):
            approve(atlas, revision, draft, "stale", "tester")
    assert ep.read_bytes() == before


def test_code_map_check_stops_when_extractor_cannot_start(histories, capsys):
    _, atlas, _ = histories
    ep = atlas / "analysis/entry-list.yaml"
    saved = load_yaml(ep)
    own = atlas / "analysis/own-extractor.sh"
    own.write_text("#!/bin/sh\n")
    own.chmod(0o644)  # 実行権限が無い
    layer = saved["extractors"][0]["layer"]
    saved["extractors"].append(
        {"name": "own", "run": own.name, "layer": layer, "params": {}}
    )
    ep.write_text(yaml.safe_dump(saved))
    assert main(["code-map", str(atlas), "--check"]) == 2
    err = capsys.readouterr().err
    assert "extractor 'own' を起動できない" in err and own.name in err


def test_extractor_search_failure_does_not_fall_back(tmp_path):
    import os

    from abatlas.enumerate import _command

    profile, own = tmp_path / "profile", tmp_path / "own"
    for base in (profile, own):
        (base / "bin").mkdir(parents=True)
        (base / "bin/extract.sh").write_text("#!/bin/sh\n")
    run = "bin/extract.sh"
    assert _command(run, profile, own) == [str((profile / run).resolve())]
    # プロファイルに無ければ、分析リポジトリ独自の抽出器を使う
    (profile / run).unlink()
    assert _command(run, profile, own) == [str((own / run).resolve())]
    # リンクの循環は「無い」ではない。同じ名前の独自の抽出器へ進まずに止める
    (profile / run).symlink_to(profile / "bin/loop")
    (profile / "bin/loop").symlink_to(profile / run)
    with pytest.raises(SystemExit, match=f"extractor '{run}' を探せない"):
        _command(run, profile, own)
    (profile / run).unlink()
    if os.name == "posix" and os.geteuid() != 0:  # root は、権限が無くても読める
        (profile / "bin").chmod(0o000)
        try:
            with pytest.raises(SystemExit, match="を探せない .*Permission denied"):
                _command(run, profile, own)
        finally:
            (profile / "bin").chmod(0o755)


def test_target_paths_use_slash_on_any_os(monkeypatch):
    from pathlib import PureWindowsPath
    from types import SimpleNamespace

    from abatlas import impact_evidence
    from abatlas.impact_evidence import references
    from abatlas.impact_git import TargetHistory

    # Windows では、範囲 (scope) のパスの区切りが「\」になる。Git が返すパスと規則は「/」
    windows = SimpleNamespace(scope=PureWindowsPath("apps\\web"))
    assert TargetHistory._in_scope(windows, "apps/web/flows/a.yaml") == "flows/a.yaml"
    here = SimpleNamespace(scope=PureWindowsPath("."))
    assert TargetHistory._in_scope(here, "flows/a.yaml") == "flows/a.yaml"
    assert list(references({"source": {"file": "./flows/a.yaml"}})) == ["flows/a.yaml"]
    # Windows で「\」区切りで書かれた根拠も、Git の一覧と比べられる
    monkeypatch.setattr(impact_evidence, "Path", PureWindowsPath)
    written = {"source": {"file": "flows\\a.yaml"}}
    assert list(references(written)) == ["flows/a.yaml"]


def test_paths_written_with_os_separator_still_match(monkeypatch):
    import abatlas
    from abatlas.code_map import reconcile_entries
    from abatlas.extractors import listed
    from abatlas.impact import _same_subject

    assert abatlas.slash_path("apps\\web", sep="\\") == "apps/web"
    assert abatlas.slash_path("a\\b", sep="/") == "a\\b"  # Linux と macOS では変えない

    original = abatlas.slash_path

    def windows(path):  # Windows の区切り文字で動かしたときの読み方
        return original(path, sep="\\")

    monkeypatch.setattr(abatlas, "slash_path", windows)
    monkeypatch.setattr(listed, "slash_path", windows)
    # 範囲を、前回と今回で違う区切りで書いても、同じ対象
    old, new = ({"repo": "r", "scope": s} for s in ("apps\\web", "apps/web"))
    assert _same_subject(old, new) and _same_subject({"repo": "r"}, {"repo": "r"})
    assert not _same_subject(old, {"repo": "r", "scope": "apps/api"})
    # 手で並べた入口の定義ファイルを「\」で書いても、定義ファイルとの照合に合う
    written = {
        "id": "a",
        "path": "/a",
        "reason": "手で足した",
        "source": {"file": "flows\\daily\\a.yaml", "line": 1},
    }
    record = listed._listed_record(written, "scheduler")
    assert record["source"]["file"] == "flows/daily/a.yaml"
    report = {"expected_entry_files": ["flows/daily/a.yaml"]}
    assert reconcile_entries(report, [record])["missing_entry_files"] == []
    # 区切り文字だけが違う入口は、同じ入口として扱う (承認や却下を引き継ぐ)
    from abatlas import enumerate as enumerating
    from abatlas.validate import _check_work_target

    monkeypatch.setattr(enumerating, "slash_path", windows)
    saved = {**record, "source": written["source"]}
    assert enumerating._target(saved) == enumerating._target(record)
    # 分析結果の検査でも、範囲の区切り文字の違いを指摘しない
    findings = []
    target = {"repo": "r", "commit": "c"}
    _check_work_target(
        {"target": {**target, "scope": "apps/web"}},
        {"target": {**target, "scope": "apps\\web"}},
        findings,
    )
    assert findings == []


def test_broken_run_setting_stops_with_message(tmp_path):
    from abatlas.enumerate import _command

    with pytest.raises(SystemExit, match="run が空"):
        _command("", None, tmp_path)
    with pytest.raises(SystemExit, match="を読めない"):
        _command("'own.sh", None, tmp_path)


def test_code_map_checks_each_pattern_and_supports_older_work(histories, capsys):
    _, atlas, baseline = histories
    path = atlas / "analysis/work-definition.yaml"
    work = load_yaml(path)
    args = ["code-map", str(atlas)]
    work["analysis"]["entry_file_patterns"].append("absent/.+")
    path.write_text(yaml.safe_dump(work))
    assert main(args) == 2 and "absent/.+" in capsys.readouterr().err
    work["analysis"]["entry_file_patterns"] = ["["]
    path.write_text(yaml.safe_dump(work))
    assert main(["validate", "work", str(path)]) == 1
    assert "entry_file_patterns" in capsys.readouterr().out
    assert main(args) == 2 and "entry_file_patterns" in capsys.readouterr().err
    del work["analysis"]["entry_file_patterns"]
    path.write_text(yaml.safe_dump(work))
    assert main(args) == 0 and "未設定" in capsys.readouterr().out
    assert main([*args, "--check"]) == 2 and "指定" in capsys.readouterr().err
    assert plan(atlas, baseline)[0]["entries"]


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


@pytest.mark.parametrize("advance_target", [True, False])
def test_unfinished_rule_change_is_still_pending_on_next_update(
    histories, advance_target
):
    target, atlas, base = histories
    work = atlas / "analysis"
    if advance_target:
        (target / "first.txt").write_text("B")
        set_version(work, snapshot(target))
    conventions = atlas / ".agents/memory/desired-state/analysis-conventions.md"
    conventions.parent.mkdir(parents=True)
    conventions.write_text("新しい分析規約")
    first, _ = plan(atlas, base)
    assert (
        next(r for r in first["entries"] if r["entry_id"] == SNAP)["action"]
        == "reanalyze"
    )
    middle = snapshot(atlas)  # 再分析を終えていない入口がある
    (target / "second.txt").write_text("C")
    set_version(work, snapshot(target))
    second, _ = plan(atlas, middle)
    assert (
        next(r for r in second["entries"] if r["entry_id"] == SNAP)["action"]
        == "reanalyze"
    )


def test_unavailable_analysis_conditions_require_reanalysis(histories):
    target, atlas, _ = histories
    assets = atlas / "analysis"
    work = assets / "work-definition.yaml"
    previous = work.read_text()
    work.write_text("format_version: 1\n")
    result = assets / "results" / f"{SNAP}.yaml"
    result.write_text(result.read_text() + "\n")
    snapshot(atlas)
    work.write_text(previous)
    middle = snapshot(atlas)
    shallow = atlas.parent / "shallow"
    git(atlas.parent, "clone", "--depth=1", atlas.as_uri(), str(shallow))
    (target / "next.txt").write_text("C")
    version = snapshot(target)
    for repo in (atlas, shallow):
        set_version(repo / "analysis", version)
        report, _ = plan(repo, middle)
        actions = {r["entry_id"]: r["action"] for r in report["entries"]}
        assert actions[SNAP] == "reanalyze"
        assert actions[SALE] == ("reuse" if repo == atlas else "reanalyze")


def test_whole_plan_approval(histories):
    from abatlas.batch import approve, preview, queue

    target, atlas, baseline = histories
    assets = atlas / "analysis"
    path = target / "jobs/settle_orders.py"
    path.write_text(path.read_text() + "\n# Comment\n")
    new = target / "flows/daily/retry.yaml"
    new.write_text(
        (target / "flows/daily/rotate_logs.yaml")
        .read_text()
        .replace("rotate_logs", "retry")
    )
    set_version(assets, snapshot(target))
    ep = assets / "entry-list.yaml"
    previous = ep.read_bytes()
    draft = {
        "assessment": "決済の注釈以外の呼び出しも確認",
        "questions": [{"entries": ["daily.retry"], "question": "本番で使うか"}],
    }
    report, _, _ = preview(atlas, baseline, draft)
    assert len(report["questions"]) == 1
    with pytest.raises(SystemExit, match="未解決"):
        approve(atlas, baseline, draft, report["plan_id"], "Maintainer")
    assert ep.read_bytes() == previous
    draft["questions"][0]["answer"] = "障害対応で使う"
    draft["decisions"] = [
        {"entries": ["daily.retry"], "action": "include", "reason": "本番手動起動"}
    ]
    with pytest.raises(SystemExit, match="計画 ID"):
        approve(atlas, baseline, draft, report["plan_id"], "Maintainer")
    report, _, _ = preview(atlas, baseline, draft)
    assert report["questions"] == []
    receipt = approve(atlas, baseline, draft, report["plan_id"], "Maintainer")
    jobs = queue(atlas, receipt["plan_id"])
    assert jobs == receipt["jobs"]
    assert (
        approve(atlas, baseline, draft, report["plan_id"], "Maintainer")["jobs"] == jobs
    )
    assert next(j for j in jobs if j["entry_id"] == CLOSE)["checkpoints"]
    actual = {j["entry_id"]: j["action"] for j in jobs}
    assert (
        actual["daily.retry"] == "analyze"
        and actual[SALE] == actual[CLOSE] == "reanalyze"
    )
    assert SNAP in receipt["reuse"] and SNAP not in actual
    assert (
        validate_result_file(
            assets / "results" / f"{SNAP}.yaml",
            work_path=assets / "work-definition.yaml",
        )
        == []
    )
    again, _ = plan(atlas, baseline)
    assert (
        next(r for r in again["entries"] if r["entry_id"] == SNAP)["action"] == "reused"
    )
    path.write_text("dirty")
    with pytest.raises(SystemExit, match="照合"):
        queue(atlas, receipt["plan_id"])


def test_first_batch(histories):
    from abatlas.batch import approve, preview, queue

    _, atlas, _ = histories
    assets = atlas / "analysis"
    (assets / "results").rename(assets / "saved-results")
    ep = assets / "entry-list.yaml"
    doc = load_yaml(ep)
    for entry in doc["entries"]:
        entry["status"] = "candidate"
    ep.write_text(yaml.safe_dump(doc, allow_unicode=True))
    draft = {
        "assessment": "定期起動を確認",
        "decisions": [
            {
                "entries": [e["id"] for e in doc["entries"] if e["id"] != SNAP],
                "action": "include",
                "reason": "本番定期起動",
            },
            {"entries": [SNAP], "action": "exclude", "reason": "検証専用"},
        ],
    }
    report, _, _ = preview(atlas, None, draft)
    receipt = approve(atlas, None, draft, report["plan_id"], "Maintainer")
    assert len(queue(atlas, receipt["plan_id"])) == 33
    assert {e["id"] for e in load_yaml(ep)["entries"] if e["status"] == "rejected"} == {
        SNAP
    }

    (assets / "results").mkdir()
    shutil.copy(assets / "saved-results" / f"{SALE}.yaml", assets / "results")
    conventions = atlas / ".agents/memory/desired-state/analysis-conventions.md"
    conventions.parent.mkdir(parents=True)
    conventions.write_text("今回から適用する規約")
    with pytest.raises(SystemExit, match="照合"):
        queue(atlas, receipt["plan_id"])
    revised, _, _ = preview(atlas, None, draft)
    assert (
        next(r for r in revised["entries"] if r["entry_id"] == SALE)["action"]
        == "reanalyze"
    )


def test_queue_requires_new_valid_result_and_review(histories):
    from abatlas.batch import approve, preview, queue

    _, atlas, base = histories
    assets = atlas / "analysis"
    draft = {
        "assessment": "運用条件を再確認",
        "decisions": [
            {
                "entries": [SNAP],
                "action": "reanalyze",
                "reason": "同じ版の手動起動条件を再確認",
            }
        ],
    }
    report, _, _ = preview(atlas, base, draft)
    token = report["plan_id"]
    approve(atlas, base, draft, token, "Maintainer")
    rp = assets / "results" / f"{SNAP}.yaml"
    stamp = "2026-11-22T09:00:00Z"
    result = load_yaml(rp)
    result["analyzer"]["reviewed"] = {"by": "reviewer", "at": stamp, "findings_open": 0}
    rp.write_text(yaml.safe_dump(result, allow_unicode=True))
    assert SNAP in {j["entry_id"] for j in queue(atlas, token)}
    revised, _, _ = preview(atlas, base, {"assessment": "入力の更新後に計画を見直した"})
    assert (
        next(r for r in revised["entries"] if r["entry_id"] == SNAP)["action"]
        == "reanalyze"
    )
    reviews = assets / "reviews"
    reviews.mkdir()
    review = {
        "format_version": 1,
        "entry_id": SNAP,
        "reviewed_at": stamp,
        "reviewer": "reviewer",
        "machine_check": "ng",
        "findings": [],
    }
    file = reviews / rp.name
    file.write_text(yaml.safe_dump(review))
    assert SNAP in {j["entry_id"] for j in queue(atlas, token)}
    review["machine_check"] = "ok"
    review["findings"] = [
        {
            "kind": "evidence_mismatch",
            "severity": "high",
            "where": "summary",
            "claim": "根拠が違う",
            "evidence": result["summary"]["evidence"][0],
            "suggestion": "根拠を見直す",
        }
    ]
    result["analyzer"]["reviewed"]["findings_open"] = 1
    rp.write_text(yaml.safe_dump(result, allow_unicode=True))
    file.write_text(yaml.safe_dump(review))
    assert SNAP in {j["entry_id"] for j in queue(atlas, token)}
    review["findings"][0]["resolved"] = True
    result["analyzer"]["reviewed"]["findings_open"] = 0
    rp.write_text(yaml.safe_dump(result, allow_unicode=True))
    file.write_text(yaml.safe_dump(review))
    assert SNAP not in {j["entry_id"] for j in queue(atlas, token)}
    revised, _, _ = preview(atlas, base, {"assessment": "レビュー済みの仕事を照合した"})
    assert (
        next(r for r in revised["entries"] if r["entry_id"] == SNAP)["action"]
        == "current"
    )
    for pending in (rp, file):
        completed = pending.read_bytes()
        pending.write_text("entry: [")
        assert SNAP in {j["entry_id"] for j in queue(atlas, token)}
        pending.write_bytes(completed)
    ep = assets / "entry-list.yaml"
    saved = load_yaml(ep)
    saved["approval"]["jobs"] = []
    ep.write_text(yaml.safe_dump(saved))
    with pytest.raises(SystemExit, match="確定後"):
        queue(atlas, token)


def test_approve_preserves_concurrent_entry_list_edit(histories, monkeypatch):
    from abatlas import batch

    _, atlas, base = histories
    file = atlas / "analysis/entry-list.yaml"
    draft = {"assessment": "全入口を確認"}
    report, _, _ = batch.preview(atlas, base, draft)
    original = batch.save_record

    def edited(path, record, **kwargs):
        doc = load_yaml(file)
        doc["entries"][0]["note"] = "承認中の別編集"
        file.write_text(yaml.safe_dump(doc, allow_unicode=True))
        original(path, record, **kwargs)

    monkeypatch.setattr(batch, "save_record", edited)
    with pytest.raises(SystemExit, match="作業中に入口一覧"):
        batch.approve(atlas, base, draft, report["plan_id"], "Maintainer")
    assert load_yaml(file)["entries"][0]["note"] == "承認中の別編集"
    assert "approval" not in load_yaml(file)
