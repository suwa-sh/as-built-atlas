"""導線の作り直し (段階 4 の 2 巡目): 種類ごとの操作の語彙、プロファイルの階層ラベル、DuckDB の meta、API の tree / pivot / __contains。

画面そのものはブラウザで見る。ここでは画面が読む契約 (宣言の subject / title、meta、集計 API) を見本で確かめる。
"""

import copy
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from abatlas import ANALYSIS_DIR
from abatlas.api import _fold, create_app
from abatlas.build import build_repo
from abatlas.declarations import SUBJECTS, check_declaration
from abatlas.etl import result_errors, build_rows
from abatlas.layout import init_repo
from abatlas.schemas import vocab
from abatlas.validate import hierarchy_label_problems, validate_analysis_result, validate_profile

FIX = Path(__file__).resolve().parent / "fixtures"
LOCAL = "http://127.0.0.1:8765"


def _entry_list(target: dict) -> dict:
    mk = lambda i, p, st: {"id": i, "path": p, "name": p.rsplit("/", 1)[-1], "layer": "scheduler", "status": st,
                           "source": {"file": f"flows{p}.yaml", "line": 1}, "extractor": "kestra-flows"}
    return {
        "format_version": 1, "target": target, "profile": {"id": "batch-kestra", "version": "0.1.0"},
        "extractors": [{"name": "kestra-flows", "run": "abatlas-extract structured-query", "layer": "scheduler", "params": {}, "rationale": "test"}],
        "enumerated_at": "2026-11-04T00:00:00+09:00",
        "entries": [mk("daily.housekeeping", "/daily/housekeeping", "approved"), mk("daily.morning.news", "/daily/morning/news", "approved"),
                    mk("weekly.report", "/weekly/report", "candidate")],
    }


def _second_result(base: dict) -> dict:
    """2 件目の結果: ファイルとキューと KVS を触る入口 (種類ごとの操作の見本)。"""
    r = copy.deepcopy(base)
    r["entry"] = {"id": "daily.morning.news", "path": "/daily/morning/news", "name": "news", "layer": "scheduler", "source": {"file": "flows/daily/morning/news.yaml", "line": 1}}
    r["summary"] = {"status": "interpretation", "value": "ニュースを集めて notes に書く", "evidence": [{"file": "flows/daily/morning/news.yaml", "line": 1}]}
    ev = [{"file": "scripts/news.py", "line": 1}]
    r["callstack"] = [
        {"id": "flow", "layer": "scheduler", "kind": "flow", "name": "daily.morning.news", "source": {"file": "flows/daily/morning/news.yaml", "line": 1}, "caller": None},
        {"id": "py", "layer": "program", "kind": "script", "name": "news.py", "source": {"file": "scripts/news.py", "line": 1}, "caller": "flow",
         "call": {"status": "fact", "evidence": [{"file": "flows/daily/morning/news.yaml", "line": 5}]},
         "io": [
             {"op": "read", "status": "fact", "evidence": ev, "resource": {"kind": "filesystem", "levels": {"directory": "notes/news/config", "file": "sources.yaml"}}},
             {"op": "write", "status": "fact", "evidence": ev, "resource": {"kind": "filesystem", "levels": {"directory": "notes/news/daily", "file": "picks.md"}}},
             {"op": "append", "status": "interpretation", "evidence": ev, "resource": {"kind": "filesystem", "levels": {"directory": "notes/news/daily", "file": "picks.md"}}},
             {"op": "list", "status": "unknown", "reason": "generated_at_runtime", "resource": {"kind": "filesystem", "levels": {"directory": "notes/news/daily"}}},
             {"op": "publish", "status": "fact", "evidence": ev, "resource": {"kind": "queue", "levels": {"broker": "redis", "topic": "news"}}},
             {"op": "set", "status": "fact", "evidence": ev, "resource": {"kind": "kvs", "levels": {"host": "redis", "key_pattern": "news:*"}}},
             {"op": "read", "status": "fact", "evidence": ev, "resource": {"kind": "rdb", "levels": {"database": "ops_logs", "table": "job_runs"}}},
             {"op": "update", "status": "fact", "evidence": ev, "resource": {"kind": "rdb", "levels": {"database": "ops_logs", "table": "job_runs"}}},
         ]},
    ]
    return r


