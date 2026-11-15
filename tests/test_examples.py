"""公開サンプル (examples/kotori-books と kotori-books-atlas) の検査。

- 生成物が生成スクリプトと一致している (再生成して差が無い)
- 正解 YAML がすべて機械チェックに通り、根拠の行が実在する
- 入口一覧は列挙ツールの出力と一致し、全件に結果がある
- 突合ツールが自分自身で 100%、欠けを入れると下がる
- init → build で mart が埋まる (共有している処理・外部との接続・不明の理由)
"""

from __future__ import annotations

import copy
import filecmp
import shutil
import subprocess
import sys
from pathlib import Path

import duckdb
import pytest
import yaml

from abatlas import ANALYSIS_DIR, REPO_ROOT, duckdb_path
from abatlas.build import build_repo
from abatlas.enumerate import enumerate_entries
from abatlas.etl import run_etl
from abatlas.evaluate import compare_entry, evaluate, exit_code, format_report, io_key, load_results
from abatlas.layout import init_repo
from abatlas.validate import validate_result_file

EX = REPO_ROOT / "examples"
TARGET = EX / "kotori-books"
ATLAS = EX / "kotori-books-atlas"
GENERATOR = EX / "generator" / "kotori_books.py"
PROFILE = REPO_ROOT / "profiles" / "batch-kestra" / "profile.yaml"
WORK = ATLAS / ANALYSIS_DIR / "work-definition.yaml"
RESULTS = ATLAS / ANALYSIS_DIR / "results"


def _tree(root: Path) -> dict[str, Path]:
    return {p.relative_to(root).as_posix(): p for p in root.rglob("*") if p.is_file() and ".git/" not in p.as_posix() and "__pycache__" not in p.parts}


