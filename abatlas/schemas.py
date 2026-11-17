"""JSON Schema の読み込みと $ref 解決。"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from . import SCHEMA_DIR, VOCAB_DIR

SCHEMA_FILES = {
    "analysis-result": "analysis-result.schema.json",
    "entry-candidate": "entry-candidate.schema.json",
    "entry-list": "entry-list.schema.json",
    "profile": "profile.schema.json",
    "work-definition": "work-definition.schema.json",
    "review": "review.schema.json",
    "data-dictionary": "data-dictionary.schema.json",
}


@lru_cache(maxsize=None)
def _registry() -> Registry:
    registry: Registry = Registry()
    for fname in SCHEMA_FILES.values():
        doc = json.loads((SCHEMA_DIR / fname).read_text(encoding="utf-8"))
        resource = Resource.from_contents(doc)
        # $id の絶対 URI と、相対参照 ("work-definition.schema.json#/...") の両方で引けるようにする
        registry = registry.with_resource(doc["$id"], resource)
        registry = registry.with_resource(fname, resource)
    return registry


@lru_cache(maxsize=None)
def validator(name: str) -> Draft202012Validator:
    doc = json.loads((SCHEMA_DIR / SCHEMA_FILES[name]).read_text(encoding="utf-8"))
    return Draft202012Validator(doc, registry=_registry())


def schema_errors(name: str, instance) -> list[str]:
    """schema 違反を人が読める 1 行ずつにして返す (空なら合格)。"""
    out = []
    for err in sorted(validator(name).iter_errors(instance), key=lambda e: list(e.absolute_path)):
        where = "/".join(str(p) for p in err.absolute_path) or "(root)"
        out.append(f"{where}: {err.message}")
    return out


@lru_cache(maxsize=None)
def vocab(name: str) -> dict:
    return yaml.safe_load((VOCAB_DIR / f"{name}.yaml").read_text(encoding="utf-8"))


# 画面に出す文字に書く用語の差し込み口。"{entry}" は用語集 (schema/vocab/terms.yaml) の呼び名に置き換わる。
# 文字どおりの {entry} を出したいときは、前に \\ を付ける ("\\{entry}" → "{entry}")
TERM_REF = re.compile(r"(\\?)\{([a-z][a-z0-9_]*)\}")


def term_labels() -> dict[str, str]:
    """用語集: 概念の id → 画面に出す呼び名。"""
    return {k: v["label"] for k, v in vocab("terms")["terms"].items()}


def term_refs(text: str) -> list[str]:
    """文字の中の差し込み口の id (\\ を付けたものは除く)。"""
    return [m.group(2) for m in TERM_REF.finditer(text) if not m.group(1)]


def resolve_terms(text: str, terms: dict[str, str] | None = None) -> str:
    """文字の中の "{id}" を呼び名に置き換える。用語集に無い id はそのまま残す (検査が指摘する)。"\\{id}" は \\ を外して文字どおり残す。"""
    terms = term_labels() if terms is None else terms
    return TERM_REF.sub(lambda m: "{" + m.group(2) + "}" if m.group(1) else terms.get(m.group(2), m.group(0)), text)


def profile_display_texts(profile: dict) -> list[tuple[str, str]]:
    """プロファイルのうち画面に出る文字 (どこか, 文字)。build が用語を差し込んで /meta に出すもの。"""
    out = []
    if isinstance(profile.get("label"), str):
        out.append(("label", profile["label"]))
    for t in profile.get("layers") or []:
        if isinstance(t, dict):
            out += [(f"layers/{t.get('id')}/{k}", t[k]) for k in ("label", "tier") if isinstance(t.get(k), str)]
    notes = (profile.get("hierarchy") or {}).get("notes") if isinstance(profile.get("hierarchy"), dict) else None
    for i, n in enumerate(notes if isinstance(notes, list) else []):
        if isinstance(n, dict) and isinstance(n.get("text"), str):
            out.append((f"hierarchy/notes/{i}/text", n["text"]))
    return out


def profile_term_problems(profile: dict) -> list[str]:
    """プロファイルの表示項目が指す用語のうち、用語集に無いもの。"""
    known = term_labels()
    return [f"profile: {where}: 用語 '{{{ref}}}' が用語集に無い (schema/vocab/terms.yaml)"
            for where, text in profile_display_texts(profile) for ref in term_refs(text) if ref not in known]


@lru_cache(maxsize=None)
def resource_kinds() -> dict:
    """データの種類の語彙 (種類と操作の label の "{id}" を、用語集の呼び名に置き換えたもの)。"""
    out = {}
    for k, v in vocab("resource-kinds")["kinds"].items():
        out[k] = {**v, "label": resolve_terms(v.get("label", k)), "ops": [{**o, "label": resolve_terms(o.get("label", o["id"]))} for o in v.get("ops", [])]}
    return out


def load_yaml(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))