@pytest.fixture(scope="module")
def repo(tmp_path_factory) -> Path:
    repo = tmp_path_factory.mktemp("nav-repo")
    init_repo(repo, "batch-kestra", targets="claude-code")
    an = repo / ANALYSIS_DIR
    base = yaml.safe_load((FIX / "result-housekeeping.yaml").read_text(encoding="utf-8"))
    (an / "results" / "daily.housekeeping.yaml").write_text(yaml.safe_dump(base, allow_unicode=True, sort_keys=False), encoding="utf-8")
    (an / "results" / "daily.morning.news.yaml").write_text(yaml.safe_dump(_second_result(base), allow_unicode=True, sort_keys=False), encoding="utf-8")
    (an / "entry-list.yaml").write_text(yaml.safe_dump(_entry_list(base["target"]), allow_unicode=True, sort_keys=False), encoding="utf-8")
    rep = build_repo(repo)
    assert rep["dbt_ok"] == rep["dbt_nodes"], rep
    return repo


def client(repo: Path) -> TestClient:
    return TestClient(create_app(repo), base_url=LOCAL)


# ---------------------------------------------------------------- 形式: 種類ごとの操作

def test_every_kind_declares_ops_with_unique_letters():
    kinds = vocab("resource-kinds")["kinds"]
    assert set(kinds) == {"rdb", "kvs", "queue", "filesystem", "object_storage", "external_api"}
    for k, spec in kinds.items():
        ops = spec["ops"]
        assert ops, k
        assert len({o["letter"] for o in ops}) == len(ops), f"{k}: 1 文字が重複"
        assert all(o["direction"] in ("in", "out") for o in ops), k
        if spec.get("repeat"):
            assert spec["repeat"] in spec["levels"], k


def test_op_must_belong_to_the_kind():
    profile = yaml.safe_load((Path(__file__).resolve().parent.parent / "profiles/batch-kestra/profile.yaml").read_text(encoding="utf-8"))
    base = yaml.safe_load((FIX / "result-housekeeping.yaml").read_text(encoding="utf-8"))
    assert validate_analysis_result(base, profile) == []
    r = _second_result(base)
    assert validate_analysis_result(r, profile) == []
    bad = copy.deepcopy(r)
    bad["callstack"][1]["io"][0]["op"] = "create"  # ファイルに create は無い (write を使う)
    findings = validate_analysis_result(bad, profile)
    assert any("操作 'create' は filesystem では使えない" in f for f in findings), findings
    assert any("'create' は filesystem では使えない" in e for e in result_errors(bad)), "ETL も同じ検査をする"
    bad2 = copy.deepcopy(r)
    bad2["callstack"][1]["io"][4]["op"] = "read"  # キューに read は無い
    assert any("'read' は queue では使えない" in f for f in validate_analysis_result(bad2, profile))


def test_etl_adds_letter_rank_and_direction():
    base = yaml.safe_load((FIX / "result-housekeeping.yaml").read_text(encoding="utf-8"))
    rows = build_rows({"entries": []}, [_second_result(base)])
    io = {(r["kind"], r["op"]): r for r in rows["io"]}
    assert io[("filesystem", "write")]["op_letter"] == "W" and io[("filesystem", "write")]["op_direction"] == "out"
    assert io[("filesystem", "read")]["op_letter"] == "R" and io[("filesystem", "read")]["op_direction"] == "in"
    assert io[("filesystem", "list")]["op_direction"] == "in"
    assert io[("queue", "publish")]["op_letter"] == "P" and io[("kvs", "set")]["op_letter"] == "S"
    assert io[("filesystem", "read")]["op_rank"] < io[("filesystem", "write")]["op_rank"] < io[("filesystem", "append")]["op_rank"]
    assert io[("filesystem", "write")]["resource_path"] == "/filesystem/notes/news/daily/picks.md"


# ---------------------------------------------------------------- プロファイルの階層ラベル

