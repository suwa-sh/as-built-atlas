"""分析結果の、版の間の差分 (abatlas diff)。"""

import copy
import subprocess  # nosec B404 - executes subprocesses with argument lists
from pathlib import Path

import pytest
import yaml

from abatlas import result_file_name
from abatlas.diff import diff_repo, diff_results

FIX = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def result():
    return yaml.safe_load(
        (FIX / "result-housekeeping.yaml").read_text(encoding="utf-8")
    )


def _frame(r, fid):
    return next(f for f in r["callstack"] if f["id"] == fid)


def test_same_results_have_no_diff(result):
    assert diff_results({"a": result}, {"a": copy.deepcopy(result)}) == []


def test_line_numbers_and_wording_are_not_a_diff(result):
    """対象の行がずれただけ、言い回しが変わっただけでは、差分にしない。"""
    new = copy.deepcopy(result)
    for f in new["callstack"]:
        f["source"]["line"] += 10
        if "summary" in f and "value" in f["summary"]:
            f["summary"]["value"] += " (書き直し)"
        for ev in (f.get("call") or {}).get("evidence", []):
            ev["line"] += 10
    assert diff_results({"a": result}, {"a": new}) == []


def test_changes_are_reported_by_aspect(result):
    new = copy.deepcopy(result)
    io = _frame(new, "psycopg")["io"][0]
    io["fields"][0]["set_to"] = "failed"  # 書く値が変わった
    io["fields"].append({"name": "error", "use": ["write"]})  # 列が増えた
    _frame(new, "notify")["call"].update({"when": "always"})  # 失敗のときだけ → いつも
    del _frame(new, "notify")["call"]["condition"]
    del _frame(new, "run_sh")["settings"]  # 設定が消えた
    (change,) = diff_results({"a": result}, {"a": new})
    by = {a["aspect"]: a for a in change["aspects"]}
    assert set(by) == {"io_fields", "conditions", "settings"}
    assert len(by["io_fields"]["added"]) == 2 and len(by["io_fields"]["removed"]) == 1
    assert (
        by["conditions"]["removed"] == [("lib.notify", "on_failure")]
        and by["conditions"]["added"] == []
    )
    assert by["settings"]["removed"] == [("KEEP_DAYS", "env")]


def test_added_and_removed_entries(result):
    changes = diff_results({"old": result}, {"new": result})
    assert [(c["entry_id"], c["change"]) for c in changes] == [
        ("new", "added"),
        ("old", "removed"),
    ]


def test_diff_reads_the_previous_results_from_git(result, tmp_path):
    def git(*args):
        subprocess.run(  # nosec B603, B607 - test-owned executable and arguments
            [
                "git",
                "-C",
                str(tmp_path),
                "-c",
                "user.name=t",
                "-c",
                "user.email=t@example.invalid",
                *args,
            ],
            check=True,
            capture_output=True,
        )

    results = tmp_path / "analysis" / "results"
    results.mkdir(parents=True)
    f = results / result_file_name(result["entry"]["id"])
    f.write_text(yaml.safe_dump(result, allow_unicode=True), encoding="utf-8")
    git("init", "-q")
    git("add", ".")
    git("commit", "-q", "-m", "first")
    assert diff_repo(tmp_path, "HEAD").splitlines() == [
        "diff: HEAD と比べて、分析結果が変わった入口 0 件、足された入口 0 件、消えた入口 0 件"
    ]
    new = copy.deepcopy(result)
    new["target"]["commit"] = "ffffffffff"
    _frame(new, "notify")["links"][0]["target"] = "weekly.report"
    f.write_text(yaml.safe_dump(new, allow_unicode=True), encoding="utf-8")
    out = diff_repo(tmp_path, "HEAD")
    assert (
        "変わった入口 1 件" in out
        and "~ /daily/housekeeping  (対象のコミット 0a1b2c3 → fffffff)" in out
    )
    assert (
        "      + trigger | weekly.report" in out
        and "      - trigger | daily.report" in out
    )
    with pytest.raises(SystemExit, match="git"):
        diff_repo(tmp_path, "no-such-rev")


def test_one_more_of_the_same_io_is_a_diff(result):
    """同じデータへの同じ操作が 1 か所増えた、も出す (キーが同じでも、個数を見る)。"""
    new = copy.deepcopy(result)
    frame = _frame(new, "notify_py")
    frame["io"].append(copy.deepcopy(frame["io"][0]))
    (change,) = diff_results({"a": result}, {"a": new})
    assert [
        (a["aspect"], len(a["added"]), len(a["removed"])) for a in change["aspects"]
    ] == [("io", 1, 0)]


def test_the_wording_of_a_condition_is_not_a_diff(result):
    """条件の文は、分析のたびに言い回しが変わる。いつ起きるか (when) の変化だけを差分にする。"""
    new = copy.deepcopy(result)
    _frame(new, "notify")["call"]["condition"] = "掃除が失敗したとき"
    assert diff_results({"a": result}, {"a": new}) == []


def test_a_moved_entry_and_a_changed_caller_are_diffs(result):
    new = copy.deepcopy(result)
    new["entry"]["path"] = "/daily/cleanup"
    (change,) = diff_results({"a": result}, {"a": new})
    assert [a["aspect"] for a in change["aspects"]] == ["entry"]
    new = copy.deepcopy(result)
    _frame(new, "notify_py")["caller"] = "run_sh"
    (change,) = diff_results({"a": result}, {"a": new})
    assert [a["aspect"] for a in change["aspects"]] == ["frames"]
    assert change["aspects"][0]["added"] == [
        ("program", "notify.py", "notify.py", "scripts/housekeeping.sh")
    ]
