"""根拠の近くに名前が無い主張の一覧 (abatlas evidence)。"""

import copy
from pathlib import Path

import pytest
import yaml

from abatlas.cli import main
from abatlas.evidence_names import unnamed_evidence

FIXTURES = Path(__file__).parent / "fixtures"


def _frame(fid, file, caller, **extra):
    base = {
        "id": fid,
        "layer": "program",
        "name": fid,
        "source": {"file": file, "line": 1},
        "caller": caller,
    }
    return {**base, **extra}


@pytest.fixture
def scope(tmp_path):
    lines = ["# filler"] * 30
    lines[9] = "bash scripts/cleanup.sh"  # 10 行目
    lines[19] = "export KEEP_DAYS=7"  # 20 行目
    (tmp_path / "flow.yaml").write_text("\n".join(lines), encoding="utf-8")
    (tmp_path / "job.py").write_text(
        'cur.execute("DELETE FROM job_runs")\n', encoding="utf-8"
    )
    return tmp_path


def _result(call_line=10, setting_line=20, table="job_runs"):
    ev = [{"file": "flow.yaml", "line": call_line}]
    return {
        "callstack": [
            _frame("flow", "flow.yaml", None),
            _frame(
                "run",
                "scripts/cleanup.sh",
                "flow",
                name="掃除のスクリプト",
                call={"status": "fact", "evidence": ev},
                settings=[
                    {
                        "name": "KEEP_DAYS",
                        "status": "fact",
                        "evidence": [{"file": "flow.yaml", "line": setting_line}],
                    }
                ],
                io=[
                    {
                        "op": "delete",
                        "status": "fact",
                        "resource": {"kind": "rdb", "levels": {"table": table}},
                        "evidence": [{"file": "job.py", "line": 1}],
                    },
                    # 根拠の無い主張と、相手の段を書いていない読み書きは、照合しない
                    {"op": "read", "status": "unknown", "resource": {"kind": "rdb"}},
                    {
                        "op": "call",
                        "status": "fact",
                        "resource": {"kind": "external_api"},
                        "evidence": [{"file": "flow.yaml", "line": 1}],
                    },
                ],
            ),
        ]
    }


def test_claims_whose_names_are_near_the_evidence_are_not_listed(scope):
    report = unnamed_evidence(_result(), scope)
    assert report == {"checked": 3, "unnamed": [], "skipped": []}


def test_a_call_is_listed_when_the_callee_is_not_near_the_evidence(scope):
    # 4 行目の前後 5 行 (1〜9 行目) に、10 行目の呼び出しは入らない
    report = unnamed_evidence(_result(call_line=4), scope)
    assert len(report["unnamed"]) == 1
    assert report["unnamed"][0].startswith("callstack/run/call: 'cleanup'")
    assert "flow.yaml:4" in report["unnamed"][0]


def test_the_window_is_five_lines_on_each_side(scope):
    assert unnamed_evidence(_result(call_line=5), scope)["unnamed"] == []
    assert unnamed_evidence(_result(call_line=15), scope)["unnamed"] == []
    assert len(unnamed_evidence(_result(call_line=16), scope)["unnamed"]) == 1


def test_settings_and_resources_are_matched_as_whole_words(scope):
    report = unnamed_evidence(_result(setting_line=1, table="job"), scope)
    where = [line.split(":")[0] for line in report["unnamed"]]
    # job_runs の中の job は、語としては一致しない
    assert where == ["callstack/run/io/0", "callstack/run/settings/0"]


def test_unreadable_evidence_is_reported_as_skipped_not_as_unnamed(scope):
    # 範囲の外に、探す語を持つファイルを実際に置く (範囲の外を読む実装なら、見つかってしまう)
    (scope.parent / "outside.py").write_text("job_runs\n", encoding="utf-8")
    result = _result(call_line=99)
    result["callstack"][1]["io"][0]["evidence"][0]["file"] = "../outside.py"
    report = unnamed_evidence(result, scope)
    assert report["checked"] == 1 and report["unnamed"] == []
    assert [line.split(":")[0] for line in report["skipped"]] == [
        "callstack/run/call",
        "callstack/run/io/0",
    ]


def test_a_name_found_near_any_readable_evidence_is_enough(scope):
    result = _result()
    result["callstack"][1]["call"]["evidence"].append({"file": "gone.py", "line": 1})
    assert unnamed_evidence(result, scope) == {
        "checked": 3,
        "unnamed": [],
        "skipped": [],
    }