@pytest.mark.parametrize("labels, ok", [(["namespace+", "flow"], True), (["a", "b", "c"], True), (["dir+"], True), (["sys", "area+", "job"], True),
                                        (["a+", "b+"], False), (["area+", "category", "job"], False), ([""], False), (["+"], False), ("namespace", False)])
def test_hierarchy_labels_allow_one_repeated_level(labels, ok):
    assert (hierarchy_label_problems(labels) == []) == ok, labels


def test_profile_hierarchy_is_valid_and_repeats_namespace():
    profile = yaml.safe_load((Path(__file__).resolve().parent.parent / "profiles/batch-kestra/profile.yaml").read_text(encoding="utf-8"))
    assert validate_profile(profile) == []
    assert profile["hierarchy"]["level_labels"] == ["namespace+", "flow"]
    bad = copy.deepcopy(profile)
    bad["hierarchy"]["level_labels"] = ["a+", "b+"]
    assert any("繰り返す段" in f for f in validate_profile(bad))


# ---------------------------------------------------------------- 宣言: subject / title / hint / keys.kind

def test_declaration_subject_title_hint_are_checked():
    cols = {"path", "resource_path", "ops", "has_unknown", "kind", "n"}
    ok = {"origin": "core", "view": "matrix", "level": "path", "subject": "data", "title": "読み書きするデータ", "hint": "行が入口",
          "keys": {"row": "path", "col": "resource_path", "value": "ops", "flag": "has_unknown", "kind": "kind"}}
    assert check_declaration("m", ok, cols) == []
    assert any("subject 'thing'" in p for p in check_declaration("m", {**ok, "subject": "thing"}, cols))
    assert any("title は空でない" in p for p in check_declaration("m", {**ok, "title": " "}, cols))
    no_kind = {**ok, "keys": {k: v for k, v in ok["keys"].items() if k != "kind"}}
    assert any("keys.kind" in p for p in check_declaration("m", no_kind, cols)), "subject data の matrix は種類の列が要る"
    assert SUBJECTS == {"entry", "data", "external", "frame", "aspect", "analysis"}


def test_core_marts_cover_every_subject_and_have_titles(repo: Path):
    marts = client(repo).get("/marts").json()
    core = [m for m in marts if m["declaration"]["origin"] == "core"]
    assert {m["declaration"].get("subject") for m in core} - {None} == SUBJECTS
    # 区分 (subject) を持たない core の表は、画面が表示の種類 (layers) か印 (within) で引くものだけ (ナビには出ない)
    assert sorted((m["declaration"]["view"], m["declaration"].get("tags", [])) for m in core if "subject" not in m["declaration"]) == [("layers", []), ("table", ["within"])]
    for m in core:
        assert m["declaration"].get("title") and m["declaration"].get("hint"), m["name"]
    data = [m for m in core if m["declaration"].get("subject") == "data"]
    assert len(data) == 1 and data[0]["declaration"]["view"] == "matrix" and data[0]["declaration"]["keys"]["kind"] == "kind"


def test_target_meta_name_falls_back_to_repo_tail():
    from abatlas.declarations import target_meta

    assert target_meta({"repo": "github.com/org/shop.git", "commit": "abc1234"}) == {"name": "shop", "repo": "github.com/org/shop.git", "commit": "abc1234"}
    assert target_meta({"repo": "org/shop/", "name": "店のバッチ"})["name"] == "店のバッチ", "表示名があれば優先"
    assert target_meta(None) is None and target_meta({}) is None


# ---------------------------------------------------------------- DuckDB の meta と API

