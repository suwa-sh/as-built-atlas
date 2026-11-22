"""transform-dbt プロファイルを、小さな見本の置き場で確かめる。

既定の抽出器が、model のファイル 1 つを入口 1 件にし、snapshot を別の階層に置くこと。
"""

from pathlib import Path

import yaml

from abatlas.enumerate import enumerate_entries
from abatlas.layout import init_repo
from abatlas.validate import validate_entry_list, validate_profile

REPO_ROOT = Path(__file__).resolve().parent.parent
PROFILE = REPO_ROOT / "profiles" / "transform-dbt" / "profile.yaml"

# 架空の題材。(ファイル, 中身)
FILES = {
    "dbt_project.yml": "name: kotori\nmodel-paths: [models]\n",
    "models/staging/stg_orders.sql": "select order_id, amount from {{ source('shop', 'orders') }}\n",
    "models/staging/schema.yml": "version: 2\nmodels: []\n",
    "models/marts/sales/fct_daily_sales.sql": "{{ config(materialized='incremental') }}\nselect * from {{ ref('stg_orders') }}\n",
    "models/top_level.sql": '{{ config(materialized = "ephemeral") }}\nselect 1 as one\n',
    "snapshots/orders_history.sql": "{# 履歴 #}\n{% snapshot orders_history %}\nselect * from {{ source('shop', 'orders') }}\n{% endsnapshot %}\n",
    "macros/cents.sql": "{% macro cents(c) %}{{ c }} * 100{% endmacro %}\n",  # macro は入口ではない
    "seeds/tax_rates.csv": "rate\n0.1\n",  # seed は入口ではない
}


def test_profile_is_valid():
    assert validate_profile(yaml.safe_load(PROFILE.read_text(encoding="utf-8"))) == []


def test_models_and_snapshots_become_entries(tmp_path: Path):
    target = tmp_path / "target"
    for rel, text in FILES.items():
        p = target / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    repo = tmp_path / "atlas"
    repo.mkdir()
    init_repo(repo, "transform-dbt", targets="claude-code")
    profile = yaml.safe_load(PROFILE.read_text(encoding="utf-8"))
    exs = []
    for ex in profile["extractors"]:
        ex = {k: v for k, v in ex.items() if k != "hint"}
        ex["rationale"] = "既定の置き場"
        exs.append(ex)
    el_path = repo / "analysis" / "entry-list.yaml"
    el_path.write_text(
        yaml.safe_dump(
            {
                "format_version": 1,
                "target": {
                    "repo": "example/kotori-dbt",
                    "clone_path": str(target),
                    "scope": ".",
                    "commit": "0a1b2c3d4e",
                },
                "profile": {"id": "transform-dbt", "version": profile["version"]},
                "extractors": exs,
                "entries": [],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    enumerate_entries(el_path, PROFILE)
    el = yaml.safe_load(el_path.read_text(encoding="utf-8"))
    assert validate_entry_list(el, profile) == []
    got = {
        e["id"]: (e["path"], e["layer"], e["source"]["file"], e["source"]["line"])
        for e in el["entries"]
    }
    assert got == {
        "staging.stg_orders": (
            "/staging/stg_orders",
            "model",
            "models/staging/stg_orders.sql",
            1,
        ),
        "marts.sales.fct_daily_sales": (
            "/marts/sales/fct_daily_sales",
            "model",
            "models/marts/sales/fct_daily_sales.sql",
            1,
        ),
        "top_level": ("/top_level", "model", "models/top_level.sql", 1),
        "snapshot.orders_history": (
            "/(snapshot)/orders_history",
            "model",
            "snapshots/orders_history.sql",
            2,
        ),  # 行は、snapshot の始まり
    }
    flags = {
        e["id"]: (e["attributes"].get("incremental"), e["attributes"].get("ephemeral"))
        for e in el["entries"]
    }
    assert flags["marts.sales.fct_daily_sales"] == (True, False)
    assert flags["top_level"] == (False, True)
    assert flags["staging.stg_orders"] == (False, False)
