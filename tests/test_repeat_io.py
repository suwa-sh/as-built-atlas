"""同じ入口の中で、同じ処理をもう一度書いたフレームの読み書きを、集計で 2 回数えないこと (stg_io の is_repeat)。

分析の決まりでは、同じ処理は 1 回だけ書く。ただし、呼び出し元が終端になって検査に落ちるときは、読み書きを持つ最初のフレームまで、もう一度書く。
その写しの読み書きを、箇所の数に足すと、同じ読み書きを 2 回数えることになる。
"""

import copy
from pathlib import Path

import duckdb
import pytest
import yaml

from abatlas import ANALYSIS_DIR, duckdb_path
from abatlas.build import build_repo
from abatlas.layout import init_repo

from test_webapp import FIX, _entry_list


@pytest.fixture(scope="module")
def repo(tmp_path_factory) -> Path:
    repo = tmp_path_factory.mktemp("repeat-repo")
    init_repo(repo, "batch-kestra", targets="claude-code")
    an = repo / ANALYSIS_DIR
    result = yaml.safe_load((FIX / "result-housekeeping.yaml").read_text(encoding="utf-8"))
    frames = {f["id"]: f for f in result["callstack"]}
    # 写し: notify_py と同じ処理 (定義の場所・名前・層が同じ) を、別の呼び出し元 (run_sh) の下に、もう一度書いたもの。読み書きも同じ
    again = copy.deepcopy(frames["notify_py"])
    again["id"], again["caller"] = "notify_py_rw", "run_sh"
    # 届く先ごとに書いたもの: 同じ処理だが、読み書きの相手が違う。写しではないので、数える
    other = copy.deepcopy(frames["notify_py"])
    other["id"], other["caller"] = "notify_py_other", "run_sh"
    other["io"][0]["resource"] = {"kind": "external_api", "levels": {"host": "other.example"}}
    # 列を持つ読み書きの写し: 値を入れる列 (status → done) と、写しにだけ書いてある列 (note) を持つ
    db_again = copy.deepcopy(frames["psycopg"])
    db_again["id"], db_again["caller"] = "psycopg_rw", "notify"
    db_again["io"][0]["fields"].append({"name": "note", "use": ["write"], "set_to": "copied"})
    # 届く先ごとに書いたものの写し: 最初のフレーム (notify_py) には無い読み書きを、2 つ目 (notify_py_other) と 3 つ目が持つ。3 つ目だけが写し
    other_again = copy.deepcopy(other)
    other_again["id"], other_again["caller"] = "notify_py_other_rw", "notify"
    result["callstack"] += [again, other, db_again, other_again]
    (an / "results" / "daily.housekeeping.yaml").write_text(yaml.safe_dump(result, allow_unicode=True, sort_keys=False), encoding="utf-8")
    (an / "entry-list.yaml").write_text(yaml.safe_dump(_entry_list(result["target"]), allow_unicode=True, sort_keys=False), encoding="utf-8")
    rep = build_repo(repo)
    assert rep["dbt_ok"] == rep["dbt_nodes"], rep
    return repo


def test_a_frame_written_again_is_not_counted_twice(repo: Path):
    with duckdb.connect(str(duckdb_path(repo)), read_only=True) as con:
        flags = dict(con.execute("select frame_id, bool_or(is_repeat) from staging.stg_io group by frame_id").fetchall())
        assert flags["notify_py"] is False and flags["notify_py_rw"] is True, "最初に書いたフレームは数え、もう一度書いたフレームは数えない"
        assert flags["notify_py_other"] is False, "同じ処理でも、読み書きの相手が違えば、写しではない"
        assert flags["notify_py_other_rw"] is True, "最初のフレームに無い読み書きでも、より前のフレームにあれば、写し"
        total, repeats = con.execute("select count(*), sum(is_repeat::int) from staging.stg_io").fetchone()
        assert (total, repeats) == (7, 3)
        (io_count,) = con.execute("select io_count from mart.mart_entry_overview where entry_id = 'daily.housekeeping'").fetchone()
        assert io_count == 4, "入口ごとの読み書きの数は、写しを除く"
        assert con.execute("select sum(io_count) from mart.mart_data_access").fetchone()[0] == con.execute(
            "select count(*) from staging.stg_io where not is_repeat and kind <> 'external_api'").fetchone()[0]
        # 列の読み書き: 箇所は 1 つ。写しにだけ書いてある列も、落とさずに 1 と数える
        fields = dict(con.execute("select field, io_count from mart.mart_field_access where resource_path like '%job_runs'").fetchall())
        assert fields["status"] == 1 and fields["note"] == 1, fields
        # 状態の変化 (status → done) は、写しの分を出さない
        assert con.execute("select count(*) from staging.stg_io_fields where set_to = 'done'").fetchone()[0] == 2
        assert con.execute("select count(*) from staging.stg_io_fields where set_to = 'done' and not is_repeat").fetchone()[0] == 1
        changes = con.execute("select frame_id, io_count from mart.mart_state_changes where field = 'status' and set_to = 'done'").fetchall()
        assert changes == [("psycopg", 1)], changes
        # 写しにだけ書いてある値は、落とさずに出す
        assert con.execute("select frame_id from mart.mart_state_changes where field = 'note' and set_to = 'copied'").fetchall() == [("psycopg_rw",)]
        # プロファイルの集計表 (namespace ごとの内訳) も、写しを除く
        assert con.execute("select sum(rdb_io) from mart.mart_namespace_summary").fetchone()[0] == 1
        # 層のつながり: 外のライブラリから RDB への読み書きは、1 箇所
        assert con.execute("select calls from mart.mart_layer_flow where edge_kind = 'io' and from_node = 'external' and to_node = '/rdb'").fetchone()[0] == 1
        # 経路の表示のために、行そのものは残す (もう一度書いたフレームにも、読み書きが付いたまま)
        assert con.execute("select count(*) from staging.stg_io where frame_id = 'notify_py_rw'").fetchone()[0] == 1
