"""2026-11-04 の外部レビュー (round 1) で受け入れた指摘の回帰テスト。"""

import copy
import json
from pathlib import Path

import pytest
import yaml

from abatlas.enumerate import _command, enumerate_entries
from abatlas.extractors.structured_query import extract
from abatlas.validate import validate_analysis_result, validate_result_file

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


# --- 指摘 1: call に余分な項目を許さない
def test_call_is_closed(profile, result):
    r = copy.deepcopy(result)
    r["callstack"][1]["call"]["typo"] = "bad"
    findings = validate_analysis_result(r, profile)
    assert findings and findings[0].startswith("schema:") and "call" in findings[0]


# --- 指摘 2: 入口フレームの層、到達可能性、循環
def test_root_layer_must_match_entry_layer(profile, result):
    r = copy.deepcopy(result)
    r["callstack"][0]["layer"] = "shell"
    findings = validate_analysis_result(r, profile)
    assert any("entry.layer" in f for f in findings)


def test_cycle_is_unreachable(profile, result):
    r = copy.deepcopy(result)
    # run_sh ⇄ psycopg の循環 (入口から切り離す)
    r["callstack"][1]["caller"] = "psycopg"
    r["callstack"][1]["call"] = {"status": "unknown", "reason": "not_analyzed"}
    findings = validate_analysis_result(r, profile)
    assert any("到達できない" in f and "run_sh" in f for f in findings)
    assert any("到達できない" in f and "psycopg" in f for f in findings)


# --- 指摘 3: 根拠の実在検査 (scope の外、行数超え、scope 無し)
def test_evidence_must_stay_inside_scope_and_lines(tmp_path: Path, profile, result):
    scope = tmp_path / "scope"
    scope.mkdir()
    (tmp_path / "outside").write_text("x\n", encoding="utf-8")
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
    r = copy.deepcopy(result)
    assert validate_analysis_result(r, profile, scope) == []
    r["summary"]["evidence"] = [{"file": "../outside", "line": 1}]
    findings = validate_analysis_result(r, profile, scope)
    assert any("summary" in f and "scope の外" in f for f in findings)
    r = copy.deepcopy(result)
    r["summary"]["evidence"] = [{"file": "flows/daily/housekeeping.yaml", "line": 999}]
    findings = validate_analysis_result(r, profile, scope)
    assert any("行数" in f for f in findings)


def test_result_file_without_scope_is_reported(tmp_path: Path):
    r = yaml.safe_load((FIX / "result-housekeeping.yaml").read_text(encoding="utf-8"))
    p = tmp_path / "r.yaml"
    p.write_text(yaml.safe_dump(r, allow_unicode=True), encoding="utf-8")
    findings = validate_result_file(p, ROOT / "profiles/batch-kestra/profile.yaml")
    assert any(f.startswith("scope:") for f in findings)


# --- 指摘 5: 相対パスの抽出器はプロファイルのディレクトリから解決する
def test_relative_extractor_resolves_from_profile_dir(tmp_path: Path):
    prof = tmp_path / "profile"
    (prof / "extractors").mkdir(parents=True)
    exe = prof / "extractors/custom.py"
    exe.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    cmd = _command("extractors/custom.py", prof, tmp_path / "analysis")
    assert cmd[0] == str(exe.resolve())
    with pytest.raises(SystemExit):
        _command("extractors/missing.py", prof, tmp_path / "analysis")


# --- 指摘 6: CSV の出典の行はレコードの行
def test_csv_source_line_is_record_line(tmp_path: Path, capsys):
    (tmp_path / "jobs.csv").write_text("id,name\na,Alpha\nb,Beta\n", encoding="utf-8")
    extract(
        tmp_path,
        {
            "files": "jobs.csv",
            "format": "csv",
            "fields": {"id": "id", "name": "name", "path": "/{id}"},
        },
        "scheduler",
    )
    recs = [
        json.loads(line)
        for line in capsys.readouterr().out.splitlines()
        if line.strip()
    ]
    assert [(r["id"], r["source"]["line"]) for r in recs] == [("a", 2), ("b", 3)]


# --- 指摘 8: glob が 1 件も当たらなければ失敗し、既存の承認を消さない。指摘 4: enumerated_at は内容が同じなら据え置き
def _write_entry_list(
    path: Path, scope: Path, entries: list, files: str = "flows/*.yaml"
):
    el = {
        "format_version": 1,
        "target": {"repo": "x", "clone_path": str(scope), "commit": "abc1234"},
        "profile": {"id": "batch-kestra", "version": "0.1.0"},
        "extractors": [
            {
                "name": "kestra-flows",
                "run": "abatlas-extract structured-query",
                "layer": "scheduler",
                "params": {
                    "files": [files],
                    "format": "yaml",
                    "fields": {
                        "id": "join('.', [namespace, id])",
                        "namespace": "namespace",
                        "flow": "id",
                        "path": "/{namespace}/{flow}",
                    },
                    "post": {"namespace": {"split": ".", "join": "/"}},
                },
            }
        ],
        "entries": entries,
    }
    path.write_text(
        yaml.safe_dump(el, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )


def test_zero_match_fails_and_keeps_list(tmp_path: Path):
    scope = tmp_path / "scope"
    scope.mkdir()
    el = tmp_path / "entry-list.yaml"
    approved = [
        {
            "id": "daily.x",
            "path": "/daily/x",
            "layer": "scheduler",
            "source": {"file": "f", "line": 1},
            "status": "approved",
        }
    ]
    _write_entry_list(el, scope, approved)
    before = el.read_text(encoding="utf-8")
    with pytest.raises(SystemExit):
        enumerate_entries(el, ROOT / "profiles/batch-kestra/profile.yaml", write=True)
    assert el.read_text(encoding="utf-8") == before


def test_enumerated_at_is_stable_when_unchanged(tmp_path: Path):
    scope = tmp_path / "scope"
    (scope / "flows").mkdir(parents=True)
    (scope / "flows/x.yaml").write_text("id: x\nnamespace: daily\n", encoding="utf-8")
    el = tmp_path / "entry-list.yaml"
    _write_entry_list(el, scope, [])
    first = enumerate_entries(
        el, ROOT / "profiles/batch-kestra/profile.yaml", write=True
    )
    assert [e["id"] for e in first["entries"]] == ["daily.x"]
    second = enumerate_entries(
        el, ROOT / "profiles/batch-kestra/profile.yaml", write=True
    )
    assert first == second
