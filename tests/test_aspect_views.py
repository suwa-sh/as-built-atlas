"""分析の観点のページの前提: 宣言の topic / rollup、表示の種類 heat / bridge、物ごとにまとめる API (groups)。

画面の描画はブラウザで見る (skill dev-webapp-verify)。ここでは、画面が読む宣言と API の約束を確かめる。
"""

import asyncio
from pathlib import Path

import pytest

from abatlas.declarations import TOPICS, VIEWS, check_declaration
from abatlas.mcp_server import in_process_client
from abatlas.api import create_app

from test_webapp import client, repo  # noqa: F401  (同じ見本の分析リポジトリを使う)

OK = {"origin": "core", "view": "table", "level": "entry", "subject": "aspect", "keys": {"id": "k", "path": "path"}}
COLS = {"k", "path", "thing", "sub", "writes", "val"}


def test_topic_and_rollup_are_checked():
    assert check_declaration("m", {**OK, "topic": "access", "rollup": {"by": ["thing", "sub"], "member": "path", "flag": "writes", "chip": "val"}}, COLS) == []
    assert any("topic" in p for p in check_declaration("m", {**OK, "topic": "nope"}, COLS))
    assert any("topic" in p for p in check_declaration("m", {**OK, "topic": []}, COLS)), "文字でない topic も、指摘として返す (例外にしない)"
    flag = {**OK, "rollup": {"by": ["thing"], "member": "path", "flag": "writes"}}
    assert check_declaration("m", flag, COLS, types={"writes": "BOOLEAN"}) == []
    assert any("真偽の列" in p for p in check_declaration("m", flag, COLS, types={"writes": "VARCHAR"}))
    assert any("topic" in p for p in check_declaration("m", {**OK, "subject": "entry", "topic": "access"}, COLS)), "topic は、分析の観点の表にだけ書ける"
    for bad in ({"by": "thing", "member": "path"}, {"by": [], "member": "path"}, {"by": ["thing"]}, {"by": ["thing"], "member": "path", "other": "x"},
                {"by": ["a", "b", "c", "d"], "member": "path"}):
        assert any("rollup は" in p for p in check_declaration("m", {**OK, "rollup": bad}, COLS)), bad
    assert any("rollup の列 'nope'" in p for p in check_declaration("m", {**OK, "rollup": {"by": ["nope"], "member": "path"}}, COLS))


def test_new_views_declare_their_keys():
    assert VIEWS["heat"]["required"] == ["row", "col", "value"] and VIEWS["bridge"]["required"] == ["id", "left", "right"]
    assert "value" in VIEWS["tree"]["optional"]
    heat = {"origin": "core", "view": "heat", "level": "entry", "keys": {"row": "path", "col": "k", "value": "val"}}
    assert check_declaration("m", heat, COLS) == []
    assert any("keys.value" in p for p in check_declaration("m", {**heat, "keys": {"row": "path", "col": "k"}}, COLS))


def test_every_aspect_mart_has_a_topic_and_rollups_point_at_real_columns(repo: Path):  # noqa: F811
    """コアの観点の表は、どれも組を持つ (「そのほか」に落ちない)。rollup の列は、集計の検査が実在を見ている。"""
    marts = [m for m in client(repo).get("/marts").json() if m["declaration"].get("subject") == "aspect"]
    assert marts and {m["declaration"].get("topic") for m in marts} == TOPICS, "5 つの組が、どれも 1 つ以上の表を持つ"
    for m in marts:
        cols = {c["name"] for c in m["columns"]}
        r = m["declaration"].get("rollup")
        if r:
            assert m["declaration"]["view"] == "table" and {*r["by"], r["member"]} <= cols, m["name"]
    views = {m["declaration"]["view"] for m in marts}
    assert {"heat", "bridge", "tree", "table"} <= views


def test_groups_roll_rows_up_to_things(repo: Path):  # noqa: F811
    c = client(repo)
    m = next(x for x in c.get("/marts").json() if x["declaration"].get("rollup") and c.get(f"/marts/{x['name']}/rows").json()["total"])
    r = m["declaration"]["rollup"]
    rows = c.get(f"/marts/{m['name']}/rows", params={"limit": 10000}).json()["rows"]
    g = c.get(f"/marts/{m['name']}/groups", params={"by": r["by"][0], "member": r["member"]}).json()
    keys = {str(x[r["by"][0]] if x[r["by"][0]] is not None else "") for x in rows}
    assert g["total"] == len(keys) and {x["key"] for x in g["groups"]} == keys
    assert g["member_total"] == len({x[r["member"]] for x in rows})
    for x in g["groups"]:
        mine = [y for y in rows if str(y[r["by"][0]] if y[r["by"][0]] is not None else "") == x["key"]]
        assert x["rows"] == len(mine) and x["members"] == len({y[r["member"]] for y in mine})
    assert [x["members"] for x in g["groups"]] == sorted((x["members"] for x in g["groups"]), reverse=True), "既定は、多い順"
    # 並び順、部分一致、読み継ぎ
    by_key = c.get(f"/marts/{m['name']}/groups", params={"by": r["by"][0], "order": "key", "limit": 1}).json()
    assert by_key["groups"][0]["key"] == min(keys) and by_key["total"] == len(keys)
    some = next(k for k in keys if k)
    hit = c.get(f"/marts/{m['name']}/groups", params={"by": r["by"][0], "q": some.upper()}).json()
    assert some in {x["key"] for x in hit["groups"]}, "q は、大文字と小文字を区別しない部分一致"
    # 誤った指定は 400
    assert c.get(f"/marts/{m['name']}/groups", params={"by": "nope"}).status_code == 400
    assert c.get(f"/marts/{m['name']}/groups", params={"by": r["by"][0], "order": "x"}).status_code == 400
    assert c.get(f"/marts/{m['name']}/groups", params={"by": r["by"][0], "flag": r["by"][0]}).status_code == 400, "flag は、真偽の列だけ"


def test_empty_filter_selects_rows_without_a_value(repo: Path):  # noqa: F811
    c = client(repo)
    m = next(x for x in c.get("/marts").json() if x["declaration"]["keys"].get("summary"))
    col = m["declaration"]["keys"]["summary"]
    rows = c.get(f"/marts/{m['name']}/rows", params={"limit": 10000}).json()["rows"]
    empty = [x for x in rows if x[col] in (None, "")]
    assert empty, "見本に、要約の無い入口 (未分析) がある"
    assert c.get(f"/marts/{m['name']}/rows", params={f"{col}__empty": "1"}).json()["total"] == len(empty)


def test_mcp_groups_like_the_api(repo: Path):  # noqa: F811
    api = in_process_client(create_app(repo))
    m = next(x for x in asyncio.run(api.list_marts()) if x["declaration"].get("rollup"))
    r = m["declaration"]["rollup"]
    g = asyncio.run(api.group_mart(m["name"], r["by"][0], r["member"]))
    assert g["by"] == r["by"][0] and "groups" in g and "member_total" in g
