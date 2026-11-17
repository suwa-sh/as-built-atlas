"""nested-keys 抽出器: 入れ子のキーが入口を決める定義ファイル (YAML / JSON) から、入口の候補を出す。

キーの組み合わせ 1 つ = 入口 1 件。例: OpenAPI は `paths.<URL>.<HTTP メソッド>`、AsyncAPI (v2) は `channels.<チャネル>.<publish | subscribe>`。
キーを '/' などで区切った「段」を加工して、階層パスと id を作る。出典の行は、最後の段のキーがある行 (YAML の構文木から取るので、同じキーが何度出ても取り違えない)。

params (JSON):
  files:    glob (scope からの相対)。複数可 (配列)
  root:     入口のキーが並ぶ場所までのキーの並び (配列か、'.' 区切りの文字列。例: "paths")。省略すると、文書のいちばん上
  levels:   キーの段の並び (1 つ以上)。段ごとに:
    match:    正規表現 (任意)。キーの全体に一致したものだけを辿る。一致しないキーは、入口にしない (例: path の下の `parameters`、`summary`)
    split:    区切りの文字 (任意)。キーをこの文字で区切って、複数の段にする (例: "/" で `/users/{id}` → users, {id})。空の段は落とす
  segments: 段の作り方 (glob 抽出器と同じ。すべて任意)
    drop:     正規表現の配列。段の全体に一致したら、その段を落とす
    replace:  [{pattern, with}] の配列。各段に上から順に re.sub する。空になった段は落とす
    prefix:   加工した段の前に置く、固定の段 (文字列か配列)
    empty:    levels の最後の段より前の段が 1 つも残らないときに、その場所に置く段 (既定 "(root)")
  id:       id の作り方 (glob 抽出器と同じ)
    join:    段のつなぎ (既定 ".")
    replace: [{pattern, with}] の配列。各段に適用する。既定は「英数字 _ - 以外を除く」
  name:     JMESPath (任意)。最後のキーの値 (入口の定義) から、人が読む名前を取り出す (例: "operationId")。取れなければ、キーを ' ' でつないだもの
  attributes: {属性名: JMESPath} (任意)。最後のキーの値に対して評価する
  allow_empty: true なら、files に一致するファイルが無くても、入口が 0 件でも成功 (既定は失敗)

出力する attributes: keys (加工前のキーの並び) と、attributes の結果。
最後のキーの値や、途中のキーの値が `$ref` だけのとき (別のファイルや場所を指す定義) は、入口にせず、標準エラーに「読めなかった参照」として出す (参照は辿らない。
指す先のファイルを files に足しても、そのファイルに root からのキーの並びが無ければ読めないので、指す先を読んで、listed 抽出器で足す)。
同じ id が 2 つのキーの組から出たらエラーにする。
"""

from __future__ import annotations

import glob
import json
import re
import sys
from pathlib import Path

import jmespath
import yaml

from .file_glob import DEFAULT_ID_REPLACE, _apply, _as_list


def _pairs(node) -> list[tuple[str, int, object]]:
    """mapping の構文木から (キー, キーの行, 値の構文木) を返す。mapping でなければ空。"""
    if not isinstance(node, yaml.MappingNode):
        return []
    return [(str(k.value), k.start_mark.line + 1, v) for k, v in node.value if isinstance(k, yaml.ScalarNode)]


def _child(node, key: str):
    for k, _line, v in _pairs(node):
        if k == key:
            return v
    return None


def _value(node):
    return yaml.safe_load(yaml.serialize(node)) if node is not None else None


def _is_ref(node) -> bool:
    pairs = _pairs(node)
    return len(pairs) == 1 and pairs[0][0] == "$ref"


def _walk(node, levels: list[dict], depth: int, keys: list[str], segs: list[str], line: int, rel: str, out: list, unresolved: list):
    if depth == len(levels):
        out.append((keys, segs, line, node))
        return
    level = levels[depth]
    match = re.compile(level["match"]) if level.get("match") else None
    for key, kline, value in _pairs(node):
        if match and not match.fullmatch(key):
            continue
        if _is_ref(value):
            unresolved.append(f"{rel}:{kline}: {key}: $ref {_pairs(value)[0][2].value}")
            continue
        parts = [p for p in key.split(level["split"]) if p] if level.get("split") else [key]
        _walk(value, levels, depth + 1, keys + [key], segs + [parts], kline, rel, out, unresolved)


