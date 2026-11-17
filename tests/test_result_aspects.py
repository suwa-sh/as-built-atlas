"""分析結果に足した観点 (列、呼び出しの条件、つながり、権限の確認、設定、業務のルール、テスト) の検査と分解。"""
import copy
from pathlib import Path

import pytest
import yaml

from abatlas.etl import build_rows
from abatlas.validate import validate_analysis_result

ROOT = Path(__file__).resolve().parent.parent
FIX = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def profile():
    return yaml.safe_load((ROOT / "profiles/batch-kestra/profile.yaml").read_text(encoding="utf-8"))


@pytest.fixture
def result():
    return yaml.safe_load((FIX / "result-housekeeping.yaml").read_text(encoding="utf-8"))


def _frame(r, fid):
    return next(f for f in r["callstack"] if f["id"] == fid)


def _entries(*extra):
    base = {"layer": "scheduler", "status": "approved", "source": {"file": "flows/x.yaml", "line": 1}}
    return {"entries": [{"id": "daily.housekeeping", "path": "/daily/housekeeping", **base}, *({**base, **e} for e in extra)]}


def test_results_without_the_new_items_stay_valid(profile, result):
    """足した項目はすべて任意。前の指示書で書いた結果は、そのまま通る。"""
    r = copy.deepcopy(result)
    for f in r["callstack"]:
        for k in ("links", "guards", "settings", "rules", "tests"):
            f.pop(k, None)
        (f.get("call") or {}).pop("when", None)
        (f.get("call") or {}).pop("condition", None)
        for io in f.get("io", []):
            io.pop("fields", None)
    assert validate_analysis_result(r, profile) == []


@pytest.mark.parametrize("when", ["conditional", "on_failure"])
def test_a_conditional_call_needs_its_condition(profile, result, when):
    r = copy.deepcopy(result)
    _frame(r, "run_sh")["call"]["when"] = when
    assert any("/call" in f and "condition" in f for f in validate_analysis_result(r, profile))


def test_an_unconditional_call_cannot_have_a_condition(profile, result):
    r = copy.deepcopy(result)
    _frame(r, "run_sh")["call"]["condition"] = "いつも"
    assert any("/call" in f for f in validate_analysis_result(r, profile))


def test_the_entry_frame_cannot_say_when_it_is_called(profile, result):
    r = copy.deepcopy(result)
    _frame(r, "flow")["call"] = {"status": "fact", "when": "always", "evidence": [{"file": "a", "line": 1}]}
    assert any("flow/call" in f and "when" in f for f in validate_analysis_result(r, profile))


def test_a_field_is_written_once_per_io(profile, result):
    r = copy.deepcopy(result)
    _frame(r, "psycopg")["io"][0]["fields"].append({"name": "status", "use": ["read"]})
    assert any("fields" in f and "'status'" in f for f in validate_analysis_result(r, profile))


def test_set_to_needs_a_write(profile, result):
    r = copy.deepcopy(result)
    _frame(r, "psycopg")["io"][0]["fields"][0]["use"] = ["filter"]
    assert any("set_to" in f for f in validate_analysis_result(r, profile))


def test_tests_need_the_analyzer_flag(profile, result):
    r = copy.deepcopy(result)
    _frame(r, "run_sh")["tests"] = [{"name": "test_housekeeping", "kind": "unit", "status": "fact", "evidence": [{"file": "tests/t.sh", "line": 1}]}]
    assert any("run_sh/tests" in f for f in validate_analysis_result(r, profile))
    r["analyzer"]["tests"] = True
    assert validate_analysis_result(r, profile) == []


@pytest.mark.parametrize("name", ["links", "guards", "settings", "rules"])
def test_unknown_items_need_a_known_reason(profile, result, name):
    r = copy.deepcopy(result)
    item = {"links": {"kind": "trigger", "target": "x"}, "guards": {"kind": "role"}, "settings": {"name": "X", "kind": "env"}, "rules": {"kind": "decision"}}[name]
    _frame(r, "run_sh")[name] = [{**item, "status": "unknown", "reason": "no_such_reason"}]
    assert any(f"run_sh/{name}/0" in f and "reason" in f for f in validate_analysis_result(r, profile))


