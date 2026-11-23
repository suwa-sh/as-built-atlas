from pathlib import Path

import yaml

from abatlas.etl import COLUMNS, build_rows, write_seeds

FIX = Path(__file__).resolve().parent / "fixtures"


def _entry_list():
    return {
        "entries": [
            {
                "id": "daily.housekeeping",
                "path": "/daily/housekeeping",
                "layer": "scheduler",
                "status": "approved",
                "source": {"file": "flows/daily/housekeeping.yaml", "line": 1},
                "extractor": "kestra-flows",
            }
        ]
    }


def test_build_rows_from_fixture():
    result = yaml.safe_load(
        (FIX / "result-housekeeping.yaml").read_text(encoding="utf-8")
    )
    rows = build_rows(_entry_list(), [result])
    assert rows["entries"][0]["depth"] == 2
    assert rows["results"][0]["frame_count"] == 6
    assert {f["frame_id"] for f in rows["frames"]} == {
        "flow",
        "run_sh",
        "notify",
        "notify_py",
        "psycopg",
        "psql",
    }
    io = {(r["frame_id"], r["idx"]): r for r in rows["io"]}
    assert io[("psycopg", 0)]["resource_path"] == "/rdb/ops_logs/job_runs"
    assert io[("psycopg", 0)]["lv_database"] == "ops_logs"
    assert io[("notify_py", 0)]["resource_path"] == "/external_api/chat.example"
    unknown = [c for c in rows["claims"] if c["status"] == "unknown"]
    assert {c["reason"] for c in unknown} == {"not_analyzed", "not_traceable_in_repo"}
    assert all(
        c["evidence_count"] >= 1 for c in rows["claims"] if c["status"] != "unknown"
    )


def test_results_analyzed_with_another_profile_version_are_marked_stale():
    """分析の決まりは型の版ごとに変わる。今の版と違う版で分析した結果に印を付ける (包む入口を足す前の結果は、その処理を含んだまま)。"""
    result = yaml.safe_load(
        (FIX / "result-housekeeping.yaml").read_text(encoding="utf-8")
    )
    version = result["analyzer"]["profile"]["version"]
    assert build_rows(_entry_list(), [result])["results"][0]["profile_stale"] == "", (
        "型を渡さなければ判定しない"
    )
    assert (
        build_rows(_entry_list(), [result], {"version": version})["results"][0][
            "profile_stale"
        ]
        == "false"
    )
    assert (
        build_rows(_entry_list(), [result], {"version": version + ".1"})["results"][0][
            "profile_stale"
        ]
        == "true"
    )


def test_write_is_deterministic(tmp_path: Path):
    result = yaml.safe_load(
        (FIX / "result-housekeeping.yaml").read_text(encoding="utf-8")
    )
    rows = build_rows(_entry_list(), [result])
    a = tmp_path / "a"
    b = tmp_path / "b"
    write_seeds(rows, a)
    write_seeds(rows, b)
    for name in COLUMNS:
        assert (a / f"{name}.csv").read_bytes() == (b / f"{name}.csv").read_bytes()
        assert (a / f"{name}.csv").read_text(encoding="utf-8").splitlines()[
            0
        ] == ",".join(COLUMNS[name])
