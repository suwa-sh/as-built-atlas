"""listed 抽出器: エージェントがコードを読んで見つけた入口を、根拠つきで一覧に足す。

ほかの抽出器 (構造化データ、glob、ast) で取れない入口のためのもの。例: 別のファイルから来る定義、関数が作る定義、
道具が読めない言語。入口を見つける skill が params.entries を書き、この抽出器が根拠の実在を確かめて候補にする。
入口の一覧の entries[] には直接書かない (列挙をやり直すと消えるため。ここに書けば、列挙のたびに同じ候補が出る)。

params (JSON):
  entries: 入口の配列 (必須)。1 件ごとに次を書く
    id:         入口の id (必須。結果のファイル名になる)
    path:       階層パス (必須。'/' で始める)
    name:       人が読む名前 (任意)
    source:     根拠 (必須)。{file: scope からの相対パス, line: 行}。入口を定義している場所を指す
    reason:     なぜ入口と判断したか、なぜ道具で取れないか (必須。人が承認するときに読む)
    attributes: 付随する情報 (任意)
  allow_empty: true なら、entries が空でも成功 (既定は失敗)

出力する attributes: listed_by = "agent" (道具が出した候補と見分ける印)、reason、params の attributes。
根拠のファイルが scope に無い・行がファイルの行数を超えるときは、エラーにする。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

from .. import slash_path
from ..validate import _ScopeFiles


def _shape_problem(e, i):
    where = f"params.entries/{e.get('id', i)}"
    missing = [k for k in ("id", "path", "source", "reason") if not e.get(k)]
    if missing:
        return f"{where}: {missing} が無い"
    src = e["source"]
    if (
        not isinstance(src, dict)
        or not isinstance(src.get("file"), str)
        or not isinstance(src.get("line"), int)
        or src["line"] < 1
    ):
        return f"{where}: source は {{file: 相対パス, line: 1 以上の行}} で書く"
    if not isinstance(e["reason"], str) or not e["reason"].strip():
        return f"{where}: reason が空 (なぜ入口と判断したかを書く)"


def _source_problem(src, files, where):
    if Path(src["file"]).is_absolute():
        return f"{where}: source.file '{src['file']}' が絶対パス (対象の範囲 (scope) からの相対パスで書く)"
    problem, lines = files.check(src["file"])
    if problem:
        return f"{where}: source.file '{src['file']}' が{problem}"
    if src["line"] > (lines or 0):
        return f"{where}: source.line {src['line']} が '{src['file']}' の行数 {lines} を超えている"


def _listed_record(e, layer):
    src = e["source"]
    attrs = dict(e.get("attributes") or {})
    attrs.update({"listed_by": "agent", "reason": e["reason"].strip()})
    rec = {
        "format_version": 1,
        "id": str(e["id"]),
        "path": str(e["path"]),
        "layer": layer,
        # 定義ファイルとの照合は「/」区切りで比べる。OS の区切り文字で書かれていても合うようにする
        "source": {"file": slash_path(src["file"]), "line": src["line"]},
        "attributes": attrs,
    }
    if e.get("name"):
        rec["name"] = str(e["name"])
    return rec


def _collect_entry(i, e, files, layer, seen, problems, recs):
    where = f"params.entries/{i}"
    if not isinstance(e, dict):
        problems.append(
            f"{where}: 形が違う (id / path / source / reason を持つ項目を書く)"
        )
        return
    problem = _shape_problem(e, i)
    if problem:
        problems.append(problem)
        return
    where = f"params.entries/{e['id']}"
    if (
        str(e["id"]) in seen
    ):  # 出すときに文字にするので、文字にした値で比べる (1 と "1" は同じ id)
        problems.append(f"{where}: id が重複している")
        return
    seen.add(str(e["id"]))
    problem = _source_problem(e["source"], files, where)
    if problem:
        problems.append(problem)
    else:
        recs.append(_listed_record(e, layer))


def extract(scope: Path, params: dict, layer: str):
    entries = params.get("entries")
    if not isinstance(entries, list) or (not entries and not params.get("allow_empty")):
        raise SystemExit(
            "[listed] params.entries が無いか、空 (入口を 1 件以上書く。空が正しいなら allow_empty: true)"
        )
    files = _ScopeFiles(scope)
    problems: list[str] = []
    seen: set[str] = set()
    recs = []
    for i, e in enumerate(entries):
        _collect_entry(i, e, files, layer, seen, problems, recs)
    if problems:
        raise SystemExit("[listed] 足した入口に問題がある:\n  " + "\n  ".join(problems))
    for rec in recs:
        sys.stdout.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"[listed] entries={len(recs)}", file=sys.stderr)


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