def test_meta_exposes_profile_hierarchy_and_vocabulary(repo: Path):
    meta = client(repo).get("/meta").json()
    assert meta["profile"]["id"] == "batch-kestra"
    assert meta["profile"]["hierarchy"]["level_labels"] == ["namespace+", "flow"]
    layers = meta["profile"]["layers"]
    assert [t["id"] for t in layers] == ["scheduler", "shell", "agent_skill", "program", "external"], "層の並びはプロファイルの順"
    assert layers[0]["role"] == "entry" and layers[-1]["role"] == "boundary" and "io" not in layers[0], "画面に要る項目だけを出す"
    assert layers[0]["tier"] == "scheduler" and layers[1]["tier"] == layers[-1]["tier"] == "job", "tier (architecture の図の枠)"
    assert meta["terms"]["entry"] == "entry point" and meta["terms"]["frame"] == "function", "用語集 (概念 → 呼び名)。画面はここから呼び名を引く"
    assert meta["target"]["name"] and meta["target"]["repo"] and len(meta["target"]["commit"]) >= 7, "分析対象の名前 (画面の見出しとタブ)"
    assert "missing_terms" not in meta, "集計したての集計表は、今の用語集の id をすべて持つ"

    assert meta["profile"]["label"].endswith("→ datastore)"), "プロファイルの表示項目の {id} は、用語集の呼び名に置き換えて出す"
    marts = {m["name"]: m for m in client(repo).get("/marts").json()}
    eo = marts["mart_entry_overview"]
    assert eo["declaration"]["title"] == "entry point overview" and eo["declaration"]["labels"]["path"] == "entry point", "宣言の {id} も置き換えて配る"
    assert eo["declaration"]["filters"][0]["label"] == "analyzed" and "{" not in eo["description"]
    fs = meta["resource_kinds"]["filesystem"]
    assert fs["levels"] == ["host", "directory", "file"] and fs["repeat"] == "directory"
    assert [o["letter"] for o in fs["ops"]] == ["R", "W", "A", "D", "L"]


def test_layer_flow_aggregates_calls_and_io_by_layer(repo: Path):
    """層のつながり: 呼び出しは 層 → 層、読み書きは 層 → / + データの種類。構成のページの図の線になる。"""
    c = client(repo)
    lm = next(m for m in c.get("/marts").json() if m["declaration"]["view"] == "layers")
    assert lm["declaration"]["keys"]["status"] == "status", "確かめられていない箇所を含む線の印 (図は点線)"
    flow = c.get(f"/marts/{lm['name']}/rows").json()["rows"]
    assert all(r["status"] == ("unknown" if r["unknowns"] else "known") and 0 <= r["unknowns"] <= r["calls"] for r in flow)
    assert "subject" not in lm["declaration"], "ナビの区分には出さない"
    layer_ids = {t["id"] for t in c.get("/meta").json()["profile"]["layers"]}
    kinds = set(c.get("/meta").json()["resource_kinds"])
    rows = c.get(f"/marts/{lm['name']}/rows").json()["rows"]
    calls = [r for r in rows if r["edge_kind"] == "call"]
    ios = [r for r in rows if r["edge_kind"] == "io"]
    assert calls and ios
    assert all(r["from_node"] in layer_ids and r["to_node"] in layer_ids for r in calls)
    assert all(r["from_node"] in layer_ids and r["to_node"].startswith("/") and r["to_node"][1:] in kinds for r in ios)
    assert all(r["calls"] >= r["entries"] >= 1 for r in rows)
    assert len({(r["from_node"], r["to_node"], r["edge_kind"]) for r in rows}) == len(rows), "1 つのつながりは 1 行"
    seq = next(m for m in c.get("/marts").json() if m["declaration"]["view"] == "sequence")
    n_io = sum(1 for r in c.get(f"/marts/{seq['name']}/rows", params={"limit": 10000}).json()["rows"] if r["message_kind"] == "io")
    assert sum(r["calls"] for r in ios) == n_io, "読み書きの箇所の合計は、処理の流れの読み書きの数と同じ"


def test_data_access_mart_orders_letters_by_vocabulary(repo: Path):
    c = client(repo)
    da = next(m for m in c.get("/marts").json() if m["declaration"].get("subject") == "data")
    rows = c.get(f"/marts/{da['name']}/rows", params={"path": "/daily/morning/news"}).json()["rows"]
    by = {(r["kind"], r["resource_path"]): r for r in rows}
    assert by[("filesystem", "/filesystem/notes/news/daily/picks.md")]["ops"] == "WA", "語彙の並び順 (R W A D L) で連ねる"
    assert by[("rdb", "/rdb/ops_logs/job_runs")]["ops"] == "RU"
    assert by[("queue", "/queue/redis/news")]["ops"] == "P" and by[("kvs", "/kvs/redis/news:*")]["ops"] == "S"
    assert by[("filesystem", "/filesystem/notes/news/daily")]["has_unknown"] is True
    assert all(r["kind"] != "external_api" for r in c.get(f"/marts/{da['name']}/rows").json()["rows"]), "外部 API は読み書きの表に出さない"


