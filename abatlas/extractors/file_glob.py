"""glob 抽出器: ファイルの置き場そのものが入口を決める対象 (ファイルベースのルーティングなど) から、入口の候補を出す。

ファイル 1 つ = 入口 1 件。ファイルの相対パスを '/' で区切った「段」を加工して、階層パスと id を作る。中身は読まない (行の特定と属性を除く)。

params (JSON):
  files:    glob (scope からの相対)。複数可 (配列)。`**` は 0 個以上のディレクトリに一致する
  exclude:  glob (任意。scope からの相対パスに fnmatch で当てる)。一致したファイルは入口にしない
  segments: 段の作り方 (すべて任意)
    strip_prefix: 先頭から落とすディレクトリ (例: "src/app")。この下に無いファイルはエラー
    drop_last:    true (既定) ならファイル名を段にしない。false なら拡張子を除いたファイル名を最後の段にする
    drop:         正規表現の配列。段の全体に一致したら、その段を落とす (例: "\\\\([^)]+\\\\)" は URL に出ない入れ物 (group))
    replace:      [{pattern, with}] の配列。各段に上から順に re.sub する (例: 先頭の "(.)" を除く)。空になった段は落とす
    prefix:       加工した段の前に置く、固定の段 (文字列か配列。例: "(layout)")。同じ置き場から別の種類の入口を拾うときに、階層を分ける。drop / replace は当てない
    empty:        段が 1 つも残らないときに置く段 (既定 "(root)")。階層パスは空にできないため。prefix があれば置かない (prefix だけの階層になる)
  id:       id の作り方 (すべて任意)
    join:    段のつなぎ (既定 ".")
    replace: [{pattern, with}] の配列。各段に適用する。既定は「英数字 _ - 以外を除く」(id は結果のファイル名になるので記号を持てない)。
             空になった段は落とす。全部落ちたらエラー
  name:     "last" (既定。最後の段) | "path" (階層パス)
  line_match: 正規表現 (任意)。最初に一致した行を出典の行にする。無い・一致しないときは 1
  contains: {属性名: 正規表現} (任意)。ファイルの中身に一致があれば attributes.<属性名> = true、無ければ false
  allow_empty: true なら、files に一致するファイルが無くても成功 (既定は失敗)

出力する attributes: file_segments (加工前の段。URL に出ない入れ物も残る) と、contains の結果。
同じ id が 2 つのファイルから出たらエラーにする (段の加工で別の入口が潰れたことを黙って通さない)。
"""

from __future__ import annotations

import fnmatch
import glob
import json
import re
import sys
from pathlib import Path

import yaml

DEFAULT_ID_REPLACE = [{"pattern": r"[^A-Za-z0-9_-]", "with": ""}]


def _as_list(v) -> list:
    if v is None:
        return []
    return [v] if isinstance(v, str) else list(v)


def _apply(seg: str, rules: list[dict]) -> str:
    for r in rules:
        seg = re.sub(r["pattern"], r.get("with", ""), seg)
    return seg


def _relative_parts(rel, conf):
    parts = rel.split("/")
    prefix = [p for p in str(conf.get("strip_prefix") or "").split("/") if p]
    if parts[: len(prefix)] != prefix:
        raise SystemExit(
            f"[glob] {rel} は segments.strip_prefix '{'/'.join(prefix)}' の下に無い (files と strip_prefix を合わせる)"
        )
    parts = parts[len(prefix) :]
    if conf.get("drop_last", True):
        parts = parts[:-1]
    else:
        parts = parts[:-1] + [Path(parts[-1]).stem]
    return parts


def segment_drops(conf):
    return [re.compile(p) for p in _as_list(conf.get("drop"))]


def shape_segments(parts, conf, drops=None):
    if drops is None:
        drops = segment_drops(conf)
    out = []
    for seg in parts:
        if any(d.fullmatch(seg) for d in drops):
            continue
        seg = _apply(seg, conf.get("replace") or [])
        if seg:
            out.append(seg)
    return out