def extract(scope: Path, params: dict, layer: str):
    files = _as_list(params.get("files"))
    if not files:
        raise SystemExit("[nested-keys] params.files が無い")
    levels = params.get("levels") or []
    if not levels:
        raise SystemExit("[nested-keys] params.levels が無い (キーの段を 1 つ以上書く)")
    root = params.get("root") or []
    root = [p for p in root.split(".") if p] if isinstance(root, str) else [str(p) for p in root]
    seg_conf = params.get("segments") or {}
    drops = [re.compile(p) for p in _as_list(seg_conf.get("drop"))]
    head = [str(p) for p in _as_list(seg_conf.get("prefix")) if str(p)]
    id_conf = params.get("id") or {}
    id_rules = id_conf.get("replace") or DEFAULT_ID_REPLACE
    id_join = id_conf.get("join", ".")
    name_expr = params.get("name")
    attr_exprs = params.get("attributes") or {}

    paths = sorted({Path(p) for g in files for p in glob.glob(str(scope / g), recursive=True) if Path(p).is_file()})
    if not paths and not params.get("allow_empty"):
        raise SystemExit(f"[nested-keys] files {files} に一致するファイルが scope に無い (glob の誤り?)。空が正しいなら allow_empty: true")

    def shape(parts: list[str]) -> list[str]:
        out = []
        for seg in parts:
            if any(d.fullmatch(seg) for d in drops):
                continue
            seg = _apply(seg, seg_conf.get("replace") or [])
            if seg:
                out.append(seg)
        return out

    seen: dict[str, str] = {}
    recs = []
    unresolved: list[str] = []
    for path in paths:
        rel = path.relative_to(scope).as_posix()
        try:
            docs = list(yaml.compose_all(path.read_text(encoding="utf-8")))
        except yaml.YAMLError as e:
            raise SystemExit(f"[nested-keys] {rel}: 読めない ({str(e).splitlines()[0]})")
        for doc in docs:
            node = doc
            at = 1
            for key in root:
                at = next((line for k, line, _v in _pairs(node) if k == key), at)
                node = _child(node, key)
                if _is_ref(node):
                    unresolved.append(f"{rel}:{at}: {key}: $ref {_pairs(node)[0][2].value}")
                    node = None
                    break
            found: list = []
            _walk(node, levels, 0, [], [], 1, rel, found, unresolved)
            for keys, seg_groups, line, value_node in found:
                here = f"{rel}:{line}"
                front = [s for group in seg_groups[:-1] for s in shape(group)]
                last = shape(seg_groups[-1])
                if len(seg_groups) > 1 and not front:
                    front = [str(seg_conf.get("empty") or "(root)")]
                segs = head + front + last
                if not segs:
                    raise SystemExit(f"[nested-keys] {here}: 段が空になった (キー {keys} に segments を当てた結果)")
                id_parts = [s for s in (_apply(seg, id_rules) for seg in segs) if s]
                if not id_parts:
                    raise SystemExit(f"[nested-keys] {here}: id が空になった (段 {segs} に id.replace を当てた結果)")
                eid = id_join.join(id_parts)
                if eid in seen:
                    raise SystemExit(f"[nested-keys] id '{eid}' が 2 つのキーの組から出た: {seen[eid]} と {here}。segments / id の加工で別の入口が同じ名前になっている")
                seen[eid] = here
                value = _value(value_node)
                name = jmespath.search(name_expr, value) if name_expr and isinstance(value, (dict, list)) else None
                attrs: dict = {"keys": keys}
                for ak, aexpr in attr_exprs.items():
                    av = jmespath.search(aexpr, value) if isinstance(value, (dict, list)) else None
                    if av is not None:
                        attrs[ak] = av
                recs.append({
                    "format_version": 1,
                    "id": eid,
                    "path": "/" + "/".join(segs),
                    "layer": layer,
                    "source": {"file": rel, "line": line},
                    "name": str(name) if name else " ".join(keys),
                    "attributes": attrs,
                })
    for u in unresolved:
        print(f"[nested-keys] 読めなかった参照: {u}", file=sys.stderr)
    if not recs and not params.get("allow_empty"):
        hint = "読めなかった参照の先を、読んで listed で足す" if unresolved else f"root {root} と levels を見直す"
        raise SystemExit(f"[nested-keys] 入口が 1 件も出なかった ({hint})。空が正しいなら allow_empty: true")
    for rec in recs:
        sys.stdout.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"[nested-keys] files={len(paths)} entries={len(recs)} unresolved={len(unresolved)}", file=sys.stderr)


def main(argv=None):
    import argparse

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scope", required=True)
    ap.add_argument("--params", required=True, help="JSON 文字列、または @path で JSON/YAML ファイル")
    ap.add_argument("--layer", required=True)
    a = ap.parse_args(argv)
    if a.params.startswith("@"):
        params = yaml.safe_load(Path(a.params[1:]).read_text(encoding="utf-8"))
    else:
        params = json.loads(a.params)
    extract(Path(a.scope).resolve(), params, a.layer)


if __name__ == "__main__":
    main()