def test_dataflow_direction_follows_vocabulary(repo: Path):
    c = client(repo)
    g = next(m for m in c.get("/marts").json() if m["declaration"]["view"] == "graph")
    rows = c.get(f"/marts/{g['name']}/rows", params={"path": "/daily/morning/news"}).json()["rows"]
    by_op = {(r["kind"], r["op"]): r for r in rows}
    assert by_op[("filesystem", "read")]["from_node"].startswith("/filesystem/") and by_op[("filesystem", "read")]["to_node"] == "/daily/morning/news"
    assert by_op[("filesystem", "write")]["from_node"] == "/daily/morning/news"
    assert by_op[("queue", "publish")]["from_node"] == "/daily/morning/news" and by_op[("filesystem", "list")]["to_node"] == "/daily/morning/news"


def test_contains_filter_is_case_insensitive_and_escaped(repo: Path):
    c = client(repo)
    ov = next(m for m in c.get("/marts").json() if m["declaration"].get("subject") == "entry" and m["declaration"]["view"] == "table")
    assert c.get(f"/marts/{ov['name']}/rows", params={"path__contains": "MORNING"}).json()["total"] == 1
    assert c.get(f"/marts/{ov['name']}/rows", params={"path__contains": "%"}).json()["total"] == 0, "% は文字として扱う"
    assert c.get(f"/marts/{ov['name']}/rows", params={"nope__contains": "x"}).status_code == 400


def test_tree_returns_children_with_counts(repo: Path):
    c = client(repo)
    ov = next(m for m in c.get("/marts").json() if m["declaration"].get("subject") == "entry" and m["declaration"]["view"] == "table")
    top = c.get(f"/marts/{ov['name']}/tree", params={"col": "path"}).json()["children"]
    assert [x["name"] for x in top] == ["daily", "weekly"]
    daily = next(x for x in top if x["name"] == "daily")
    assert daily["key"] == "/daily" and daily["leaves"] == 2 and daily["is_leaf"] is False
    under = c.get(f"/marts/{ov['name']}/tree", params={"col": "path", "under": "/daily"}).json()["children"]
    assert {x["name"]: x["is_leaf"] for x in under} == {"housekeeping": True, "morning": False}
    # データの階層: 種類で絞り、入口の相異なる数を distinct で数える
    da = next(m for m in c.get("/marts").json() if m["declaration"].get("subject") == "data")
    fs = c.get(f"/marts/{da['name']}/tree", params={"col": "resource_path", "under": "/filesystem", "kind": "filesystem", "flag": "has_unknown", "distinct": "path"}).json()["children"]
    assert [x["name"] for x in fs] == ["notes"]
    assert fs[0]["distinct"] == 1 and fs[0]["has_flag"] is True
    assert c.get(f"/marts/{da['name']}/tree", params={"col": "nope"}).status_code == 400


