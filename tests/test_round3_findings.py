"""外部レビュー round 3 で受け入れた指摘の回帰テスト (外部再レビューは未実施)。"""

import json
from pathlib import Path

import yaml

from abatlas.extractors.structured_query import extract
from abatlas.validate import validate_analysis_result, validate_entry_list

ROOT = Path(__file__).resolve().parent.parent
FIX = Path(__file__).resolve().parent / "fixtures"


def _profile():
    return yaml.safe_load(
        (ROOT / "profiles/batch-kestra/profile.yaml").read_text(encoding="utf-8")
    )


def test_root_frame_must_declare_caller_null():
    r = yaml.safe_load((FIX / "result-housekeeping.yaml").read_text(encoding="utf-8"))
    del r["callstack"][0]["caller"]
    findings = validate_analysis_result(r, _profile())
    assert any("caller が無い" in f for f in findings)


def test_entry_list_layer_must_be_entry_role():
    el = {
        "format_version": 1,
        "target": {"repo": "x", "commit": "abc1234"},
        "profile": {"id": "batch-kestra", "version": "0.1.0"},
        "extractors": [
            {
                "name": "x",
                "run": "abatlas-extract structured-query",
                "layer": "shell",
                "params": {},
            }
        ],
        "entries": [
            {
                "id": "a",
                "path": "/a",
                "layer": "shell",
                "source": {"file": "f", "line": 1},
                "status": "candidate",
            }
        ],
    }
    findings = validate_entry_list(el, _profile())
    assert any("extractors/x" in f and "role: entry" in f for f in findings)
    assert any("entries/a" in f and "role: entry" in f for f in findings)


def test_source_line_for_json_and_yaml_lists(tmp_path: Path, capsys):
    (tmp_path / "jobs.json").write_text(
        json.dumps({"jobs": [{"id": "first"}, {"id": "second"}]}, indent=2),
        encoding="utf-8",
    )
    (tmp_path / "jobs.yaml").write_text(
        "jobs:\n  - id: first\n  - id: second\n", encoding="utf-8"
    )
    fields = {"id": "id", "path": "/{id}"}
    extract(
        tmp_path,
        {"files": "jobs.json", "format": "json", "records": "jobs", "fields": fields},
        "scheduler",
    )
    recs = [
        json.loads(line)
        for line in capsys.readouterr().out.splitlines()
        if line.strip()
    ]
    assert {r["id"]: r["source"]["line"] for r in recs} == {"first": 4, "second": 7}
    extract(
        tmp_path,
        {"files": "jobs.yaml", "format": "yaml", "records": "jobs", "fields": fields},
        "scheduler",
    )
    recs = [
        json.loads(line)
        for line in capsys.readouterr().out.splitlines()
        if line.strip()
    ]
    assert {r["id"]: r["source"]["line"] for r in recs} == {"first": 2, "second": 3}
