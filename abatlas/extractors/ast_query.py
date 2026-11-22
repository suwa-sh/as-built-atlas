"""ast 抽出器: コードの構文を読んで、コードの中で定義される入口 (ルーティングの定義、登録の呼び出しなど) の候補を出す。

構文の一致には ast-grep を使う。一致 1 つ = 入口 1 件。
静的に読めるものだけを出す。別のファイルから来る定義や、関数が作る定義は取れない。取れない所を探す規則 (unresolved) を書くと、
その場所を標準エラーに出す (入口を見つける skill が、そこを読んで入口を足す)。

params (JSON):
  files:    glob (scope からの相対)。複数可 (配列)。`**` は 0 個以上のディレクトリに一致する
  exclude:  glob (任意。scope からの相対パスに fnmatch で当てる)
  language: 言語 (必須)。SUPPORTED_LANGUAGES のどれか
  rule:     ast-grep の規則 (必須)。`pattern` / `kind` / `has` / `inside` / `all` / `any` / `not` / `regex` など。
            値を取り出す所に、名前付きの穴 (`$NAME`。大文字) を置く。
            `constraints` や `utils` を使うときは、{rule: {...}, constraints: {...}} の形で書く
  fields:   入口の項目の作り方。値は「ひな形」で、`{NAME}` が穴 `$NAME` に一致した文字に置き換わる。
            `{file}` (ファイルの相対パス)、`{dir}` (そのディレクトリ)、`{stem}` (拡張子を除いたファイル名) も使える
    path:       階層パスの元 (必須)。'/' で区切って段にする (例: "{PATH}")
    id:         id の元 (任意)。'/' で区切り、段ごとに id.replace を当てて id.join でつなぐ。省くと、階層パスの段から作る
    name:       人が読む名前 (任意)。省くと、最後の段
    attributes: {属性名: ひな形} (任意)
  unquote:  true (既定) なら、穴に一致した文字の両端の引用符 (' " `) を外す
  segments: 段の加工 (すべて任意。下の 4 つは、glob 抽出器と同じ意味。glob 抽出器の strip_prefix と drop_last は使えない。書くと止まる)
    drop:    正規表現の配列。段の全体に一致したら、その段を落とす (例: ":tenant\\\\?")
    replace: [{pattern, with}] の配列。各段に上から順に re.sub する。空になった段は落とす
    prefix:  加工した段の前に置く、固定の段 (文字列か配列)
    empty:   段が 1 つも残らないときに置く段 (既定 "(root)")
  id:       id の作り方 (すべて任意。glob 抽出器と同じ意味)
    join:    段のつなぎ (既定 ".")
    replace: [{pattern, with}] の配列。既定は「英数字 _ - 以外を除く」
  unresolved: ast-grep の規則 (任意)。静的に読めない定義 (別のファイルから来る名前、展開、関数の呼び出しなど) に一致させる。
            一致した場所を「読めなかった参照」として標準エラーに出す。入口にはしない
  allow_empty: true なら、files に一致するファイルが無くても成功 (既定は失敗)

同じ id が 2 つの一致から出たらエラーにする。規則の穴が一致に無いときもエラーにする (規則と fields の食い違いを黙って通さない)。
"""

from __future__ import annotations

import fnmatch
import glob
import json
import re
import sys
from pathlib import Path

import yaml

from .file_glob import id_options, _apply, _as_list, shape_segments

# ast-grep (ast-grep-py) が、追加の設定なしで読める言語。tests/test_ast_query.py が、全部が読めることを確かめる
SUPPORTED_LANGUAGES = (
    "bash",
    "c",
    "cpp",
    "csharp",
    "dart",
    "elixir",
    "go",
    "hcl",
    "html",
    "java",
    "javascript",
    "json",
    "kotlin",
    "lua",
    "php",
    "python",
    "ruby",
    "rust",
    "scala",
    "swift",
    "tsx",
    "typescript",
    "yaml",
)
_HOLE = re.compile(r"\{([A-Za-z_]\w*)\}", re.ASCII)
_FILE_VARS = ("file", "dir", "stem")


def check_language(language) -> str:
    if language not in SUPPORTED_LANGUAGES:
        raise SystemExit(
            f"[ast] language '{language}' は読めない。読める言語: {', '.join(SUPPORTED_LANGUAGES)}"
        )
    return language


