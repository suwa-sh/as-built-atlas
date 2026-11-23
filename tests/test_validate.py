import copy
from pathlib import Path

import pytest
import yaml

from abatlas.validate import (
    validate_analysis_result,
    validate_entry_list,
    validate_profile,
)

ROOT = Path(__file__).resolve().parent.parent
FIX = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def profile():
    return yaml.safe_load(
        (ROOT / "profiles/batch-kestra/profile.yaml").read_text(encoding="utf-8")
    )


@pytest.fixture
def result():
    return yaml.safe_load(
        (FIX / "result-housekeeping.yaml").read_text(encoding="utf-8")
    )


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
            {
                "id": "a",
                "path": "/a",
                "layer": "scheduler",
                "source": {"file": "f", "line": 1},
                "status": "candidate",
            },
            {
                "id": "a",
                "path": "/a",
                "layer": "scheduler",
                "source": {"file": "f", "line": 1},
                "status": "candidate",
            },
        ],
    }
    findings = validate_entry_list(el, profile)
    assert any("重複" in f for f in findings)


def test_an_approval_with_mixed_key_types_is_reported_not_crashed_on(profile):
    # 承認の記録の項目名に、文字列と true が混ざる (形式の検査は通る)。封の計算で項目名を並べられない
    record = yaml.safe_load((FIX / "reuse-housekeeping.yaml").read_text("utf-8"))
    el = {
        "format_version": 1,
        "target": {"repo": "x", "commit": "abc1234"},
        "profile": {"id": "batch-kestra", "version": "0.1.0"},
        "extractors": [],
        "entries": [],
        "approval": {
            "plan_id": "a" * 64,
            "by": "Maintainer",
            "target_commit": "0" * 40,
            "baseline": None,
            "conditions_digest": "a" * 64,
            "draft": yaml.safe_load((FIX / "batch-draft.yaml").read_text("utf-8")),
            "jobs": [],
            "reuse": {"daily.housekeeping": record, True: record},
            "seal": "a" * 64,
        },
    }
    findings = validate_entry_list(el, profile)
    assert findings == [
        "entry-list: approval の確定後に内容が変わりました。承認時の版を復元してください"
    ]


