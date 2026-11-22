"""外部レビュー round 2 で受け入れた指摘の回帰テスト。"""

import copy
from pathlib import Path

import pytest
import yaml

from abatlas.etl import run_etl
from abatlas.validate import (
    _resolve_scope,
    validate_analysis_result,
    validate_profile,
    validate_result_file,
)

ROOT = Path(__file__).resolve().parent.parent
FIX = Path(__file__).resolve().parent / "fixtures"
PROFILE = ROOT / "profiles/batch-kestra/profile.yaml"


@pytest.fixture
def profile():
    return yaml.safe_load(PROFILE.read_text(encoding="utf-8"))


@pytest.fixture
def result():
    return yaml.safe_load(
        (FIX / "result-housekeeping.yaml").read_text(encoding="utf-8")
    )


def _scope(tmp_path: Path) -> Path:
    scope = tmp_path / "clone" / "tools"
    for rel in [
        "flows/daily/housekeeping.yaml",
        "flows/lib/notify.yaml",
        "scripts/housekeeping.sh",
        "notify.py",
    ]:
        p = scope / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            "\n".join(f"line{i}" for i in range(1, 70)) + "\n", encoding="utf-8"
        )
    return scope


def test_work_and_result_target_must_match(tmp_path: Path, result):
    scope = _scope(tmp_path)
    work = {
        "format_version": 1,
        "target": {
            "repo": "DIFFERENT",
            "clone_path": str(scope.parent),
            "scope": "tools",
            "commit": "deadbeef",
        },
        "profile": {"id": "batch-kestra"},
    }
    (tmp_path / "work.yaml").write_text(yaml.safe_dump(work), encoding="utf-8")
    r = copy.deepcopy(result)
    r["target"]["scope"] = "tools"
    (tmp_path / "r.yaml").write_text(
        yaml.safe_dump(r, allow_unicode=True), encoding="utf-8"
    )
    findings = validate_result_file(
        tmp_path / "r.yaml", PROFILE, tmp_path / "work.yaml"
    )
    assert any(f.startswith("target/repo") for f in findings)
    assert any(f.startswith("target/commit") for f in findings)


def test_entry_source_line_bound(tmp_path: Path, profile, result):
    scope = _scope(tmp_path)
    r = copy.deepcopy(result)
    r["entry"]["source"]["line"] = 999
    findings = validate_analysis_result(r, profile, scope)
    assert any(f.startswith("entry/source") and "行数" in f for f in findings)


def test_unknown_parameter_allows_leaf(profile, result):
    r = copy.deepcopy(result)
    leaf = r["callstack"][3]  # notify_py
    del leaf["io"]
    leaf["parameters"] = [
        {"name": "webhook", "status": "unknown", "reason": "not_traceable_in_repo"}
    ]
    assert not any(
        "notify_py: 終端なのに" in f for f in validate_analysis_result(r, profile)
    )


def test_scope_cannot_escape_clone(tmp_path: Path):
    with pytest.raises(SystemExit):
        _resolve_scope({"clone_path": str(tmp_path), "scope": "../outside"}, tmp_path)


def test_profile_layer_io_is_required(profile):
    p = copy.deepcopy(profile)
    del p["layers"][0]["io"]
    assert any("io" in f for f in validate_profile(p))


def test_etl_refuses_invalid_result(tmp_path: Path, result):
    repo = tmp_path / "analysis"
    (repo / "results").mkdir(parents=True)
    el = {
        "format_version": 1,
        "target": {"repo": "x", "commit": "abc1234"},
        "profile": {"id": "batch-kestra", "version": "0.1.0"},
        "extractors": [],
        "entries": [],
    }
    (repo / "entry-list.yaml").write_text(yaml.safe_dump(el), encoding="utf-8")
    r = copy.deepcopy(result)
    del r["summary"]["evidence"]
    r["summary"]["status"] = "fact"
    (repo / "results/bad.yaml").write_text(
        yaml.safe_dump(r, allow_unicode=True), encoding="utf-8"
    )
    with pytest.raises(SystemExit):
        run_etl(repo, tmp_path / "seeds")
    assert not (tmp_path / "seeds").exists()


# ---- 段階 3 のレビュー round 2 (2026-11-04)


def test_result_file_name_rule_is_single_source():
    from abatlas import file_name_collisions, result_file_name

    assert result_file_name("daily/housekeeping") == "daily__housekeeping.yaml"
    assert result_file_name("daily.housekeeping") == "daily.housekeeping.yaml"
    assert file_name_collisions(["a/b", "a__b", "c"]) == {"a__b.yaml": ["a/b", "a__b"]}


def test_entry_list_rejects_colliding_file_names():
    from abatlas.validate import validate_entry_list

    el = {
        "format_version": 1,
        "target": {"repo": "x", "commit": "0" * 40},
        "profile": {"id": "p", "version": "1"},
        "extractors": [],
        "enumerated_at": "2026-11-04T00:00:00+09:00",
        "entries": [
            {
                "id": i,
                "path": "/" + i,
                "layer": "scheduler",
                "status": "candidate",
                "source": {"file": "f", "line": 1},
                "extractor": "e",
            }
            for i in ("a/b", "a__b")
        ],
    }
    findings = validate_entry_list(el, None)
    assert any("同じ結果ファイル名" in f and "a__b.yaml" in f for f in findings)


# ---- 段階 3 のレビュー round 3 (2026-11-04、外部再レビュー未実施)


def test_file_name_collision_is_case_insensitive():
    from abatlas import file_name_collisions

    got = file_name_collisions(["Daily", "daily", "x"])
    assert list(got.values()) == [["Daily", "daily"]]


def test_build_swaps_duckdb_atomically(tmp_path, monkeypatch):
    """build は .building に作ってから入れ替える。失敗時は既存の DB を壊さない。"""
    from abatlas import build, duckdb_path

    repo = tmp_path / "r"
    (repo / "analysis" / "data" / "dbt" / "target").mkdir(parents=True)
    db = duckdb_path(repo)
    db.write_bytes(b"old")
    monkeypatch.setattr(
        build, "render_dbt_project", lambda *a, **k: repo / "analysis" / "data" / "dbt"
    )
    monkeypatch.setattr(build, "run_etl", lambda *a, **k: {})
    monkeypatch.setattr(
        build, "_profile", lambda *a, **k: {}
    )  # ETL の入力の検査に渡すだけ (ここでは ETL を差し替えている)
    monkeypatch.setattr(
        build, "oss_copy_outdated", lambda *a, **k: None
    )  # 作業定義を置いていないので、配布物のコピーの確認も差し替える

    class R:
        returncode = 1
        stdout = "boom"
        stderr = ""

    monkeypatch.setattr(build.subprocess, "run", lambda *a, **k: R())
    import pytest

    with pytest.raises(SystemExit, match="dbt build が失敗"):
        build.build_repo(repo)
    assert (
        db.read_bytes() == b"old" and not db.with_name(db.name + ".building").exists()
    )
