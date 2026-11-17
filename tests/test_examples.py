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
from abatlas.schemas import vocab
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


def test_complexity_counts_match_the_results(built: Path):
    """複雑度の表の数を、分析結果の YAML から数え直して突き合わせる (1 つの点数にまとめず、数を並べる)。"""
    docs = {p.stem: yaml.safe_load(p.read_text(encoding="utf-8")) for p in RESULTS.glob("*.yaml")}

    def key(f: dict) -> tuple:
        return (f["source"]["file"], f["name"], f["layer"])

    users: dict[tuple, set[str]] = {}
    for d in docs.values():
        for f in d["callstack"]:
            if f.get("caller"):
                users.setdefault(key(f), set()).add(d["entry"]["id"])
    shared = {k: v for k, v in users.items() if len(v) >= 2}
    expected = {}
    for d in docs.values():
        frames = {f["id"]: f for f in d["callstack"]}

        def depth(f: dict) -> int:
            return 1 if not f.get("caller") else 1 + depth(frames[f["caller"]])

        mine = {key(f) for f in frames.values() if f.get("caller") and key(f) in shared}
        expected[d["entry"]["id"]] = (
            len(frames),
            max(depth(f) for f in frames.values()),
            sum(1 for f in frames.values() if f.get("caller") and f["layer"] != frames[f["caller"]]["layer"]),
            len(mine),
            len(set().union(*(shared[k] for k in mine)) - {d["entry"]["id"]}) if mine else 0,
        )
    with duckdb.connect(str(duckdb_path(built)), read_only=True) as con:
        rows = con.execute("select entry_id, frame_count, max_depth, layer_crossings, shared_frame_count, sharing_entry_count from mart.mart_entry_complexity").fetchall()
        assert {r[0]: tuple(r[1:]) for r in rows} == expected
        # データの数も、分析結果の YAML から数え直す (集計の SQL と同じ条件を使わない)。外部の接続先は、データに数えない
        out_ops = {(k, o["id"]) for k, v in vocab("resource-kinds")["kinds"].items() for o in v["ops"] if o["direction"] == "out"}
        want = {}
        for d in docs.values():
            data, written, external = set(), set(), set()
            for f in d["callstack"]:
                for io in f.get("io", []):
                    res = io["resource"]
                    one = (res["kind"], tuple(sorted((res.get("levels") or {}).items())))
                    if res["kind"] == "external_api":
                        external.add(one)
                        continue
                    data.add(one)
                    if (res["kind"], io["op"]) in out_ops:
                        written.add(one)
            want[d["entry"]["id"]] = (len(data), len(written), len(external))
        got = {r[0]: tuple(r[1:]) for r in con.execute("select entry_id, datastore_count, written_datastore_count, external_count from mart.mart_entry_complexity").fetchall()}
        assert got == want
        assert all(w <= n for n, w, _ in got.values()) and any(w < n for n, w, _ in got.values()) and any(x > 0 for _, _, x in got.values())
        # 並びは、直すときに一緒に確かめるものが多い順
        order = con.execute("select sharing_entry_count, written_datastore_count, frame_count from mart.mart_entry_complexity").fetchall()
        assert order == sorted(order, reverse=True)
        cols = {c[0] for c in con.execute("describe mart.mart_entry_overview").fetchall()}
        assert "complexity" not in cols, "1 つにまとめた仮の指標は、置かない"