def test_pivot_folds_letters_in_vocabulary_order(repo: Path):
    c = client(repo)
    da = next(m for m in c.get("/marts").json() if m["declaration"].get("subject") == "data")
    k = da["declaration"]["keys"]
    body = {"row": k["row"], "col": k["col"], "value": k["value"], "flag": k["flag"],
            "row_keys": ["/daily", "/daily/morning/news"], "col_keys": ["/filesystem", "/filesystem/notes/news/daily"], "filters": {k["kind"]: "filesystem"}}
    res = c.post(f"/marts/{da['name']}/pivot", json=body).json()
    assert res["letters"] == "RWADL"
    cells = {(x["row"], x["col"]): x for x in res["cells"]}
    assert cells[("/daily", "/filesystem")]["value"] == "RWADL", "畳んだ節は配下の和集合 (housekeeping の D も含む)。語彙の並び順"
    assert cells[("/daily", "/filesystem")]["flag"] is True
    assert cells[("/daily/morning/news", "/filesystem/notes/news/daily")]["value"] == "WAL"
    assert ("/daily/morning/news", "/filesystem") in cells and cells[("/daily/morning/news", "/filesystem")]["value"] == "RWAL"
    root = c.post(f"/marts/{da['name']}/pivot", json={**body, "row_keys": ["/"], "col_keys": ["/"]}).json()["cells"]
    assert len(root) == 1 and root[0]["row"] == "/" and root[0]["col"] == "/"
    assert c.post(f"/marts/{da['name']}/pivot", json={**body, "value": "nope"}).status_code == 400
    assert c.post(f"/marts/{da['name']}/pivot", json={**body, "row_keys": "x"}).status_code == 400


def test_fold_rules():
    from decimal import Decimal

    assert _fold([Decimal("1.1"), Decimal("2.2")], None) == pytest.approx(3.3), "DuckDB の DECIMAL も数値として和"
    assert _fold(["CR", "U"], "CRUD") == "CRU"
    assert _fold(["U", "C"], None) == "UC", "並び順が無ければ出現順"
    assert _fold([1, 2, None], None) == 3
    assert _fold(["b", "a", "b"], None) == "a, b"
    assert _fold([None, ""], None) is None


@pytest.mark.parametrize("meta", [
    {"origin": "core", "view": "table", "level": "entry", "subject": [], "keys": {"id": "path"}},
    {"origin": "core", "view": "table", "level": "entry", "keys": {"id": []}},
    {"origin": "core", "view": "table", "level": "entry", "keys": {"id": "path"}, "filters": [{"label": "x", "where": {1: "a"}}]},
    {"origin": "core", "view": "table", "level": "entry", "keys": {"id": "path"}, "filters": [{"label": "x", "where": {"path": ["a"]}}]},
    {"origin": "core", "view": "table", "level": "entry", "keys": {"id": "path"}, "tags": [1]},
    {"origin": "core", "view": "table", "level": "entry", "keys": {"id": "path"}, "show": "path", "labels": [1]},
])
def test_declaration_check_reports_wrong_types_instead_of_crashing(meta):
    """書き間違えた宣言でも例外で止まらず、指摘の一覧を返す (build が利用者向けに出す)。"""
    problems = check_declaration("m", meta, {"path", "n"})
    assert problems, meta


def test_under_boundaries_in_tree_and_pivot(repo: Path):
    """`/daily` の配下に `/daily2` を混ぜない。根 `/` は全部。"""
    c = client(repo)
    ov = next(m for m in c.get("/marts").json() if m["declaration"].get("subject") == "entry" and m["declaration"]["view"] == "table")
    kids = c.get(f"/marts/{ov['name']}/tree", params={"col": "path", "under": "/dail"}).json()["children"]
    assert kids == [], "前方一致ではなく、節の自身か配下"
    da = next(m for m in c.get("/marts").json() if m["declaration"].get("subject") == "data")
    k = da["declaration"]["keys"]
    body = {"row": k["row"], "col": k["col"], "value": k["value"], "row_keys": ["/dail", "/daily"], "col_keys": ["/"], "filters": {}}
    cells = {x["row"] for x in c.post(f"/marts/{da['name']}/pivot", json=body).json()["cells"]}
    assert cells == {"/daily"}
    too_many = {**body, "row_keys": [f"/x{i}" for i in range(2001)]}
    assert c.post(f"/marts/{da['name']}/pivot", json=too_many).status_code == 400


def test_meta_reports_terms_missing_from_an_old_build(repo: Path, monkeypatch):
    """配布物の用語集に、この集計表より後で足された id があれば、/meta が missing_terms で知らせる (画面は、集計し直すよう促して止まる)。"""
    from abatlas import schemas

    real = schemas.term_labels()
    monkeypatch.setattr(schemas, "term_labels", lambda: {**real, "added_later": "added later"})
    assert client(repo).get("/meta").json()["missing_terms"] == ["added_later"]