def find_all(text: str, language: str, rule: dict, where: str) -> list:
    """text を language として読み、rule に一致するノードを返す。規則の誤りは、理由を付けて止める。"""
    from ast_grep_py import SgRoot

    if not isinstance(rule, dict) or not rule:
        raise SystemExit(f"[ast] {where} が無いか、形が違う (ast-grep の規則を書く)")
    try:
        root = SgRoot(text, language).root()
        return root.find_all(rule) if "rule" in rule else root.find_all(**rule)
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException as e:  # ast-grep は、規則の誤りを通常の例外でなく異常終了 (PanicException) で返すことがある
        raise SystemExit(
            f"[ast] {where} を ast-grep が受け付けない: {type(e).__name__}: {str(e)[:300]}"
        )


def target_files(scope: Path, files: list[str], excludes: list[str]) -> list[str]:
    paths = sorted(
        {
            Path(p)
            for g in files
            for p in glob.glob(str(scope / g), recursive=True)
            if Path(p).is_file()
        }
    )
    root = scope.resolve()
    outside = sorted(str(p) for p in paths if not p.resolve().is_relative_to(root))
    if outside:
        raise SystemExit(
            f"[ast] files {files} が、対象の範囲 (scope) の外のファイルに一致した: {outside[:3]}。files は scope の中を指す"
        )
    rels = [p.resolve().relative_to(root).as_posix() for p in paths]
    return [r for r in rels if not any(fnmatch.fnmatch(r, x) for x in excludes)]


def _unquote(s: str) -> str:
    return s[1:-1] if len(s) >= 2 and s[0] == s[-1] and s[0] in "'\"`" else s


def _fill(template: str, node, rel: str, unquote: bool, where: str) -> str:
    def sub(m: re.Match) -> str:
        key = m.group(1)
        if key in _FILE_VARS:
            p = Path(rel)
            return {"file": rel, "dir": p.parent.as_posix(), "stem": p.stem}[key]
        got = node.get_match(key)
        if got is None:
            line = node.range().start.line + 1
            raise SystemExit(
                f"[ast] {rel}:{line}: {where} の {{{key}}} に当たる穴 ${key} が、一致の中に無い (rule に ${key} を置くか、fields を直す)"
            )
        text = got.text()
        return _unquote(text) if unquote else text

    return _HOLE.sub(sub, str(template))


def _segments(path_str: str, conf: dict) -> list[str]:
    unknown = sorted(set(conf) - {"drop", "replace", "prefix", "empty"})
    if unknown:
        # glob 抽出器の strip_prefix / drop_last は、ファイルの置き場を段にするときのもの。ここでは効かないので、黙って無視しない
        raise SystemExit(
            f"[ast] segments に、使えない項目がある: {unknown}。使えるのは drop / replace / prefix / empty (先頭を落とすなら、drop か replace で書く)"
        )
    out = shape_segments([part for part in path_str.split("/") if part], conf)
    head = [str(p) for p in _as_list(conf.get("prefix")) if str(p)]
    if any("/" in p for p in head):
        raise SystemExit(
            f"[ast] segments.prefix {head} の段に '/' は書けない (段ごとに配列で書く)"
        )
    if not out and not head:
        out = [str(conf.get("empty") or "(root)")]
    return head + out


def _entry_id(fields, node, rel, unquote, segs, id_rules, id_join, here, seen):
    id_src = (
        _fill(fields["id"], node, rel, unquote, "fields.id").split("/")
        if fields.get("id")
        else segs
    )
    id_parts = [s for s in (_apply(p, id_rules) for p in id_src) if s]
    if not id_parts:
        raise SystemExit(
            f"[ast] {here}: id が空になった ({id_src} に id.replace を当てた結果)。fields.id か id.replace を見直す"
        )
    eid = id_join.join(id_parts)
    if eid in seen:
        raise SystemExit(
            f"[ast] id '{eid}' が 2 つの一致から出た: {seen[eid]} と {here}。fields / segments / id の加工で別の入口が同じ名前になっている"
        )
    seen[eid] = here
    return eid


