"""構造化データのクエリ抽出器: YAML / JSON / CSV の定義ファイルから入口の候補を出す。

params (JSON):
  files:   glob (scope からの相対)。複数可 (配列)
  format:  yaml | json | csv
  records: JMESPath。1 ファイルを読んだ結果から「入口 1 件 = 1 要素」の配列を取り出す式。
           省略時はドキュメント自身を 1 件とみなす (YAML 1 ファイル = 入口 1 件)。
           csv は常に 1 行 = 1 件 (records は不要)
  where:   JMESPath (任意)。真の要素だけ残す
  fields:  各項目を JMESPath で取り出す。{id, path, name, layer, line_key, attributes: {k: expr}}
           - 式は要素に対して評価する。`$file` (ファイルの相対パス) と `$stem` (拡張子無しの名前) も使える
           - path は "format" 文字列。{field} に fields の値を差し込める。例: "/{namespace_path}/{id}"
           - namespace のような '.' 区切りを '/' にしたいときは fields に "x_path": "replace(...)" のような式は書けないので、
             fields の値に対して post: {field: {"split": ".", "join": "/"}} を書く
  post:    フィールドの後処理 {field: {"split": ".", "join": "/"}}
  line_key: 出典の行を決めるための「ファイル内で探す文字列のキー」。既定は "id"。
            YAML の `key: value` / `- key: value`、JSON の `"key": "value",` の行を探す。同じ値が複数あれば最初の行、
            見つからなければ 1 行目 (パーサーは位置を持たないため、厳密な位置が要る形式は専用パーサーで)。csv は常にそのレコードの行
  allow_empty: true なら、files に一致するファイルが無くても成功 (既定は失敗)
"""

from __future__ import annotations

import csv
import glob
import json
import re
import sys
from pathlib import Path

import jmespath
import yaml


def _load(path: Path, fmt: str):
    text = path.read_text(encoding="utf-8")
    if fmt == "yaml":
        return list(yaml.safe_load_all(text))
    if fmt == "json":
        return [json.loads(text)]
    if fmt == "csv":
        reader = csv.DictReader(text.splitlines())
        rows = []
        for row in reader:
            row["$line"] = reader.line_num  # レコードの (最後の) 物理行。出典の行に使う
            rows.append(row)
        return [rows]
    raise SystemExit(f"unsupported format: {fmt}")


def _find_line(path: Path, key: str, value) -> int:
    """`key: value` (YAML。リスト要素の `- key: value` も) または `"key": "value",` (JSON) の行を探す。
    同じ key と value の行が複数あれば最初の行。見つからなければ 1 (ファイル先頭)。"""
    k, v = re.escape(key), re.escape(str(value))
    pat = re.compile(rf"^\s*-?\s*['\"]?{k}['\"]?\s*[:=]\s*['\"]?{v}['\"]?\s*,?\s*$")
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if pat.match(line):
            return i
    return 1


def _post(value, rule: dict | None):
    if value is None or not rule:
        return value
    if "split" in rule:
        parts = str(value).split(rule["split"])
        value = rule.get("join", "/").join(p for p in parts if p != "")
    return value


def _input_paths(scope, files, params):
    paths = sorted(
        {Path(p) for g in files for p in glob.glob(str(scope / g), recursive=True)}
    )
    if not paths and not params.get("allow_empty"):
        raise SystemExit(
            f"[structured-query] files {files} に一致するファイルが scope に無い (glob の誤り?)。空が正しいなら allow_empty: true"
        )
    return paths


def _records(doc, fmt, records_expr):
    if fmt == "csv":
        items = doc
    elif records_expr:
        items = jmespath.search(records_expr, doc) or []
    else:
        items = [doc]
    return items


def _field_values(item, rel, path, fields, post):
    env = dict(item)
    env["$file"] = rel
    env["$stem"] = path.stem
    vals = {}
    for k, expr in fields.items():
        if k in ("path", "attributes"):
            continue
        v = env[expr] if expr in ("$file", "$stem") else jmespath.search(expr, item)
        vals[k] = _post(v, post.get(k))
    return vals


def _entry_record(fields, vals, item, rel, layer, fmt, path, line_key):
    path_str = fields.get("path", "/{id}").format(
        **{k: (v if v is not None else "") for k, v in vals.items()}
    )
    path_str = re.sub(r"/+", "/", path_str)
    attrs = {}
    for ak, aexpr in (fields.get("attributes") or {}).items():
        av = jmespath.search(aexpr, item)
        if av is not None:
            attrs[ak] = av
    rec = {
        "format_version": 1,
        "id": str(vals["id"]),
        "path": path_str,
        "layer": layer,
        "source": {
            "file": rel,
            "line": item["$line"]
            if fmt == "csv"
            else _find_line(path, line_key, item.get(line_key, vals["id"])),
        },
    }
    if vals.get("name"):
        rec["name"] = str(vals["name"])
    if attrs:
        rec["attributes"] = attrs
    return rec


def _matching_items(path, fmt, records_expr, where_expr):
    for doc in _load(path, fmt):
        if doc is None:
            continue
        for item in _records(doc, fmt, records_expr):
            if isinstance(item, dict) and (
                not where_expr or jmespath.search(where_expr, item)
            ):
                yield item


def extract(scope: Path, params: dict, layer: str):
    files = params["files"]
    if isinstance(files, str):
        files = [files]
    fmt = params.get("format", "yaml")
    records_expr = params.get("records")
    where_expr = params.get("where")
    fields = params.get("fields", {})
    post = params.get("post", {})
    line_key = params.get("line_key", "id")

    paths = _input_paths(scope, files, params)
    n = 0
    for path in paths:
        rel = path.relative_to(scope).as_posix()
        for item in _matching_items(path, fmt, records_expr, where_expr):
            vals = _field_values(item, rel, path, fields, post)
            if not vals.get("id"):
                print(f"[structured-query] skip (id 無し): {rel}", file=sys.stderr)
                continue
            rec = _entry_record(fields, vals, item, rel, layer, fmt, path, line_key)
            sys.stdout.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n += 1
    print(f"[structured-query] files={len(paths)} entries={n}", file=sys.stderr)


def main(argv=None):
    import argparse

    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--scope", required=True)
    ap.add_argument(
        "--params",
        required=True,
        help="JSON 文字列、または @path で JSON/YAML ファイル",
    )
    ap.add_argument("--layer", required=True)
    a = ap.parse_args(argv)
    if a.params.startswith("@"):
        params = yaml.safe_load(Path(a.params[1:]).read_text(encoding="utf-8"))
    else:
        params = json.loads(a.params)
    extract(Path(a.scope).resolve(), params, a.layer)


if __name__ == "__main__":
    main()