def test_review_schema_and_where(result):
    from abatlas.validate import validate_review

    review = {
        "format_version": 1,
        "entry_id": "daily.housekeeping",
        "reviewed_at": "2026-11-04T05:08:22+09:00",
        "machine_check": "ok",
        "findings": [
            {
                "kind": "evidence_mismatch",
                "severity": "medium",
                "where": "callstack/run_sh/summary",
                "claim": "根拠の行は layers[].io: [...] の説明",
                "evidence": {"file": "scripts/housekeeping.sh", "line": 3},
            }
        ],
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
    assert any("layer" in f for f in validate_analysis_result(old, profile)) and any(
        "tier" in f for f in validate_analysis_result(old, profile)
    )
    old = copy.deepcopy(result)
    old["callstack"][0]["tier"] = old["callstack"][0].pop("layer")
    assert validate_analysis_result(old, profile)
    p = copy.deepcopy(profile)
    p["tiers"] = p.pop("layers")
    assert validate_profile(p)
    p = copy.deepcopy(profile)
    p["layers"][0]["zone"] = "x"
    assert validate_profile(p)
    assert any(
        "origin" in x
        for x in check_declaration(
            "m",
            {"tier": "core", "view": "stat", "level": "path", "keys": {"value": "n"}},
            {"n"},
        )
    )


def test_a_leaf_with_business_rules_is_allowed(profile, result):
    """読み書きも外部の呼び出しもしない、判定や計算だけの関数は、業務のルールを書けば終端になれる。"""
    r = copy.deepcopy(result)
    leaf = {
        "id": "decide",
        "layer": "program",
        "kind": "function",
        "name": "decide_exit_code",
        "source": {"file": "scripts/housekeeping.sh", "line": 1},
        "caller": "run_sh",
        "call": {
            "status": "fact",
            "when": "always",
            "evidence": [{"file": "scripts/housekeeping.sh", "line": 1}],
        },
    }
    r["callstack"].append(leaf)
    assert any(
        "decide" in f and "終端" in f for f in validate_analysis_result(r, profile)
    )
    leaf["rules"] = [
        {
            "kind": "decision",
            "value": "1 つでも失敗があれば 1 で終わる",
            "status": "fact",
            "evidence": [{"file": "scripts/housekeeping.sh", "line": 1}],
        }
    ]
    assert validate_analysis_result(r, profile) == []


def test_a_resolved_finding_may_point_at_a_removed_frame(result):
    """「このフレームは要らない」という指摘に従ってフレームを消すと、指摘の指す先が無くなる。直した指摘なら、検査に通す。"""
    from abatlas.validate import validate_review

    finding = {
        "kind": "evidence_mismatch",
        "severity": "high",
        "where": "callstack/removed_frame/summary",
        "claim": "この画面では動かない",
    }
    review = {
        "format_version": 1,
        "entry_id": result["entry"]["id"],
        "reviewed_at": "2026-11-04T12:00:00+09:00",
        "machine_check": "ok",
        "findings": [finding],
    }
    assert any("removed_frame" in f for f in validate_review(review, result))
    finding["resolved"] = True
    assert validate_review(review, result) == []


def test_the_open_findings_count_must_match_the_review(result):
    """結果に記録した「直っていない指摘の数」は、レビューのファイルから数えた値と合う (画面と集計が、結果の値を使う)。"""
    from abatlas.validate import validate_review

    r = copy.deepcopy(result)
    finding = {
        "kind": "evidence_mismatch",
        "severity": "low",
        "where": "summary",
        "claim": "根拠の行が足りない",
    }
    review = {
        "format_version": 1,
        "entry_id": r["entry"]["id"],
        "reviewed_at": "2026-11-04T12:00:00+09:00",
        "machine_check": "ok",
        "findings": [finding],
    }
    r["analyzer"]["reviewed"] = {
        "by": "x",
        "at": "2026-11-04T12:00:00+09:00",
        "findings_open": 0,
    }
    assert any("findings_open" in f for f in validate_review(review, r))
    finding["resolved"] = True
    assert validate_review(review, r) == []


def test_the_work_definition_may_name_models_for_subagents():
    from abatlas.validate import validate_work_definition

    work = {
        "format_version": 1,
        "target": {"repo": "x", "commit": "abcdef0"},
        "profile": {"id": "batch-kestra"},
        "analysis": {"models": {"analyze": "m-a", "review": "m-r"}},
    }
    assert validate_work_definition(work) == []
    work["analysis"]["models"]["summarize"] = "m-s"
    assert validate_work_definition(work)


def test_a_leaf_that_embeds_another_entry_is_allowed(profile, result):
    """別の入口にした部品を描くフレームは、読み書きが無くても終端になれる (続きは、行き先の入口の結果にある)。"""
    r = copy.deepcopy(result)
    ev = [{"file": "scripts/housekeeping.sh", "line": 1}]
    leaf = {
        "id": "renderer",
        "layer": "program",
        "kind": "function",
        "name": "render_part",
        "source": {"file": "scripts/housekeeping.sh", "line": 1},
        "caller": "run_sh",
        "call": {"status": "fact", "when": "always", "evidence": ev},
    }
    r["callstack"].append(leaf)
    leaf["links"] = [
        {
            "kind": "navigate",
            "target": "other",
            "entry_id": "other",
            "status": "fact",
            "evidence": ev,
        }
    ]
    assert any(
        "renderer" in f and "終端" in f for f in validate_analysis_result(r, profile)
    )
    leaf["links"] = [
        {"kind": "embed", "target": "Chart", "status": "interpretation", "evidence": ev}
    ]  # 行き先の入口が無い
    problems = validate_analysis_result(r, profile)
    assert any("renderer" in f and "終端" in f for f in problems) and any(
        "embed" in f and "entry_id" in f for f in problems
    )
    leaf["links"] = [
        {
            "kind": "embed",
            "target": "Chart",
            "entry_id": "part_p.registry.Chart",
            "status": "interpretation",
            "evidence": ev,
        }
    ]
    assert any(
        "renderer" in f and "終端" in f for f in validate_analysis_result(r, profile)
    )  # 入口の一覧を渡さない検査では、終端の根拠にしない
    assert any(
        "renderer" in f and "入口の一覧に無い" in f
        for f in validate_analysis_result(r, profile, entry_ids={"other"})
    )  # 一覧に無い行き先
    assert (
        validate_analysis_result(r, profile, entry_ids={"part_p.registry.Chart"}) == []
    )
    me = r["entry"]["id"]
    leaf["links"] = [
        {
            "kind": "embed",
            "target": "Self",
            "entry_id": me,
            "status": "interpretation",
            "evidence": ev,
        }
    ]  # 自分自身を指しても、続きはどこにも無い
    problems = validate_analysis_result(r, profile, entry_ids={me})
    assert any("renderer" in f and "終端" in f for f in problems) and any(
        "この入口自身" in f for f in problems
    )
    leaf["links"] = [
        {
            "kind": "trigger",
            "target": "child.yml",
            "entry_id": "child",
            "status": "fact",
            "evidence": ev,
        }
    ]  # 別の入口を起動するだけの段
    assert validate_analysis_result(r, profile, entry_ids={"child"}) == []
