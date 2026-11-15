"""mart 宣言 (dbt model の meta.abatlas) の検査と、DuckDB の中の meta (宣言・プロファイル・語彙)。

webapp と MCP は宣言しか読まないので、宣言が形式に合い、keys が指す列が実在することを build のときに確かめる。
検査は決定論 (manifest と DuckDB の information_schema だけを見る)。
build は検査に通った宣言と、プロファイルの階層ラベル・データの種類の語彙を、集計表と同じ DuckDB の `meta` スキーマに書く。
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb

from .schemas import TERM_REF, resolve_terms, term_labels, term_refs  # noqa: F401  (TERM_REF はテストが使う)

# keys.path は全 view で任意: 入口の画面がその列 (入口の階層パス) で節に絞る。matrix は row、stat / tree は group でも絞れる
# table の label = 人が読む名前の列、summary = 1 行の要約の列、members = 関係する入口のパスを ", " で連ねた列 (外部接続・共有処理の表が持つ)
VIEWS: dict[str, dict[str, list[str]]] = {
    # order = 行の並び順の列。source = 定義場所 (ファイル) の列: 共有処理の表が持つと、画面は同じ名前で定義場所の違う処理を取り違えない
    "table": {"required": ["id"], "optional": ["path", "label", "summary", "members", "order", "source"]},
    "matrix": {"required": ["row", "col", "value"], "optional": ["flag", "kind", "path"]},
    "graph": {"required": ["from", "to"], "optional": ["label", "status", "path"]},
    # 層のつながりの図 (構成のページと同じ図)。from = 層の id、to = 層の id か "/" + データの種類、label = 箇所の数。層どうしのつながりの表だけが使う
    "layers": {"required": ["from", "to"], "optional": ["label", "status"]},
    # node = そのメッセージを起こした処理の id (tree の id と対応する列)、evidence = 根拠の場所 (file:line) の列。画面はこの 2 つで「入口から終点までの経路」を引く
    "sequence": {"required": ["group", "seq", "from", "to"], "optional": ["label", "status", "path", "node", "evidence"]},
    # source = 定義場所 (file:line) の列、tag = 処理の種類 (層など) の短い札の列
    "tree": {"required": ["id", "parent", "label"], "optional": ["group", "detail", "path", "source", "tag"]},
    "stat": {"required": ["value"], "optional": ["group", "total", "path"]},
}
ORIGINS = {"core", "profile", "repo"}
LEVELS = {"entry", "path"}
ATTACH = {"any", "root", *(f"level{i}" for i in range(1, 6))}
TAGS = {"monitor", "within"}  # within = 入口を包む入口の表 (入口の詳細の画面が、包む入口・中で動く入口のカードに使う)
# この表が何についての表か。webapp のナビの区分 (その区分の表が無ければ区分は出ない)
SUBJECTS = {"entry", "data", "external", "frame", "analysis"}
TEXT_FIELDS = ("title", "hint")
FILTER_SUFFIXES = ("__prefix", "__under", "__contains", "__min", "__max")

def declaration_texts(meta: dict) -> list[tuple[str, str]]:
    """宣言のうち画面に出る文字 (どこか, 文字)。"""
    out = [(f, meta[f]) for f in TEXT_FIELDS if isinstance(meta.get(f), str)]
    if isinstance(meta.get("labels"), dict):
        out += [(f"labels.{c}", v) for c, v in meta["labels"].items() if isinstance(v, str)]
    if isinstance(meta.get("filters"), list):
        out += [(f"filters[{i}].label", f["label"]) for i, f in enumerate(meta["filters"]) if isinstance(f, dict) and isinstance(f.get("label"), str)]
    return out


def resolve_declaration(meta: dict, terms: dict[str, str]) -> dict:
    """宣言の文字の "{id}" を呼び名に置き換えた写し。画面と MCP へはこれを配る。"""
    out = dict(meta)
    for f in TEXT_FIELDS:
        if isinstance(out.get(f), str):
            out[f] = resolve_terms(out[f], terms)
    if isinstance(out.get("labels"), dict):
        out["labels"] = {c: resolve_terms(v, terms) if isinstance(v, str) else v for c, v in out["labels"].items()}
    if isinstance(out.get("filters"), list):
        out["filters"] = [{**f, "label": resolve_terms(f["label"], terms)} if isinstance(f, dict) and isinstance(f.get("label"), str) else f for f in out["filters"]]
    return out


def declared_models(manifest: dict) -> list[dict]:
    """manifest の model のうち meta.abatlas を持つもの (名前・宣言・relation)。"""
    out = []
    for n in manifest.get("nodes", {}).values():
        if n.get("resource_type") != "model":
            continue
        holders = [n.get("meta") or {}, (n.get("config") or {}).get("meta") or {}]
        if not any("abatlas" in h for h in holders):
            continue
        meta = next(h["abatlas"] for h in holders if "abatlas" in h)  # 空の宣言 ({}) も拾い、検査で指摘する
        out.append({"name": n["name"], "description": n.get("description", ""), "declaration": meta,
                    "relation": {"schema": n.get("schema"), "alias": n.get("alias") or n["name"]},
                    "dir": _model_dir(n)})
    return sorted(out, key=lambda m: m["name"])


def _model_dir(node: dict) -> str | None:
    """model の定義の置き場所 (models/ の直下のディレクトリ名: core / profile / repo / staging …)。分からなければ None。"""
    parts = Path(str(node.get("original_file_path") or "")).parts
    if "models" in parts and len(parts) > parts.index("models") + 2:
        return parts[parts.index("models") + 1]
    return None


def origin_problems(models: list[dict]) -> list[str]:
    """宣言の origin (集計表の持ち主) が、定義の置き場所 (models/core | profile | repo) と合っていること。

    置き場所が、3 つのどれでもない・分からない model は見ない。origin そのものの検査は check_declaration が行う。
    """
    out = []
    for m in models:
        origin = m["declaration"].get("origin") if isinstance(m["declaration"], dict) else None
        if m.get("dir") in ORIGINS and origin in ORIGINS and origin != m["dir"]:
            out.append(f"{m['name']}: origin '{origin}' が、定義の置き場所 models/{m['dir']}/ と合わない (origin: {m['dir']} と書くか、定義を models/{origin}/ に置く)")
    return out


def check_declaration(name: str, meta, columns: set[str] | None, description: str | None = None) -> list[str]:
    """1 つの宣言の指摘。columns を渡すと keys の列の実在も見る。description (model の説明) を渡すと、その用語の差し込み口も見る。"""
    problems = []
    if isinstance(description, str):
        known = term_labels()
        problems += [f"{name}: description の用語 '{{{ref}}}' が用語集に無い (schema/vocab/terms.yaml)" for ref in term_refs(description) if ref not in known]
    if not isinstance(meta, dict):
        return [f"{name}: meta.abatlas は対応表でなければならない"]
    view = meta.get("view")
    if view not in VIEWS:
        return [f"{name}: view '{view}' は {sorted(VIEWS)} のどれでもない"]
    if meta.get("origin") not in ORIGINS:
        problems.append(f"{name}: origin '{meta.get('origin')}' は {sorted(ORIGINS)} のどれでもない")
    if meta.get("level") not in LEVELS:
        problems.append(f"{name}: level '{meta.get('level')}' は {sorted(LEVELS)} のどれでもない")
    if meta.get("attach", "any") not in ATTACH:
        problems.append(f"{name}: attach '{meta.get('attach')}' は {sorted(ATTACH)} のどれでもない")
    if "subject" in meta and (not isinstance(meta["subject"], str) or meta["subject"] not in SUBJECTS):
        problems.append(f"{name}: subject '{meta.get('subject')}' は {sorted(SUBJECTS)} のどれでもない")
    for f in TEXT_FIELDS:
        if f in meta and (not isinstance(meta[f], str) or not meta[f].strip()):
            problems.append(f"{name}: {f} は空でない文字列")
    terms = term_labels()
    for where, text in declaration_texts(meta):
        for ref in term_refs(text):
            if ref not in terms:
                problems.append(f"{name}: {where} の用語 '{{{ref}}}' が用語集に無い (schema/vocab/terms.yaml)")
    tags = meta.get("tags", [])
    if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags) or not set(tags) <= TAGS:
        problems.append(f"{name}: tags {tags!r} は {sorted(TAGS)} の中から並べる")
    keys = meta.get("keys")
    if not isinstance(keys, dict):
        return problems + [f"{name}: keys が無い (view {view} は {VIEWS[view]['required']} が必須)"]
    if not all(isinstance(k, str) and isinstance(v, str) and v for k, v in keys.items()):
        return problems + [f"{name}: keys は 役割 → 列名 (文字列) の対応表"]
    spec = VIEWS[view]
    for k in spec["required"]:
        if k not in keys:
            problems.append(f"{name}: view {view} に必須の keys.{k} が無い")
    for k in keys:
        if k not in spec["required"] and k not in spec["optional"]:
            problems.append(f"{name}: keys.{k} は view {view} では使わない (使えるのは {spec['required'] + spec['optional']})")
    if meta.get("subject") == "data" and view == "matrix" and "kind" not in keys:
        problems.append(f"{name}: subject data の matrix は keys.kind (データの種類の列) が必須 (画面が種類ごとに表を分ける)")
    # show (一覧に出す列の並び) / labels (列の表示名) / filters (一覧の絞り込みの候補: label と where)
    show = meta.get("show")
    if show is not None and (not isinstance(show, list) or not all(isinstance(c, str) for c in show)):
        problems.append(f"{name}: show は列名の並び")
    labels = meta.get("labels")
    if labels is not None and (not isinstance(labels, dict) or not all(isinstance(v, str) for v in labels.values())):
        problems.append(f"{name}: labels は 列名 → 表示名 の対応表")
    filters = meta.get("filters")
    if filters is not None:
        if not isinstance(filters, list):
            problems.append(f"{name}: filters は並び")
        else:
            for i, f in enumerate(filters):
                if not (isinstance(f, dict) and isinstance(f.get("label"), str) and isinstance(f.get("where"), dict) and f["where"]
                        and all(isinstance(k, str) and isinstance(v, (str, int, float, bool)) for k, v in f["where"].items())):
                    problems.append(f"{name}: filters[{i}] は {{label, where}} (where は 列 → 値 (文字列か数値)。列には __prefix / __under / __contains / __min / __max を付けられる)")
    if columns is not None:
        for k, col in keys.items():
            if col not in columns:
                problems.append(f"{name}: keys.{k} が指す列 '{col}' が mart に無い (列: {sorted(columns)})")
        for col in (show or []) if isinstance(show, list) else []:
            if col not in columns:
                problems.append(f"{name}: show の列 '{col}' が mart に無い")
        for col in (labels or {}) if isinstance(labels, dict) else {}:
            if col not in columns:
                problems.append(f"{name}: labels の列 '{col}' が mart に無い")
        for i, f in enumerate(filters or []) if isinstance(filters, list) else []:
            where = f.get("where") if isinstance(f, dict) and isinstance(f.get("where"), dict) else {}
            for k in where:
                if not isinstance(k, str):
                    continue  # 型の指摘は上で出している
                col = next((k[: -len(sfx)] for sfx in FILTER_SUFFIXES if k.endswith(sfx)), k)
                if col not in columns:
                    problems.append(f"{name}: filters[{i}].where の列 '{col}' が mart に無い")
    return problems


META_SCHEMA = "meta"  # build が DuckDB の中に書き、API が読む (schema 名はカタログ名 abatlas と被らないものにする)
DECLARATIONS_TABLE = (META_SCHEMA, "declarations")  # (schema, table)
META_TABLE = (META_SCHEMA, "atlas")  # key / value (json): profile と resource_kinds と terms


def publish_declarations(con: duckdb.DuckDBPyConnection, models: list[dict]) -> None:
    """検査に通った宣言を DuckDB の表に書く。集計表と同じファイルなので、公開 (ファイルの置き換え) は 1 回で済み、新旧が混ざらない。

    宣言の文字と説明の "{id}" は、ここで用語集の呼び名に置き換える (画面と MCP は置き換えた後の文字だけを見る)。
    """
    terms = term_labels()
    models = [{**m, "description": resolve_terms(m["description"], terms), "declaration": resolve_declaration(m["declaration"], terms)} for m in models]
    sch, tbl = DECLARATIONS_TABLE
    con.execute(f'create schema if not exists "{sch}"')
    con.execute(f'create or replace table "{sch}"."{tbl}" (name varchar primary key, description varchar, rel_schema varchar, rel_alias varchar, declaration json)')
    con.executemany(f'insert into "{sch}"."{tbl}" values (?, ?, ?, ?, ?)',
                    [(m["name"], m["description"], m["relation"]["schema"], m["relation"]["alias"], json.dumps(m["declaration"], ensure_ascii=False)) for m in models])


def target_meta(target: dict | None) -> dict | None:
    """作業定義の対象から、画面に出す項目 (name / repo / commit) を作る。name が無ければ repo の最後の区切りより後ろ (末尾の .git は除く)。"""
    if not isinstance(target, dict) or not target.get("repo"):
        return None
    repo = str(target["repo"])
    tail = repo.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git")
    out = {"name": str(target.get("name") or tail or repo), "repo": repo}
    if target.get("commit"):
        out["commit"] = str(target["commit"])
    return out


def publish_meta(con: duckdb.DuckDBPyConnection, profile: dict, resource_kinds: dict, target: dict | None = None) -> None:
    """プロファイル (id / version / label / hierarchy / layers)、データの種類の語彙、用語集 (概念 → 呼び名)、分析対象 (name / repo / commit) を書く。webapp はナビと見出し、表の凡例にこれを使う。"""
    sch, tbl = META_TABLE
    con.execute(f'create schema if not exists "{sch}"')
    con.execute(f'create or replace table "{sch}"."{tbl}" (key varchar primary key, value json)')
    terms = term_labels()
    rt = lambda v: resolve_terms(v, terms) if isinstance(v, str) else v  # noqa: E731  プロファイルの表示項目の "{id}" を呼び名に置き換える
    prof = {k: profile.get(k) for k in ("id", "version", "label", "hierarchy") if profile.get(k) is not None}
    if "label" in prof:
        prof["label"] = rt(prof["label"])
    if isinstance(prof.get("hierarchy"), dict) and isinstance(prof["hierarchy"].get("notes"), list):
        prof["hierarchy"] = {**prof["hierarchy"], "notes": [{**n, "text": rt(n.get("text"))} if isinstance(n, dict) else n for n in prof["hierarchy"]["notes"]]}
    # 層の並び (構成のページの図)。画面に要る項目だけ (抽出器の設定などは出さない)
    layers = [{k: (rt(t[k]) if k in ("label", "tier") else t[k]) for k in ("id", "label", "role", "tier", "stack", "invokes_next") if t.get(k) is not None}
             for t in profile.get("layers") or [] if isinstance(t, dict) and t.get("id")]
    if layers:
        prof["layers"] = layers
    con.executemany(f'insert into "{sch}"."{tbl}" values (?, ?)',
                    [("profile", json.dumps(prof, ensure_ascii=False)), ("resource_kinds", json.dumps(resource_kinds, ensure_ascii=False)),
                     ("terms", json.dumps(term_labels(), ensure_ascii=False))]
                    + ([("target", json.dumps(target_meta(target), ensure_ascii=False))] if target_meta(target) else []))


def read_declarations(con: duckdb.DuckDBPyConnection) -> dict[str, dict]:
    sch, tbl = DECLARATIONS_TABLE
    rows = con.execute(f'select name, description, rel_schema, rel_alias, declaration from "{sch}"."{tbl}" order by name').fetchall()
    return {r[0]: {"name": r[0], "description": r[1], "declaration": json.loads(r[4]), "relation": {"schema": r[2], "alias": r[3]}} for r in rows}


def read_meta(con: duckdb.DuckDBPyConnection) -> dict:
    sch, tbl = META_TABLE
    try:
        rows = con.execute(f'select key, value from "{sch}"."{tbl}"').fetchall()
    except duckdb.CatalogException:
        return {}
    return {k: json.loads(v) for k, v in rows}


def check_manifest(manifest_path: Path, db_path: Path | None) -> list[str]:
    """build 後の検査。manifest の全宣言を見て、指摘を返す (空なら合格)。"""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    models = declared_models(manifest)
    if not models:
        return ["meta.abatlas を持つ mart が 1 つも無い"]
    con = duckdb.connect(str(db_path), read_only=True) if db_path else None
    try:
        problems = origin_problems(models)
        for m in models:
            cols = None
            if con is not None:
                rel = m["relation"]
                rows = con.execute("select column_name from information_schema.columns where table_schema = ? and table_name = ?",
                                   [rel["schema"], rel["alias"]]).fetchall()
                cols = {r[0] for r in rows}
            problems.extend(check_declaration(m["name"], m["declaration"], cols, m.get("description")))
        return problems
    finally:
        if con is not None:
            con.close()
