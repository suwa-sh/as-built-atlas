"""公開サンプル examples/umami-atlas (画面を持つシステムを分析した見本) の検査。

対象 (umami) は同梱しないので、ここで確かめるのは対象が無くても分かることだけ:
形式、プロファイルとの整合、一覧と結果・レビューの対応、手元の情報が残っていないこと、init → build で集計表が埋まること。
根拠の行の実在は、umami を隣に clone して `abatlas validate result --work` で確かめる (examples/umami-atlas/README.md)。
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import duckdb
import pytest
import yaml

from abatlas import ANALYSIS_DIR, REPO_ROOT, duckdb_path
from abatlas.build import build_repo
from abatlas.layout import init_repo
from abatlas.validate import validate_analysis_result, validate_entry_list, validate_review, validate_work_definition

ATLAS = REPO_ROOT / "examples" / "umami-atlas"
AN = ATLAS / ANALYSIS_DIR
PROFILE = yaml.safe_load((REPO_ROOT / "profiles" / "ui-nextjs" / "profile.yaml").read_text(encoding="utf-8"))


def _load(p: Path) -> dict:
    return yaml.safe_load(p.read_text(encoding="utf-8"))


def _results() -> dict[str, dict]:
    return {p.stem: _load(p) for p in sorted((AN / "results").glob("*.yaml"))}


def test_entry_list_is_valid_and_wraps_every_page():
    work, el = _load(AN / "work-definition.yaml"), _load(AN / "entry-list.yaml")
    assert validate_work_definition(work) == [] and validate_entry_list(el, PROFILE) == []
    assert el["target"] == work["target"] and el["profile"] == {"id": "ui-nextjs", "version": PROFILE["version"]}
    layers = [e["layer"] for e in el["entries"]]
    assert (layers.count("page"), layers.count("layout")) == (60, 6) and {e["status"] for e in el["entries"]} == {"approved"}
    by_id = {e["id"]: e for e in el["entries"]}
    assert all(e["within"][0] == "layout_l" for e in el["entries"] if e["layer"] == "page"), "どの画面も、いちばん外の枠を通る"
    assert "within" not in by_id["layout_l"]
    assert by_id["settings.teams.teamId_d"]["within"] == ["layout_l", "layout_l.main_g", "layout_l.main_g.settings"]


def test_results_and_reviews_pass_checks_that_need_no_target():
    el, results = _load(AN / "entry-list.yaml"), _results()
    by_id = {e["id"]: e for e in el["entries"]}
    assert len(results) == 10
    layouts = {i for i, r in results.items() if r["entry"]["layer"] == "layout"}
    assert layouts == {i for i, e in by_id.items() if e["layer"] == "layout"}, "枠は 6 つとも分析済み"
    for eid, r in results.items():
        assert validate_analysis_result(r, PROFILE, None) == [], eid
        assert r["entry"]["id"] == eid and r["entry"]["path"] == by_id[eid]["path"] and r["entry"]["layer"] == by_id[eid]["layer"]
        assert r["entry"]["source"] == by_id[eid]["source"], f"{eid}: 結果の入口の場所が、一覧の入口の場所と違う (別の画面を分析した結果になっている)"
        root = next(f for f in r["callstack"] if f.get("caller") is None)
        assert root["source"]["file"] == by_id[eid]["source"]["file"], f"{eid}: 入口のフレームが、一覧の入口のファイルから始まっていない"
        assert r["target"] == el["target"], eid
        assert r["analyzer"]["profile"] == {"id": "ui-nextjs", "version": PROFILE["version"]}, f"{eid}: 今の決まりで分析した結果だけを置く"
        review = _load(AN / "reviews" / f"{eid}.yaml")
        assert validate_review(review, r) == [], eid
    assert {p.stem for p in (AN / "reviews").glob("*.yaml")} == set(results)


def test_pages_do_not_trace_their_layouts():
    """画面の結果は、枠 (layout ファイル) をフレームにしない。枠の結果は、入口のフレームだけが layout ファイル。"""
    for eid, r in _results().items():
        # external のフレームは「ライブラリを呼んでいる行」が場所になるので、枠の入口では layout ファイルを指すことがある。数えない
        layout_frames = [f["id"] for f in r["callstack"] if Path(f["source"]["file"]).stem == "layout" and f["layer"] != "external"]
        if r["entry"]["layer"] == "page":
            assert layout_frames == [], eid
        else:
            root = next(f for f in r["callstack"] if f.get("caller") is None)
            assert layout_frames == [root["id"]] and root["layer"] == "layout", eid


def test_pages_do_not_repeat_what_their_layouts_draw():
    """枠が直接描く部品 (枠の入口のフレームの直下。例: (main) の App) は、その枠を通る画面の結果に現れない。

    画面が自分でも呼ぶフックや API の受け口 (ログイン確認など) は両方に出てよいので、見るのは「枠の直下の部品のファイル」だけ。
    """
    el, results = _load(AN / "entry-list.yaml"), _results()
    within = {e["id"]: e.get("within", []) for e in el["entries"]}
    drawn_by: dict[str, set[str]] = {}
    for eid, r in results.items():
        if r["entry"]["layer"] != "layout":
            continue
        root = next(f for f in r["callstack"] if f.get("caller") is None)
        drawn_by[eid] = {f["source"]["file"] for f in r["callstack"] if f.get("caller") == root["id"] and f["layer"] == "component"}
    assert "src/app/(main)/App.tsx" in drawn_by["layout_l.main_g"] and "src/app/Providers.tsx" in drawn_by["layout_l"], drawn_by
    checked = 0
    for eid, r in results.items():
        if r["entry"]["layer"] != "page":
            continue
        own = {f["source"]["file"] for f in r["callstack"]}
        for w in within[eid]:
            assert not own & drawn_by[w], f"{eid}: 枠 {w} が描く部品 {sorted(own & drawn_by[w])} を、画面の結果も辿っている"
            checked += 1
    assert checked >= 8


# 手元の環境の絶対パス。URL の形のパス (/api/…、/websites/… など) は分析結果にふつうに現れるので、OS のルート直下の名前で見分ける
_LOCAL_PATH = re.compile(r"(?<![\w.$\]}/-])/(?:Users|home|private|var|tmp|mnt|opt|root|Volumes|workspace|workspaces|ws|srv|etc|usr)/|\b[A-Za-z]:\\|~/", re.A)


def test_no_local_paths_or_target_code_are_shipped():
    files = [p for p in ATLAS.rglob("*") if p.is_file()]
    assert {p.suffix for p in files} <= {".yaml", ".md", "", ".env", ".gitignore"} and not any(p.suffix in (".ts", ".tsx", ".js") for p in files), "対象のコードは入れない"
    for p in files:
        text = p.read_text(encoding="utf-8")
        if p.name == "README.md" and p.parent == ATLAS:
            # 使い方の説明に書く 2 つの場所だけは許す: 試す場所 ~/abatlas-try と、コンテナの中の /ws/analysis
            text = text.replace("~/abatlas-try", "<try>").replace('"$PWD:/ws/analysis" -w /ws/analysis', "<mount>")
        hit = _LOCAL_PATH.search(text)
        assert hit is None, f"{p.relative_to(ATLAS)}: 手元の絶対パスらしい文字列が残っている: {hit.group(0)!r}"
    assert _LOCAL_PATH.search("clone_path: /Users/me/umami") and _LOCAL_PATH.search("at /private/tmp/x") and _LOCAL_PATH.search("C:\\work") and _LOCAL_PATH.search("see ~/src")
    assert not _LOCAL_PATH.search("GET /api/users/[userId] と /home の画面、basePath + /api、`${base}/tmp/x`")
    # 場所を表す項目は、対象のリポジトリからの相対パスだけ
    for eid, r in _results().items():
        claims = [r["summary"]] + [c for f in r["callstack"] for c in [f.get("call"), f.get("summary"), *f.get("io", []), *f.get("parameters", [])] if c]
        paths = [r["entry"]["source"]["file"], *(f["source"]["file"] for f in r["callstack"]), *(ev["file"] for c in claims for ev in c.get("evidence") or [])]
        bad = [x for x in paths if x.startswith(("/", "~", "..")) or ":" in x]
        assert not bad, f"{eid}: 相対パスでない場所 {bad[:3]}"
    assert _load(AN / "work-definition.yaml")["target"]["clone_path"] == "../umami"
    assert "ABATLAS_TARGET=../umami" in (ATLAS / ".env").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def built(tmp_path_factory) -> Path:
    """見本を checkout の外 (tmp) にコピーし、init → build まで通す (対象の clone は集計には要らない)。"""
    repo = tmp_path_factory.mktemp("umami") / "umami-atlas"
    shutil.copytree(ATLAS, repo)
    init_repo(repo, "ui-nextjs", targets="claude-code")
    assert "ABATLAS_TARGET=../umami" in (repo / ".env").read_text(encoding="utf-8")  # 見本の .env は上書きされない
    rep = build_repo(repo)
    assert rep["dbt_ok"] == rep["dbt_nodes"] and rep["stale_results"] == 0, rep
    return repo


def test_marts_show_pages_and_the_layouts_that_wrap_them(built: Path):
    with duckdb.connect(str(duckdb_path(built)), read_only=True) as con:
        assert con.execute("select count(*), sum(analyzed::int) from mart.mart_entry_overview").fetchone() == (66, 10)
        wrap = con.execute("select within_path from mart.mart_entry_within where path = '/settings/teams/[teamId]' order by ord").fetchall()
        assert [w for (w,) in wrap] == ["/(layout)", "/(layout)/(main)", "/(layout)/(main)/settings"]
        (inner,) = con.execute("select count(*) from mart.mart_entry_within where within_path = '/(layout)/(main)' and layer = 'page'").fetchone()
        assert inner == 54
        kinds = {k for (k,) in con.execute("select distinct kind from mart.mart_data_access").fetchall()}
        assert {"rdb", "kvs"} <= kinds
        dbms = {d for (d,) in con.execute("select distinct lv_dbms from staging.stg_io where kind = 'rdb'").fetchall()}
        assert {"postgresql", "clickhouse"} <= dbms, "同じ処理に 2 つの DB 向けの実装がある (両方を読み書きに書く)"
        # 枠の読み書きは枠の入口に 1 回だけあり、枠を通る画面の行には出ない (2 段階認証の表は、ログイン後の枠だけが触る)
        owners = {p for (p,) in con.execute("select distinct path from mart.mart_data_access where resource_path like '%two_factor_backup_code'").fetchall()}
        assert owners == {"/(layout)/(main)"}, owners