def matching_files(scope, files):
    paths = sorted(
        {
            Path(p)
            for g in files
            for p in glob.glob(str(scope / g), recursive=True)
            if Path(p).is_file()
        }
    )
    return paths


def _entry_id(segs, id_rules, id_join, seen, rel):
    id_parts = [s for s in (_apply(seg, id_rules) for seg in segs) if s]
    if not id_parts:
        raise SystemExit(
            f"[glob] {rel}: id が空になった (段 {segs} に id.replace を当てた結果)。id.replace か segments.empty を見直す"
        )
    eid = id_join.join(id_parts)
    if eid in seen:
        raise SystemExit(
            f"[glob] id '{eid}' が 2 つのファイルから出た: {seen[eid]} と {rel}。segments / id の加工で別の入口が同じ名前になっている"
        )
    seen[eid] = rel
    return eid


def segments_of(rel: str, conf: dict) -> tuple[list[str], list[str]]:
    """相対パスから (加工前の段, 加工後の段) を作る。"""
    raw = _relative_parts(rel, conf)
    out = shape_segments(raw, conf)
    head = [str(p) for p in _as_list(conf.get("prefix")) if str(p)]
    if any("/" in p for p in head):
        raise SystemExit(
            f"[glob] segments.prefix {head} の段に '/' は書けない (段ごとに配列で書く)"
        )
    if not out and not head:
        out = [str(conf.get("empty") or "(root)")]
    return raw, head + out


def _line(text: str, pattern: str | None) -> int:
    if not pattern:
        return 1
    pat = re.compile(pattern)
    for i, line in enumerate(text.splitlines(), 1):
        if pat.search(line):
            return i
    return 1


def _relative_files(scope, files, excludes, params):
    paths = matching_files(scope, files)
    rels = [p.relative_to(scope).as_posix() for p in paths]
    rels = [r for r in rels if not any(fnmatch.fnmatch(r, x) for x in excludes)]
    if not rels and not params.get("allow_empty"):
        raise SystemExit(
            f"[glob] files {files} に一致するファイルが scope に無い (glob の誤り?)。空が正しいなら allow_empty: true"
        )
    return rels


def _file_attributes(scope, rel, raw, contains, line_match):
    attrs: dict = {"file_segments": raw}
    text = None
    if contains or line_match:
        text = (scope / rel).read_text(encoding="utf-8", errors="replace")
    for key, pattern in contains.items():
        attrs[key] = re.search(pattern, text, re.M) is not None
    return attrs, text


def id_options(params):
    id_conf = params.get("id") or {}
    id_rules = id_conf.get("replace") or DEFAULT_ID_REPLACE
    id_join = id_conf.get("join", ".")
    return id_rules, id_join


def extract(scope: Path, params: dict, layer: str):
    files = _as_list(params.get("files"))
    if not files:
        raise SystemExit("[glob] params.files が無い")
    excludes = _as_list(params.get("exclude"))
    seg_conf = params.get("segments") or {}
    id_rules, id_join = id_options(params)
    name_mode = params.get("name", "last")
    contains = params.get("contains") or {}
    line_match = params.get("line_match")

    rels = _relative_files(scope, files, excludes, params)

    seen: dict[str, str] = {}
    recs = []
    for rel in rels:
        raw, segs = segments_of(rel, seg_conf)
        eid = _entry_id(segs, id_rules, id_join, seen, rel)
        path_str = "/" + "/".join(segs)
        attrs, text = _file_attributes(scope, rel, raw, contains, line_match)
        recs.append(
            {
                "format_version": 1,
                "id": eid,
                "path": path_str,
                "layer": layer,
                "source": {
                    "file": rel,
                    "line": _line(text, line_match) if text is not None else 1,
                },
                "name": path_str if name_mode == "path" else segs[-1],
                "attributes": attrs,
            }
        )
    for rec in recs:
        sys.stdout.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"[glob] files={len(rels)} entries={len(recs)}", file=sys.stderr)


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
