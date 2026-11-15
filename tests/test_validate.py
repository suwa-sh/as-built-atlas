import copy
from pathlib import Path

import pytest
import yaml

from abatlas.validate import validate_analysis_result, validate_entry_list, validate_profile

ROOT = Path(__file__).resolve().parent.parent
FIX = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def profile():
    return yaml.safe_load((ROOT / "profiles/batch-kestra/profile.yaml").read_text(encoding="utf-8"))


@pytest.fixture
def result():
    return yaml.safe_load((FIX / "result-housekeeping.yaml").read_text(encoding="utf-8"))


def test_profile_is_valid(profile):
    assert validate_profile(profile) == []


def test_fixture_result_is_valid(profile, result):
    assert validate_analysis_result(result, profile) == []


def test_fact_requires_evidence(profile, result):
    r = copy.deepcopy(result)
    del r["summary"]["evidence"]
    r["summary"]["status"] = "fact"
    findings = validate_analysis_result(r, profile)
    assert any("summary" in f and "evidence" in f for f in findings)


def test_unknown_requires_known_reason(profile, result):
    r = copy.deepcopy(result)
    r["callstack"][1]["io"][0]["reason"] = "because"
    findings = validate_analysis_result(r, profile)
    assert any("reason 'because'" in f for f in findings)


def test_unknown_without_reason_is_schema_error(profile, result):
    r = copy.deepcopy(result)
    del r["callstack"][1]["io"][0]["reason"]
    findings = validate_analysis_result(r, profile)
    assert findings and findings[0].startswith("schema:")


def test_layer_must_exist_in_profile(profile, result):
    r = copy.deepcopy(result)
    r["callstack"][1]["layer"] = "mainframe"
    findings = validate_analysis_result(r, profile)
    assert any("'mainframe' がプロファイルに無い" in f for f in findings)


def test_caller_must_resolve(profile, result):
    r = copy.deepcopy(result)
    r["callstack"][1]["caller"] = "nope"
    findings = validate_analysis_result(r, profile)
    assert any("caller 'nope' が存在しない" in f for f in findings)


def test_leaf_must_be_boundary_or_unknown(profile, result):
    r = copy.deepcopy(result)
    # notify_py は葉で program 層だが I/O を持つので許容される。I/O を消すと指摘される
    assert validate_analysis_result(r, profile) == []
    del r["callstack"][3]["io"]
    findings = validate_analysis_result(r, profile)
    assert any("callstack/notify_py: 終端なのに" in f for f in findings)


def test_resource_levels_must_match_kind(profile, result):
    r = copy.deepcopy(result)
    r["callstack"][4]["io"][0]["resource"]["levels"] = {"bucket": "x"}
    findings = validate_analysis_result(r, profile)
    assert any("段 'bucket'" in f for f in findings)


def test_entry_list_duplicate_ids(profile):
    el = {
        "format_version": 1,
        "target": {"repo": "x", "commit": "abc1234"},
        "profile": {"id": "batch-kestra", "version": "0.1.0"},
        "extractors": [],
        "entries": [
            {"id": "a", "path": "/a", "layer": "scheduler", "source": {"file": "f", "line": 1}, "status": "candidate"},
            {"id": "a", "path": "/a", "layer": "scheduler", "source": {"file": "f", "line": 1}, "status": "candidate"},
        ],
    }
    findings = validate_entry_list(el, profile)
    assert any("重複" in f for f in findings)


def test_review_schema_and_where(result):
    from abatlas.validate import validate_review

    review = {
        "format_version": 1, "entry_id": "daily.housekeeping", "reviewed_at": "2026-11-04T05:08:22+09:00",
        "machine_check": "ok",
        "findings": [{"kind": "evidence_mismatch", "severity": "medium", "where": "callstack/run_sh/summary",
                      "claim": "根拠の行は layers[].io: [...] の説明", "evidence": {"file": "scripts/housekeeping.sh", "line": 3}}],
    }
    assert validate_review(review, result) == []
    review["findings"][0]["where"] = "callstack/nope/summary"
    assert any("'nope' が結果に無い" in f for f in validate_review(review, result))
    review["findings"][0]["kind"] = "typo"
    assert validate_review(review, result)[0].startswith("schema:")


def test_old_field_names_are_rejected(profile, result):
    """前の項目名 (層の id の tier、層の並びの tiers、区分の zone、宣言の tier) の入力は、形式の検査で落ちる (docs/adr/0009)。"""
    from abatlas.declarations import check_declaration

    old = copy.deepcopy(result)
    old["entry"]["tier"] = old["entry"].pop("layer")
    assert any("layer" in f for f in validate_analysis_result(old, profile)) and any("tier" in f for f in validate_analysis_result(old, profile))
    old = copy.deepcopy(result)
    old["callstack"][0]["tier"] = old["callstack"][0].pop("layer")
    assert validate_analysis_result(old, profile)
    p = copy.deepcopy(profile)
    p["tiers"] = p.pop("layers")
    assert validate_profile(p)
    p = copy.deepcopy(profile)
    p["layers"][0]["zone"] = "x"
    assert validate_profile(p)
    assert any("origin" in x for x in check_declaration("m", {"tier": "core", "view": "stat", "level": "path", "keys": {"value": "n"}}, {"n"}))