def test_aspect_marts_match_the_results(built: Path):
    """足した観点の表 (条件つきの呼び出し、列、状態の変化、つながり、設定) を、分析結果の YAML から数え直して突き合わせる。"""
    docs = [yaml.safe_load(p.read_text(encoding="utf-8")) for p in RESULTS.glob("*.yaml")]
    cond, fields, states, links, settings = set(), set(), 0, set(), set()
    branches: dict[str, tuple[int, int]] = {}
    for d in docs:
        eid = d["entry"]["id"]
        whens = [(f.get("call") or {}).get("when") for f in d["callstack"]]
        branches[eid] = (whens.count("conditional"), whens.count("on_failure"))
        for f in d["callstack"]:
            if (f.get("call") or {}).get("when") in ("conditional", "on_failure"):
                cond.add((eid, f["id"]))
            links |= {(eid, ln["kind"], ln["target"]) for ln in f.get("links", [])}
            settings |= {(s["name"], eid) for s in f.get("settings", [])}
            for io in f.get("io", []):
                table = (io["resource"].get("levels") or {}).get("table", "")
                for fl in io.get("fields", []):
                    fields.add((eid, table, fl["name"]))
                    states += "set_to" in fl
    assert cond and fields and states and links and settings, "見本が、どの観点も 1 つは持つ"
    with duckdb.connect(str(duckdb_path(built)), read_only=True) as con:
        q = lambda sql: con.execute(sql).fetchall()  # noqa: E731
        assert {tuple(r[0].split("|")) for r in q("select call_key from mart.mart_call_conditions")} == cond
        assert {(e, p.rsplit("/", 1)[1], f) for e, p, f in q("select entry_id, resource_path, field from mart.mart_field_access")} == fields
        assert q("select count(*) from mart.mart_state_changes")[0][0] == states
        assert {(e, k, t) for e, k, t in q("select entry_id, kind, target from mart.mart_entry_links")} == links
        assert q("select count(*) from mart.mart_entry_links where not resolved")[0][0] == 0, "見本のつながりの行き先は、すべて入口の一覧にある"
        assert {(s, e) for s, e in q("select setting, entry_id from mart.mart_settings")} == settings
        assert {e: (b, f) for e, b, f in q("select entry_id, branch_count, failure_path_count from mart.mart_entry_complexity")} == branches
        assert q("select count(*) from mart.mart_entry_access where authentication")[0][0] == 0, "見本は、権限の確認を持たない"
        assert q("select count(*) from mart.mart_entry_access")[0][0] == len(docs), "観点を分析した結果は、権限のまとめに 1 行ずつ出る"
        tested = {(e, f) for e, f in q("select entry_id, frame_name from mart.mart_test_coverage where test_count > 0")}
        assert tested == {(d["entry"]["id"], f["name"]) for d in docs for f in d["callstack"] if f.get("tests")} and tested, "テストのある処理だけが、数を持つ"
        assert q("select count(*) from mart.mart_test_coverage where layer = 'external'")[0][0] == 0, "外との境の処理は、テストの対象に数えない"
        guards = {(e, v) for e, v in q("select entry_id, value from mart.mart_entry_guards")}
        assert guards == {(d["entry"]["id"], g["value"]) for d in docs for f in d["callstack"] for g in f.get("guards", [])} and guards
        rules = q("select count(*) from mart.mart_rules")[0][0]
        assert rules == sum(len(f.get("rules", [])) for d in docs for f in d["callstack"]) and rules
        assert q("select count(*) from mart.mart_sensitive_data")[0][0] == 0, "辞書が無ければ、空"


def test_the_data_dictionary_feeds_the_sensitive_data_mart(tmp_path: Path):
    """辞書のコマンドが列を candidate で足し、人が approved にした列だけが、個人情報の表に出る。"""
    from abatlas.dictionary import FILE, update_dictionary

    shutil.copytree(TARGET, tmp_path / "kotori-books")
    shutil.copytree(ATLAS, tmp_path / "kotori-books-atlas")
    repo = tmp_path / "kotori-books-atlas"
    init_repo(repo, "batch-kestra", targets="claude-code")
    path = repo / ANALYSIS_DIR / FILE
    assert update_dictionary(repo, dry_run=True)["added"] > 0 and not path.exists(), "dry-run では書かない"
    rep = update_dictionary(repo)
    assert rep["added"] == rep["fields"] == rep["candidate"] == rep["unclassified"] > 0
    assert update_dictionary(repo)["added"] == 0, "2 回目は、何も足さない"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert all(f["field"] != "*" for f in doc["fields"]), "全部の列 (*) は、辞書に入れない"
    first, second = doc["fields"][0], doc["fields"][1]
    first.update({"category": "personal", "status": "approved"})
    second.update({"category": "personal"})  # candidate のまま: 集計に出ない
    path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    build_repo(repo)
    with duckdb.connect(str(duckdb_path(repo)), read_only=True) as con:
        rows = con.execute("select distinct resource_path, field, category from mart.mart_sensitive_data").fetchall()
    assert rows == [(first["resource"], first["field"], "personal")]
    # 語彙に無い区分は、集計の前に止まる
    first["category"] = "secret"
    path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    with pytest.raises(SystemExit, match="語彙に無い"):
        build_repo(repo)


def test_unreached_files_are_the_ones_no_result_mentions(built: Path):
    """どの入口からも辿られないファイル = 対象の範囲にあって、分析結果のどこにも出てこないファイル。YAML から数え直して突き合わせる。"""
    from abatlas.etl import target_files

    mentioned = set()
    for p in RESULTS.glob("*.yaml"):
        d = yaml.safe_load(p.read_text(encoding="utf-8"))
        mentioned.add(d["entry"]["source"]["file"])

        def walk(node):
            if isinstance(node, dict):
                if set(node) >= {"file", "line"}:
                    mentioned.add(node["file"])
                for v in node.values():
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)

        walk(d)
    files = target_files(built.parent / "kotori-books")
    assert "README.md" in files and all(not f.startswith(".git/") for f in files)
    with duckdb.connect(str(duckdb_path(built)), read_only=True) as con:
        unreached = {f for (f,) in con.execute("select file from mart.mart_unreached_files").fetchall()}
    assert unreached == set(files) - mentioned
    assert "README.md" in unreached and "scripts/run_job.sh" not in unreached
    assert target_files(None) == [] and target_files(built / "no-such-dir") == [], "対象が読めなければ、空 (集計は止めない)"