def test_rows_carry_the_new_items(result):
    rows = build_rows(_entries(), [result])
    frames = {f["frame_id"]: f for f in rows["frames"]}
    assert (frames["run_sh"]["call_when"], frames["run_sh"]["call_condition"]) == ("always", "")
    assert frames["notify"]["call_when"] == "on_failure" and frames["notify"]["call_condition"]
    assert frames["notify_py"]["call_when"] == "", "書かれていなければ空 (分析していない)"
    assert [(r["name"], r["use_write"], r["use_read"], r["set_to"], r["resource_path"]) for r in rows["io_fields"]] == [
        ("status", "true", "false", "done", "/rdb/ops_logs/job_runs"), ("finished_at", "true", "false", "", "/rdb/ops_logs/job_runs")]
    assert [(r["frame_id"], r["name"], r["kind"]) for r in rows["settings"]] == [("run_sh", "KEEP_DAYS", "env")]
    assert [(r["frame_id"], r["kind"]) for r in rows["rules"]] == [("run_sh", "decision")]
    assert rows["results"][0]["tests_analyzed"] == "false"
    paths = {c["claim_path"] for c in rows["claims"]}
    assert {"callstack/run_sh/settings/0", "callstack/run_sh/rules/0", "callstack/notify/links/0"} <= paths, "足した主張も、品質の集計に入る"


def test_a_link_is_matched_with_the_entry_list(result):
    """行き先は、入口の id か階層パスと一致すれば結ぶ。entry_id が書いてあれば、そちらを使う。一覧に無ければ結ばない。"""
    def target(entries, **link):
        r = copy.deepcopy(result)
        _frame(r, "notify")["links"][0].update(link)
        return build_rows(entries, [r])["links"][0]["target_entry_id"]

    report = {"id": "daily.report", "path": "/daily/report"}
    assert target(_entries()) == "", "一覧に無い"
    assert target(_entries(report)) == "daily.report", "id と一致"
    assert target(_entries(report), target="/daily/report") == "daily.report", "階層パスと一致"
    assert target(_entries(report), target="レポートのフロー", entry_id="daily.report") == "daily.report"
    assert target(_entries(report), entry_id="no.such") == "", "entry_id が一覧に無ければ、target で代わりに結ばない"


def test_a_condition_needs_when(profile, result):
    """条件だけを書いた呼び出しは、条件つきの呼び出しの表に出ない。when と一緒に書かせる。"""
    r = copy.deepcopy(result)
    call = _frame(r, "notify")["call"]
    del call["when"]
    assert any("/call" in f and "when" in f for f in validate_analysis_result(r, profile))


@pytest.mark.parametrize("name,key", [("settings", "effect"), ("settings", "kind"), ("rules", "value")])
def test_a_known_claim_carries_its_content(profile, result, name, key):
    """確かめた主張 (fact / interpretation) は、中身を持つ。分からなければ unknown にする。"""
    r = copy.deepcopy(result)
    item = _frame(r, "run_sh")[name][0]
    del item[key]
    assert any(name in f and key in f for f in validate_analysis_result(r, profile))
    if key != "kind":
        item.update({"status": "unknown", "reason": "not_analyzed"})
        item.pop("evidence")
        assert validate_analysis_result(r, profile) == []


def test_etl_refuses_what_the_field_check_refuses(result, tmp_path):
    """列の検査は、検査のコマンドを通さずに集計しても効く (列の表の行が重ならないように)。"""
    from abatlas import result_file_name
    from abatlas.etl import run_etl

    r = copy.deepcopy(result)
    _frame(r, "psycopg")["io"][0]["fields"].append({"name": "status", "use": ["read"]})
    (tmp_path / "results").mkdir()
    (tmp_path / "entry-list.yaml").write_text(yaml.safe_dump({"format_version": 1, "target": r["target"], "profile": r["analyzer"]["profile"], "extractors": [], "entries": []}), encoding="utf-8")
    (tmp_path / "results" / result_file_name(r["entry"]["id"])).write_text(yaml.safe_dump(r, allow_unicode=True), encoding="utf-8")
    with pytest.raises(SystemExit, match="2 回書かれている"):
        run_etl(tmp_path, tmp_path / "out")


def test_frames_know_whether_their_layer_is_the_boundary(profile, result):
    rows = build_rows(_entries(), [result], profile)
    assert {f["frame_id"]: f["boundary"] for f in rows["frames"]}["psycopg"] == "true"
    assert {f["frame_id"]: f["boundary"] for f in rows["frames"]}["run_sh"] == "false"
    assert build_rows(_entries(), [result])["frames"][0]["boundary"] == "", "プロファイルを渡さなければ、判定しない"
