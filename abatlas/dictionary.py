"""データの辞書 (analysis/data-dictionary.yaml): 分析結果に出てきた列ごとの区分。

区分 (個人情報など) は分析結果には書かず、ここに 1 回だけ書く。このモジュールは、分析結果に出てきた列を
candidate として足すだけで、区分は決めない (区分の案はエージェントが書き、人が approved にする)。
決定論: 同じ入力なら同じファイル (行は resource → field の順)。
"""

from __future__ import annotations

from pathlib import Path

import yaml

from . import analysis_dir
from .etl import build_rows
from .schemas import load_yaml, schema_errors, vocab

FILE = "data-dictionary.yaml"
HEADER = "# データの辞書。列ごとの区分 (schema/vocab/data-categories.yaml)。abatlas dictionary が列を足し、人が status を approved にする\n"


def dictionary_problems(doc) -> list[str]:
    """形式と意味の検査: 同じ列を 2 回書かない。区分は語彙にある。approved の行は区分を持つ。"""
    problems = [f"{FILE}: {e}" for e in schema_errors("data-dictionary", doc)]
    if problems:
        return problems
    categories = vocab("data-categories")["categories"]
    seen = set()
    for i, f in enumerate(doc["fields"]):
        key = (f["resource"], f["field"])
        where = f"{FILE}: fields/{i} ({f['resource']} の {f['field']})"
        if key in seen:
            problems.append(f"{where}: 同じ列が 2 回書かれている")
        seen.add(key)
        if "category" in f and f["category"] not in categories:
            problems.append(
                f"{where}: 区分 '{f['category']}' が語彙に無い (schema/vocab/data-categories.yaml: {sorted(categories)})"
            )
        if f["status"] == "approved" and "category" not in f:
            problems.append(f"{where}: approved なのに、区分 (category) が無い")
        if f["field"] == "*":
            problems.append(
                f"{where}: * (全部の列) には区分を付けられない。列の名前で書く"
            )
    return problems


def load_dictionary(repo: Path) -> dict:
    """辞書を読む。無ければ空。違反があれば止める。"""
    p = analysis_dir(repo) / FILE
    if not p.is_file():
        return {"format_version": 1, "fields": []}
    doc = load_yaml(p)
    problems = dictionary_problems(doc)
    if problems:
        raise SystemExit(
            "dictionary: 辞書が形式に違反している:\n  " + "\n  ".join(problems[:20])
        )
    return doc


def result_fields(repo: Path) -> list[tuple[str, str]]:
    """分析結果に出てきた (データのパス, 列の名前)。* と、外部 API の項目は除く (外部の接続先は、データの持ち場ではない)。"""
    base = analysis_dir(repo)
    results = [load_yaml(p) for p in sorted((base / "results").glob("*.yaml"))]
    rows = build_rows({"entries": []}, results)["io_fields"]
    return sorted(
        {
            (r["resource_path"], r["name"])
            for r in rows
            if r["name"] != "*" and r["kind"] != "external_api"
        }
    )


def update_dictionary(repo: Path, dry_run: bool = False) -> dict[str, int]:
    """分析結果に出てきた列のうち、辞書に無いものを candidate で足す。既にある行は変えない。分析結果から消えた列の行も残す (数だけ報告する)。"""
    doc = load_dictionary(repo)
    have = {(f["resource"], f["field"]) for f in doc["fields"]}
    found = result_fields(repo)
    added = [k for k in found if k not in have]
    doc["fields"] = sorted(
        doc["fields"]
        + [{"resource": r, "field": f, "status": "candidate"} for r, f in added],
        key=lambda f: (f["resource"], f["field"]),
    )
    if added and not dry_run:
        (analysis_dir(repo) / FILE).write_text(
            HEADER + yaml.safe_dump(doc, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
    return {
        "fields": len(doc["fields"]),
        "added": len(added),
        "unclassified": sum(1 for f in doc["fields"] if "category" not in f),
        "candidate": sum(1 for f in doc["fields"] if f["status"] == "candidate"),
        "not_in_results": len(have - set(found)),
    }