def test_generated_files_are_up_to_date(tmp_path: Path):
    """生成スクリプトを直したら再生成して commit する (差があればこのテストが落ちる)。"""
    r = subprocess.run([sys.executable, str(GENERATOR), "--out", str(tmp_path)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    for name in ("kotori-books", "kotori-books-atlas"):
        want, got = _tree(tmp_path / name), _tree(EX / name)
        assert set(want) == set(got), f"{name}: ファイルの集合が違う: {sorted(set(want) ^ set(got))[:10]}"
        diff = [rel for rel in sorted(want) if not filecmp.cmp(want[rel], got[rel], shallow=False)]
        assert not diff, f"{name}: 内容が違う: {diff[:10]}"


def test_all_results_pass_machine_check():
    files = sorted(RESULTS.glob("*.yaml"))
    assert len(files) >= 30
    for p in files:
        assert validate_result_file(p, PROFILE, WORK) == [], p.name


def test_entry_list_matches_enumeration_and_results():
    el_path = ATLAS / ANALYSIS_DIR / "entry-list.yaml"
    shipped = yaml.safe_load(el_path.read_text(encoding="utf-8"))
    fresh = enumerate_entries(el_path, PROFILE, write=False)
    key = lambda e: (e["id"], e["path"], e["layer"], e["source"]["file"], e["source"]["line"], e.get("name"))  # noqa: E731
    assert [key(e) for e in fresh["entries"]] == [key(e) for e in shipped["entries"]]
    assert all(e["status"] == "approved" for e in shipped["entries"])
    assert {p.stem for p in RESULTS.glob("*.yaml")} == {e["id"] for e in shipped["entries"]}
    assert all(r["target"]["commit"] == shipped["target"]["commit"] for r in load_results(RESULTS).values())


def test_etl_counts(tmp_path: Path):
    counts = run_etl(ATLAS / ANALYSIS_DIR, tmp_path)
    assert counts["entries"] == counts["results"] >= 30
    assert counts["io"] >= 150 and counts["frames"] >= 150


def test_unknown_reasons_are_covered():
    reasons = {c.get("reason") for r in load_results(RESULTS).values() for f in r["callstack"]
               for c in [f.get("summary") or {}, *f.get("io", [])] if c.get("status") == "unknown"}
    assert {"not_traceable_in_repo", "dynamic_dispatch", "generated_at_runtime", "binary_or_vendored"} <= reasons


def test_evaluate_self_is_perfect():
    rep = evaluate(RESULTS, RESULTS)
    assert rep["entries"]["compared"] >= 30 and not rep["entries"]["unanalyzed"]
    for section in ("frames", "io", "parameters"):
        assert rep["totals"][section]["precision"] == 1.0 and rep["totals"][section]["recall"] == 1.0
    assert rep["totals"]["io"]["status_and_reason_agree"] == rep["totals"]["io"]["matched"]
    text = format_report(rep)
    assert "100%" in text and "未分析" not in text.splitlines()[-1]
    assert exit_code(rep) == 0


def test_evaluate_detects_gaps(tmp_path: Path):
    truth = load_results(RESULTS)["daily.sales.settle_orders"]
    got = copy.deepcopy(truth)
    job = next(f for f in got["callstack"] if f["id"] == "job")
    removed = job["io"].pop(0)                         # 正解にだけある I/O
    job["io"][0]["op"] = "delete" if job["io"][0]["op"] != "delete" else "read"  # 同じデータで操作だけ違う
    job["io"][1]["status"] = "interpretation"          # 状態の不一致 (キーは同じなので一致はする)
    assert job["io"][2]["resource"]["kind"] == "rdb"
    job["io"][2]["resource"]["levels"]["host"] = "DB.INTERNAL/"  # 表記ゆれは吸収する
    got["callstack"] = [f for f in got["callstack"] if f["id"] != "psycopg"]  # フレームの欠け
    rep = compare_entry(got, truth)
    assert rep["io"]["fn"] == 2 and rep["io"]["fp"] == 1 and rep["io"]["op_mismatch"] == 1
    total_io = sum(len(f.get("io", [])) for f in got["callstack"])
    assert rep["io"]["matched"] == total_io - 1 and rep["io"]["status_agree"] == rep["io"]["matched"] - 1
    assert rep["frames"]["fn"] == 1 and rep["frames"]["missing"] == ["external jobs/lib/db.py"]
    assert any(removed["resource"]["levels"]["table"] in m for m in rep["io"]["missing"])
    # 未分析と正解に無い入口
    (tmp_path / "r").mkdir()
    shutil.copy(RESULTS / "daily.sales.settle_orders.yaml", tmp_path / "r")
    extra = copy.deepcopy(truth)
    extra["entry"]["id"] = "daily.sales.not_in_truth"
    (tmp_path / "r" / "x.yaml").write_text(yaml.safe_dump(extra, allow_unicode=True), encoding="utf-8")
    (tmp_path / "r" / "broken.yaml").write_text("just: text\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="突合できない入力"):
        evaluate(tmp_path / "r", RESULTS)
    (tmp_path / "r" / "broken.yaml").unlink()
    (tmp_path / "r" / "dup.yaml").write_text(yaml.safe_dump(truth, allow_unicode=True), encoding="utf-8")
    with pytest.raises(SystemExit, match="重複"):
        evaluate(tmp_path / "r", RESULTS)
    (tmp_path / "r" / "dup.yaml").unlink()
    rep2 = evaluate(tmp_path / "r", RESULTS)
    assert rep2["entries"]["compared"] == 1 and rep2["entries"]["not_in_truth"] == ["daily.sales.not_in_truth"]
    assert len(rep2["entries"]["unanalyzed"]) == len(list(RESULTS.glob("*.yaml"))) - 1
    # 未分析の入口は分母に入る (1 件だけ分析しても総合 100% にならない)。正解に無い入口は結果だけ (FP) に入る。終了コードは 1
    assert rep2["totals"]["io"]["recall"] < 0.1 and rep2["totals"]["io"]["precision"] == 0.5
    assert exit_code(rep2) == 1 and "操作だけ違うもの" in format_report(rep2)
    # 状態の一致は並び順に依らない (同じキーの fact と unknown を入れ替えても一致数は同じ)
    tw = copy.deepcopy(truth)
    j = next(f for f in tw["callstack"] if f["id"] == "job")
    dup = copy.deepcopy(j["io"][0]); dup["status"] = "unknown"; dup["reason"] = "not_analyzed"; dup.pop("evidence", None)
    j["io"].insert(0, dup)
    swapped = copy.deepcopy(tw)
    js = next(f for f in swapped["callstack"] if f["id"] == "job")
    js["io"][0], js["io"][1] = js["io"][1], js["io"][0]
    a, b = compare_entry(tw, tw)["io"], compare_entry(swapped, tw)["io"]
    assert a["status_agree"] == b["status_agree"] == a["matched"] and a["status_and_reason_agree"] == b["status_and_reason_agree"]


def test_evaluate_distinct_ignores_repeats(tmp_path: Path):
    """同じ処理を何度書くかの違いは、重複を除いた比較 (distinct) には響かない。欠けと余分は distinct でも数える。"""
    truth = load_results(RESULTS)["daily.sales.settle_orders"]
    got = copy.deepcopy(truth)
    job = next(f for f in got["callstack"] if f["id"] == "job")
    again = copy.deepcopy(job)                          # 同じ処理を、別の id でもう一度書く (フレームも I/O もパラメータも重複する)
    again["id"] = "job_again"
    got["callstack"].append(again)
    rep = compare_entry(got, truth)
    assert rep["frames"]["fp"] == 1 and rep["io"]["fp"] == len(job["io"]) and rep["io"]["precision"] < 1.0
    for section in ("frames", "io", "parameters"):
        d = rep[section]["distinct"]
        assert d["fp"] == 0 and d["fn"] == 0 and d["precision"] in (1.0, None) and d["recall"] in (1.0, None)
    # 欠けと余分は distinct でも出る
    removed = next(f for f in got["callstack"] if f["id"] == "job_again")["io"].pop(0)
    job["io"] = [io for io in job["io"] if io != removed]
    extra = copy.deepcopy(job["io"][0])
    extra["resource"]["levels"]["table"] = "not_in_truth_table"
    job["io"].append(extra)
    d = compare_entry(got, truth)["io"]["distinct"]
    assert d["fn"] == 1 and d["fp"] == 1
    # 総合: 入口ごとに重複を除いてから足す。未分析の入口は distinct の分母にも入る。終了コードは重複込みで決まる
    (tmp_path / "r").mkdir()
    dup = copy.deepcopy(truth)
    dup["callstack"].append({**copy.deepcopy(next(f for f in dup["callstack"] if f["id"] == "job")), "id": "job_again"})
    (tmp_path / "r" / "a.yaml").write_text(yaml.safe_dump(dup, allow_unicode=True), encoding="utf-8")
    (tmp_path / "t").mkdir()
    shutil.copy(RESULTS / "daily.sales.settle_orders.yaml", tmp_path / "t")
    rep2 = evaluate(tmp_path / "r", tmp_path / "t")
    t = rep2["totals"]
    assert t["io"]["distinct"]["precision"] == 1.0 and t["io"]["distinct"]["recall"] == 1.0 and t["io"]["precision"] < 1.0
    assert exit_code(rep2) == 1
    text = format_report(rep2)
    assert "重複を除いた比較" in text and "I/O 適合率 (重複なし)" in text
    rep3 = evaluate(tmp_path / "r", RESULTS)
    assert rep3["entries"]["unanalyzed"] and rep3["totals"]["io"]["distinct"]["recall"] < 0.1
    assert rep3["totals"]["frames"]["distinct"]["fn"] > 0
    # 入口が複数: 入口ごとに重複を除いてから足す (入口をまたいで 1 つにまとめない)。正解に無い入口は、重複を除いた数だけ「結果だけ」に入る
    n_io = len({io_key(io) for f in truth["callstack"] for io in f.get("io", [])})
    n_fr = len({(f["layer"], f["source"]["file"]) for f in truth["callstack"]})
    second = copy.deepcopy(truth)
    second["entry"]["id"] = "daily.sales.second"       # 中身が同じ別の入口 (同じキーを持つ)
    (tmp_path / "t" / "b.yaml").write_text(yaml.safe_dump(second, allow_unicode=True), encoding="utf-8")
    dup2 = copy.deepcopy(dup)
    dup2["entry"]["id"] = "daily.sales.second"
    (tmp_path / "r" / "b.yaml").write_text(yaml.safe_dump(dup2, allow_unicode=True), encoding="utf-8")
    stray = copy.deepcopy(dup)                           # 正解に無い入口 (中に重複がある)
    stray["entry"]["id"] = "daily.sales.stray"
    (tmp_path / "r" / "c.yaml").write_text(yaml.safe_dump(stray, allow_unicode=True), encoding="utf-8")
    t4 = evaluate(tmp_path / "r", tmp_path / "t")["totals"]
    assert (t4["io"]["distinct"]["tp"], t4["io"]["distinct"]["fp"], t4["io"]["distinct"]["fn"]) == (2 * n_io, n_io, 0)
    assert (t4["frames"]["distinct"]["tp"], t4["frames"]["distinct"]["fp"], t4["frames"]["distinct"]["fn"]) == (2 * n_fr, n_fr, 0)
    assert t4["io"]["fp"] > t4["io"]["distinct"]["fp"]  # 重複込みでは、重複の分だけ「結果だけ」が増える
    # 未分析の入口 (正解にだけある) も、中の重複を除いた数だけ「正解だけ」に入る
    (tmp_path / "t" / "d.yaml").write_text(yaml.safe_dump({**copy.deepcopy(dup), "entry": {**dup["entry"], "id": "daily.sales.unanalyzed"}}, allow_unicode=True), encoding="utf-8")
    t5 = evaluate(tmp_path / "r", tmp_path / "t")["totals"]
    assert t5["io"]["distinct"]["fn"] == n_io and t5["frames"]["distinct"]["fn"] == n_fr
    assert t5["io"]["fn"] > n_io and t5["frames"]["fn"] == n_fr + 1


@pytest.fixture(scope="module")
def built(tmp_path_factory) -> Path:
    """見本を checkout の外 (tmp) に並べてコピーし、init → build まで通す (README の手順と同じ)。"""
    root = tmp_path_factory.mktemp("kotori")
    shutil.copytree(TARGET, root / "kotori-books")
    shutil.copytree(ATLAS, root / "kotori-books-atlas")
    repo = root / "kotori-books-atlas"
    made = init_repo(repo, "batch-kestra", targets="claude-code")
    assert any(".abatlas" in m for m in made)
    assert (repo / ".env").read_text(encoding="utf-8").startswith("# docker compose")  # 見本の .env は上書きされない
    rep = build_repo(repo)
    assert rep["dbt_ok"] == rep["dbt_nodes"], rep
    return repo


def test_marts_are_populated(built: Path):
    with duckdb.connect(str(duckdb_path(built)), read_only=True) as con:
        shared = con.execute("select source_file, entry_count from mart.mart_shared_frames order by entry_count desc").fetchall()
        assert shared and shared[0][0] == "scripts/run_job.sh" and shared[0][1] >= 25
        hosts = {h for (h,) in con.execute("select distinct host from mart.mart_external_if").fetchall()}
        assert {"api.payment.example", "api.mail.example", "(不明)"} <= hosts
        kinds = {k for (k,) in con.execute("select distinct kind from mart.mart_data_access").fetchall()}
        assert {"rdb", "kvs", "filesystem", "object_storage", "queue"} <= kinds
        reasons = {r for (r,) in con.execute("select distinct reason from mart.mart_quality_unknowns").fetchall()}
        assert {"not_traceable_in_repo", "dynamic_dispatch", "generated_at_runtime", "binary_or_vendored"} <= reasons
        (analyzed,) = con.execute("select sum(analyzed) from mart.mart_progress").fetchone()
        assert analyzed == len(list(RESULTS.glob("*.yaml")))
        (n_data,) = con.execute("select count(distinct resource_path) from mart.mart_data_access").fetchone()
        assert n_data >= 80
