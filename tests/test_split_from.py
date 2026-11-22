"""別の入口に分けられる層 (profile.yaml の split_from) の検査と、集計への渡し方。

集計表「別の入口に分ける候補」は、ここに挙がった層のフレームだけを出す。
どの入口も通るサーバー側の確認などは、大きくても、入口に分けられないので、出さない。
"""

import copy
from pathlib import Path

import pytest
import yaml

from abatlas.etl import build_rows
from abatlas.validate import validate_profile

from test_result_aspects import _entries

ROOT = Path(__file__).resolve().parent.parent
FIX = Path(__file__).resolve().parent / "fixtures"
UI_PROFILES = ["ui-nextjs", "ui-vue-router", "ui-nuxt", "ui-sveltekit"]


def _profile(pid: str) -> dict:
    return yaml.safe_load(
        (ROOT / "profiles" / pid / "profile.yaml").read_text(encoding="utf-8")
    )


def _layer(profile: dict, lid: str) -> dict:
    return next(t for t in profile["layers"] if t["id"] == lid)


@pytest.mark.parametrize("pid", UI_PROFILES)
def test_ui_profiles_declare_that_parts_are_split_from_components(pid: str):
    profile = _profile(pid)
    assert validate_profile(profile) == []
    assert _layer(profile, "part")["split_from"] == ["component"]


def test_split_from_must_be_on_an_entry_layer_and_name_an_intermediate_layer():
    profile = _profile("ui-nextjs")
    bad = copy.deepcopy(profile)
    _layer(bad, "component")["split_from"] = ["query"]
    assert any("role: entry の層にだけ書ける" in p for p in validate_profile(bad))
    bad = copy.deepcopy(profile)
    _layer(bad, "part")["split_from"] = ["nothing"]
    assert any("未知の層 'nothing'" in p for p in validate_profile(bad))
    bad = copy.deepcopy(profile)
    _layer(bad, "part")["split_from"] = ["external"]
    assert any("role: boundary の層" in p for p in validate_profile(bad))
    bad = copy.deepcopy(profile)
    _layer(bad, "part")["split_from"] = ["page"]
    assert any("role: entry の層" in p for p in validate_profile(bad))


def test_frames_know_whether_their_layer_can_be_split():
    profile = _profile("batch-kestra")
    result = yaml.safe_load(
        (FIX / "result-housekeeping.yaml").read_text(encoding="utf-8")
    )
    layer_of = {f["id"]: f["layer"] for f in result["callstack"]}
    rows = build_rows(_entries(), [result], profile)
    assert {f["splittable"] for f in rows["frames"]} == {"false"}, (
        "分けられる層を決めていないプロファイルでは、どのフレームも分けられない"
    )
    declared = copy.deepcopy(profile)
    entry_layer = next(t for t in declared["layers"] if t.get("role") == "entry")
    entry_layer["split_from"] = [layer_of["run_sh"]]
    assert validate_profile(declared) == []
    flags = {
        f["frame_id"]: f["splittable"]
        for f in build_rows(_entries(), [result], declared)["frames"]
    }
    assert flags["run_sh"] == "true" and flags["psycopg"] == "false"
    assert build_rows(_entries(), [result])["frames"][0]["splittable"] == "", (
        "プロファイルを渡さなければ、判定しない"
    )