def test_unreadable_evidence_left_after_a_miss_is_skipped_not_unnamed(scope):
    # 読めた根拠 (4 行目) には名前が無く、もう 1 つは読めない。確かめ切れていないので、名前が無いとは言わない
    result = _result(call_line=4)
    result["callstack"][1]["call"]["evidence"].append({"file": "gone.py", "line": 1})
    report = unnamed_evidence(result, scope)
    assert report["unnamed"] == [] and report["checked"] == 2
    assert report["skipped"][0].startswith("callstack/run/call")


def test_evidence_that_is_not_a_path_or_not_utf8_text_is_skipped(scope):
    (scope / "job.py").write_bytes("DELETE FROM job_runs\n".encode("utf-16"))
    result = _result()
    result["callstack"][1]["call"]["evidence"][0]["file"] = "flow\0.yaml"
    report = unnamed_evidence(result, scope)
    assert report["checked"] == 1 and report["unnamed"] == []
    assert [line.split(":")[0] for line in report["skipped"]] == [
        "callstack/run/call",
        "callstack/run/io/0",
    ]


def test_a_name_that_starts_with_a_digit_is_searched_whole(scope):
    (scope / "flow.yaml").write_text("exec zip archive\n", encoding="utf-8")
    result = _result(call_line=1)
    result["callstack"][1]["source"]["file"] = "bin/x"
    result["callstack"][1]["name"] = "7zip"
    assert unnamed_evidence(result, scope)["unnamed"][0].startswith(
        "callstack/run/call: '7zip'"
    )
    (scope / "flow.yaml").write_text("exec 7zip archive\n", encoding="utf-8")
    report = unnamed_evidence(result, scope)
    assert not [u for u in report["unnamed"] if "/call" in u]


def test_a_file_that_cannot_be_opened_does_not_stop_the_listing(scope, monkeypatch):
    from pathlib import Path

    real = Path.read_bytes

    def read_bytes(self):
        if self.name == "job.py":
            raise PermissionError("denied")
        return real(self)

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    report = unnamed_evidence(_result(), scope)
    assert report["checked"] == 2
    assert report["skipped"][0].startswith("callstack/run/io/0")


def test_lines_are_counted_like_the_machine_check(scope):
    # 改ページ (\f) は行を分けない。10 行目の呼び出しは、5 行目の前後 5 行に入る
    text = (scope / "flow.yaml").read_text(encoding="utf-8")
    (scope / "flow.yaml").write_text("\f" + text, encoding="utf-8")
    assert unnamed_evidence(_result(call_line=5), scope)["unnamed"] == []


def test_a_line_number_written_as_a_whole_float_is_accepted(scope):
    result = _result()
    result["callstack"][1]["call"]["evidence"][0]["line"] = 10.0
    assert unnamed_evidence(result, scope)["unnamed"] == []


def test_short_setting_names_are_searched_as_they_are(scope):
    result = _result()
    result["callstack"][1]["settings"][0]["name"] = "TZ"
    assert unnamed_evidence(result, scope)["unnamed"][0].startswith(
        "callstack/run/settings/0: 'TZ'"
    )


def test_a_resource_without_searchable_words_is_skipped(scope):
    report = unnamed_evidence(_result(table="*"), scope)
    assert report["checked"] == 2
    assert "探せる語" in report["skipped"][0]


def test_the_deepest_written_level_names_the_resource(scope):
    result = _result()
    result["callstack"][1]["io"][0]["resource"]["levels"] = {
        "table": "job_runs",
        "database": "ops_logs",
    }
    assert unnamed_evidence(result, scope)["unnamed"] == []


def _work(tmp_path, clone):
    work = yaml.safe_load((FIXTURES / "work-definition.yaml").read_text("utf-8"))
    work["target"]["clone_path"] = str(clone)
    work["target"]["scope"] = "."
    path = tmp_path / "work-definition.yaml"
    path.write_text(yaml.safe_dump(work, allow_unicode=True), encoding="utf-8")
    return path


def test_the_command_lists_without_failing(tmp_path, capsys):
    clone = tmp_path / "clone"
    (clone / "flows/daily").mkdir(parents=True)
    (clone / "flows/daily/housekeeping.yaml").write_text(
        "\n".join(["# filler"] * 80), encoding="utf-8"
    )
    result = yaml.safe_load((FIXTURES / "result-housekeeping.yaml").read_text("utf-8"))
    path = tmp_path / "result.yaml"
    path.write_text(yaml.safe_dump(result, allow_unicode=True), encoding="utf-8")
    args = ["evidence", str(path), "--work", str(_work(tmp_path, clone))]
    assert main(args) == 0
    out = capsys.readouterr().out
    assert f"{path}: 根拠の近くに名前が無い主張 2 件 (照合した主張 2 件" in out
    assert "  - callstack/run_sh/call: 'housekeeping', 'scripts' のどれも" in out
    assert "  - callstack/notify/call: 'notify', 'lib' のどれも" in out
    assert "(照合できない) callstack/run_sh/settings/0" in out