def _entry_record(eid, segs, layer, rel, line, fields, node, unquote):
    rec = {
        "format_version": 1,
        "id": eid,
        "path": "/" + "/".join(segs),
        "layer": layer,
        "source": {"file": rel, "line": line},
        "name": _fill(fields["name"], node, rel, unquote, "fields.name")
        if fields.get("name")
        else segs[-1],
    }
    attrs = {
        k: _fill(t, node, rel, unquote, f"fields.attributes.{k}")
        for k, t in (fields.get("attributes") or {}).items()
    }
    if attrs:
        rec["attributes"] = attrs
    return rec


def _checked_files(scope, files, params, language, rule, unresolved_rule, seg_conf):
    # 規則の誤りは、対象のファイルが 1 つも無くても見つける (空の文字に当てて、ast-grep に検査させる)
    find_all("", language, rule, "params.rule")
    if unresolved_rule is not None:
        find_all("", language, unresolved_rule, "params.unresolved")
    _segments("", seg_conf)

    rels = target_files(scope, files, _as_list(params.get("exclude")))
    if not rels and not params.get("allow_empty"):
        raise SystemExit(
            f"[ast] files {files} に一致するファイルが scope に無い (glob の誤り?)。空が正しいなら allow_empty: true"
        )
    return rels


def _report_unresolved(text, language, unresolved_rule, rel):
    unresolved = 0
    if (
        unresolved_rule is not None
    ):  # 空の規則は、書いたつもりで何も探さないことになるので、find_all が止める
        for node in find_all(text, language, unresolved_rule, "params.unresolved"):
            first = node.text().splitlines()[0][:120] if node.text() else ""
            print(
                f"[ast] 読めなかった参照: {rel}:{node.range().start.line + 1}: {first}",
                file=sys.stderr,
            )
            unresolved += 1
    return unresolved


def extract(scope: Path, params: dict, layer: str):
    files = _as_list(params.get("files"))
    if not files:
        raise SystemExit("[ast] params.files が無い")
    language = check_language(params.get("language"))
    rule = params.get("rule")
    fields = params.get("fields") or {}
    if not fields.get("path"):
        raise SystemExit('[ast] params.fields.path が無い (階層パスの元。例: "{PATH}")')
    unquote = params.get("unquote", True)
    seg_conf = params.get("segments") or {}
    id_rules, id_join = id_options(params)
    unresolved_rule = params.get("unresolved")

    rels = _checked_files(
        scope, files, params, language, rule, unresolved_rule, seg_conf
    )

    seen: dict[str, str] = {}
    recs = []
    unresolved = 0
    for rel in rels:
        text = (scope / rel).read_text(encoding="utf-8", errors="replace")
        for node in find_all(text, language, rule, "params.rule"):
            line = node.range().start.line + 1
            here = f"{rel}:{line}"
            segs = _segments(
                _fill(fields["path"], node, rel, unquote, "fields.path"), seg_conf
            )
            eid = _entry_id(
                fields, node, rel, unquote, segs, id_rules, id_join, here, seen
            )
            rec = _entry_record(eid, segs, layer, rel, line, fields, node, unquote)
            recs.append(rec)
        unresolved += _report_unresolved(text, language, unresolved_rule, rel)
    for rec in recs:
        sys.stdout.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(
        f"[ast] files={len(rels)} entries={len(recs)} unresolved={unresolved}",
        file=sys.stderr,
    )


def search(
    scope: Path,
    files: list[str],
    excludes: list[str],
    language: str,
    rule: dict,
    limit: int = 200,
) -> list[str]:
    """規則に一致した場所を「ファイル:行: 1 行目」の形で返す (入口を見つける skill が、その場で調べるのに使う)。"""
    check_language(language)
    rels = target_files(scope, files, excludes)
    if not rels:
        raise SystemExit(f"[ast] files {files} に一致するファイルが {scope} に無い")
    out: list[str] = []
    total = 0
    for rel in rels:
        text = (scope / rel).read_text(encoding="utf-8", errors="replace")
        for node in find_all(text, language, rule, "規則"):
            total += 1
            if len(out) < limit:
                first = node.text().splitlines()[0][:160] if node.text() else ""
                out.append(f"{rel}:{node.range().start.line + 1}: {first}")
    out.append(
        f"# files={len(rels)} matches={total}"
        + (f" (先頭の {limit} 件だけ出した)" if total > limit else "")
    )
    return out


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