def test_the_command_stops_when_the_result_or_the_target_is_unreadable(
    tmp_path, capsys
):
    result = yaml.safe_load((FIXTURES / "result-housekeeping.yaml").read_text("utf-8"))
    broken = copy.deepcopy(result)
    del broken["callstack"]
    path = tmp_path / "result.yaml"
    path.write_text(yaml.safe_dump(broken, allow_unicode=True), encoding="utf-8")
    work = str(_work(tmp_path, tmp_path / "absent"))
    assert main(["evidence", str(path), "--work", work]) == 2
    assert "validate result" in capsys.readouterr().err
    path.write_text("callstack: [", encoding="utf-8")
    assert main(["evidence", str(path), "--work", work]) == 2
    assert f"{path} を読めない" in capsys.readouterr().err
    # 分析結果は読めるが、対象の clone が無い
    path.write_text(yaml.safe_dump(result, allow_unicode=True), encoding="utf-8")
    assert main(["evidence", str(path), "--work", work]) == 2
    assert "target.clone_path" in capsys.readouterr().err


def test_the_command_stops_when_the_work_definition_is_unreadable(tmp_path, capsys):
    # 分析結果と対象は読める。作業定義だけが、壊れている・無い・形式に合わない
    clone = tmp_path / "clone"
    clone.mkdir()
    result = (FIXTURES / "result-housekeeping.yaml").read_text("utf-8")
    path = tmp_path / "result.yaml"
    path.write_text(result, encoding="utf-8")
    good = _work(tmp_path, clone)
    assert main(["evidence", str(path), "--work", str(good)]) == 0
    capsys.readouterr()
    absent = tmp_path / "none.yaml"
    broken = tmp_path / "broken.yaml"
    broken.write_text("target: [", encoding="utf-8")
    for work in (absent, broken):
        assert main(["evidence", str(path), "--work", str(work)]) == 2
        assert f"{work} を読めない" in capsys.readouterr().err
    broken.write_text("format_version: 1\n", encoding="utf-8")
    assert main(["evidence", str(path), "--work", str(broken)]) == 2
    err = capsys.readouterr().err
    assert str(broken) in err and "validate work" in err


def test_the_command_stops_when_the_target_cannot_be_entered(
    tmp_path, capsys, monkeypatch
):
    import os

    clone = tmp_path / "clone"
    clone.mkdir()
    path = tmp_path / "result.yaml"
    path.write_text(
        (FIXTURES / "result-housekeeping.yaml").read_text("utf-8"), encoding="utf-8"
    )
    work = str(_work(tmp_path, clone))
    assert main(["evidence", str(path), "--work", work]) == 0
    # 読む権限はあるが、中に入る権限 (X_OK) が無い
    monkeypatch.setattr(os, "access", lambda p, mode, **k: not mode & os.X_OK)
    assert main(["evidence", str(path), "--work", work]) == 2
    assert "target.clone_path" in capsys.readouterr().err


def test_an_empty_work_option_is_an_error_not_an_omission(tmp_path, capsys):
    path = tmp_path / "result.yaml"
    path.write_text(
        (FIXTURES / "result-housekeeping.yaml").read_text("utf-8"), encoding="utf-8"
    )
    assert main(["evidence", str(path), "--work", ""]) == 2
    assert "を読めない" in capsys.readouterr().err


def test_a_target_path_that_cannot_be_a_path_stops_with_the_reason(tmp_path, capsys):
    path = tmp_path / "result.yaml"
    path.write_text(
        (FIXTURES / "result-housekeeping.yaml").read_text("utf-8"), encoding="utf-8"
    )
    work = _work(tmp_path, "clone\0")
    assert main(["evidence", str(path), "--work", str(work)]) == 2
    assert f"{work} の target" in capsys.readouterr().err


def test_evidence_in_another_encoding_or_a_link_loop_is_skipped(scope):
    (scope / "job.py").write_bytes("# vérité\nDELETE FROM job_runs\n".encode("latin-1"))
    (scope / "loop.yaml").symlink_to("loop.yaml")
    result = _result()
    result["callstack"][1]["call"]["evidence"][0]["file"] = "loop.yaml"
    report = unnamed_evidence(result, scope)
    assert report["checked"] == 1 and report["unnamed"] == []
    assert len(report["skipped"]) == 2
