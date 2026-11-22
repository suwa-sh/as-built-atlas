"""画面の呼び名が用語集 (schema/vocab/terms.yaml) だけで決まることの検査。

- 画面のコード・宣言・プロファイルが指す用語は、用語集にある
- 使わなくなった呼び名 (retired) が、画面に出る文字に残っていない
- core の mart の title と labels は、用語の差し込み口と記号・単位だけで組まれている
- 画面のコードは、用語集の呼び名を文字列に直接書いていない (term("<id>") で引く)
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from abatlas.declarations import check_declaration, declaration_texts
from abatlas.schemas import (
    profile_display_texts,
    profile_term_problems,
    resolve_terms,
    resource_kinds,
    term_labels,
    term_refs,
    vocab,
)

ROOT = Path(__file__).resolve().parents[1]
WEBAPP = ROOT / "abatlas" / "webapp"
CORE_SCHEMA = ROOT / "dbt-template" / "models" / "core" / "schema.yml"
PROFILE_SCHEMAS = sorted(
    (ROOT / "profiles").glob("*/dbt-template/models/**/schema.yml")
)
PROFILES = sorted((ROOT / "profiles").glob("*/profile.yaml"))
JA = re.compile(r"[ぁ-んァ-ヶ一-龥]")
RETIRED = [re.compile(p) for p in vocab("terms")["retired"]]
# 1 語の呼び名のうち、日本語の文の中に直接書かれていたら用語集を通していないと言えるもの (宣言の項目名や値と同じ綴りの語は除く)
# 1 語の呼び名と同じ綴りで、宣言の項目名・値・CSS のクラス名・用語の id として文字列に書く語 (表示のためではない)。
# ここに無い 1 語の呼び名を、文字列にそのまま書くと落とす。ここにある語を表示のために直接書いた場合は見つけられない (検査の限界)
IDENT = {
    "columns",
    "datastore",
    "description",
    "external",
    "function",
    "kind",
    "layer",
    "level",
    "name",
    "ops",
    "path",
    "read",
    "sequence",
    "status",
    "subject",
    "summary",
    "title",
    "unknown",
    "view",
    "write",
}
DISTINCT = [
    "datastore",
    "layer",
    "tier",
    "function",
    "hop",
    "mart",
    "architecture",
    "dependencies",
    "evidence",
    "progress",
    "unknown",
    "analyzed",
    "stale",
    "rebuild",
    "profile",
    "target",
]


def js_code(path: Path) -> str:
    """コメントを除いた JS。日本語が残るのは文字列の中だけ。"""
    out = []
    block = False
    for line in path.read_text(encoding="utf-8").split("\n"):
        if block or line.lstrip().startswith(("/*", "*")):
            block = "*/" not in line and (block or line.lstrip().startswith("/*"))
            continue
        cut = len(line)
        for m in re.finditer(r"//", line):
            before = line[: m.start()]
            if before.strip() == "" or (
                before[-1] in " \t;{},"
                and before.count('"') % 2 == 0
                and before.count("`") % 2 == 0
            ):
                cut = m.start()
                break
        out.append(line[:cut])
    return "\n".join(out)


def js_files() -> list[Path]:
    return sorted(WEBAPP.rglob("*.js"))


def declared(schema: Path) -> list[tuple[str, dict, str]]:
    models = yaml.safe_load(schema.read_text(encoding="utf-8"))["models"]
    return [
        (m["name"], m["meta"]["abatlas"], m.get("description", ""))
        for m in models
        if "abatlas" in (m.get("meta") or {})
    ]


def profile_texts(path: Path) -> list[tuple[str, str]]:
    """プロファイルのうち画面に出る文字 (/meta が用語を差し込んで配るもの)。"""
    return profile_display_texts(yaml.safe_load(path.read_text(encoding="utf-8")))


def kind_texts() -> list[tuple[str, str]]:
    """データの種類の語彙のうち画面に出る文字 (置き換える前)。"""
    out = []
    for k, v in vocab("resource-kinds")["kinds"].items():
        out.append((f"{k}/label", v.get("label", "")))
        out += [(f"{k}/ops/{o['id']}", o.get("label", "")) for o in v.get("ops", [])]
    return out


def test_terms_have_one_label_each():
    labels = term_labels()
    assert labels and all(isinstance(v, str) and v.strip() for v in labels.values())
    assert all(re.fullmatch(r"[a-z][a-z0-9_]*", k) for k in labels), (
        "id は小文字と _ (宣言の差し込み口 {id} に書ける形)"
    )
    by_label: dict[str, list[str]] = {}
    for k, v in labels.items():
        by_label.setdefault(v, []).append(k)
    assert {v: ks for v, ks in by_label.items() if len(ks) > 1} == {}, (
        "同じ呼び名を 2 つの概念に使わない"
    )
    assert not any(JA.search(v) for v in labels.values()), "技術用語は英語のまま書く"


def _check_js_term_ids(labels, missing):
    for p in js_files():
        for ref in re.findall(r'\bterm\("([^"]+)"\)', js_code(p)):
            if ref not in labels:
                missing.append(f'{p.relative_to(ROOT)}: term("{ref}")')
        for names in re.findall(r"[A-Z_]+_TERM = \{([^}]*)\}", js_code(p)):
            missing += [
                f"{p.relative_to(ROOT)}: {ref}"
                for ref in re.findall(r'"([a-z_]+)"', names)
                if ref not in labels
            ]


def _check_literal_labels(p, code, singles, bad):
    # 1 語の呼び名を、そのまま 1 つの文字列として書いていないか (term("<id>") の引数は除く)
    bare = re.sub(r'term\("[a-z_]+"\)', "", code)
    lits = (
        re.findall(r'"((?:[^"\\\n]|\\.)*)"', bare)
        + re.findall(r"'((?:[^'\\\n]|\\.)*)'", bare)
        + re.findall(r"`([^`$]*)`", bare)
    )
    for lit in lits:
        if lit in singles and lit not in IDENT:
            bad.append(f'{p.relative_to(ROOT)}: "{lit}" (term() で引く)')


def _check_japanese_labels(p, code, bad):
    # 日本語の文に、1 語の呼び名を直接書いていないか (差し込み口 ${...} の中は見ない)
    flat = code
    for _ in range(4):
        flat = re.sub(r"\$\{[^{}]*\}", " ", flat)
    for lit in re.findall(r'"(?:[^"\\\n]|\\.)*"|`[^`]*`', flat):
        if not JA.search(lit):
            continue
        for w in DISTINCT:
            if re.search(rf"(?<![\w.-]){w}(?![\w-])", lit):
                bad.append(f"{p.relative_to(ROOT)}: '{w}' in {lit[:70]!r}")


def _vocabulary_texts():
    for schema in [CORE_SCHEMA, *PROFILE_SCHEMAS]:
        for name, meta, desc in declared(schema):
            for where, text in [*declaration_texts(meta), ("description", desc)]:
                yield f"{name}: {where}", text
    for prof in PROFILES:
        for where, text in profile_texts(prof):
            yield f"{prof.relative_to(ROOT)}: {where}", text
    for where, text in kind_texts():
        yield f"resource-kinds: {where}", text


def test_every_referenced_term_exists():
    labels = term_labels()
    missing = []
    _check_js_term_ids(labels, missing)
    for where, text in _vocabulary_texts():
        missing.extend(
            f"{where}: {{{ref}}}" for ref in term_refs(text) if ref not in labels
        )
    assert missing == []


def test_resource_kind_labels_follow_the_glossary():
    """データの種類の語彙 (種類と操作の label) も、用語集にある呼び名は "{id}" で引く (同じ呼び名を 2 か所に書かない)。"""
    labels = set(term_labels().values())
    direct = [f"{where}: {text!r}" for where, text in kind_texts() if text in labels]
    assert direct == []
    assert resource_kinds()["external_api"]["label"] == term_labels()["external"]
    assert not any(
        "{" in v["label"] or any("{" in o["label"] for o in v["ops"])
        for v in resource_kinds().values()
    )


def test_profile_display_terms_are_checked():
    """プロファイルの表示項目の用語は、validate と build が配る前に見る (未知の id を画面に出さない)。"""
    prof = {
        "label": "x → {datastore}",
        "layers": [{"id": "a", "label": "{nope}", "tier": "{tier}"}],
        "hierarchy": {"notes": [{"text": "\\{entry} と {oops}"}]},
    }
    assert profile_term_problems(prof) == [
        "profile: layers/a/label: 用語 '{nope}' が用語集に無い (schema/vocab/terms.yaml)",
        "profile: hierarchy/notes/0/text: 用語 '{oops}' が用語集に無い (schema/vocab/terms.yaml)",
    ]
    for path in PROFILES:
        assert (
            profile_term_problems(yaml.safe_load(path.read_text(encoding="utf-8")))
            == []
        )


def test_term_reference_can_be_escaped_and_description_is_checked():
    labels = {"entry": "entry point"}
    assert resolve_terms("{entry} の一覧", labels) == "entry point の一覧"
    assert resolve_terms("書き方: \\{entry}", labels) == "書き方: {entry}", (
        "\\ を付けた差し込み口は文字どおり残す"
    )
    assert term_refs("\\{entry} と {nope}") == ["nope"]
    ok = {"origin": "repo", "view": "table", "level": "entry", "keys": {"id": "x"}}
    assert check_declaration("m", ok, {"x"}, "説明 {entry}") == []
    assert any(
        "description の用語 '{nope}'" in p
        for p in check_declaration("m", ok, {"x"}, "説明 {nope}")
    )
    assert any(
        "title の用語 '{nope}'" in p
        for p in check_declaration("m", {**ok, "title": "{nope}"}, {"x"})
    )


def test_webapp_calls_term_only_inside_functions():
    """用語集は起動の後に入るので、モジュールの読み込み時 (字下げの無い行) に term() を呼ぶと id がそのまま出る。"""
    bad = []
    for p in js_files():
        for i, line in enumerate(js_code(p).split("\n"), 1):
            if (
                "term(" in line
                and re.match(
                    r"(export )?(const|let|var) \w+ = (?!\(|async|function)", line
                )
                and "=>" not in line
            ):
                bad.append(f"{p.relative_to(ROOT)}:{i}")
    assert bad == []


def test_no_retired_words_on_screen():
    labels = term_labels()
    hits = []

    def scan(where: str, text: str) -> None:
        for rx in RETIRED:
            m = rx.search(text)
            if m:
                hits.append(f"{where}: '{m.group(0)}' in {text.strip()[:80]!r}")

    for p in js_files():
        for i, line in enumerate(js_code(p).split("\n"), 1):
            scan(f"{p.relative_to(ROOT)}:{i}", line)
    for i, line in enumerate(
        (WEBAPP / "index.html").read_text(encoding="utf-8").split("\n"), 1
    ):
        scan(f"abatlas/webapp/index.html:{i}", re.sub(r"<!--.*?-->", "", line))
    for where, text in _vocabulary_texts():
        scan(where, resolve_terms(text, labels))
    assert hits == []


def test_core_titles_and_labels_are_built_from_terms():
    """core の title と labels は "{id}" と記号・単位だけ (呼び名を直接書かない)。"""
    bad = []
    for name, meta, _ in declared(CORE_SCHEMA):
        texts = [
            (w, t)
            for w, t in declaration_texts(meta)
            if w == "title" or w.startswith(("labels.", "filters["))
        ]
        for where, text in texts:
            rest = re.sub(r"\b(USD|s)\b", "", re.sub(r"\{[a-z][a-z0-9_]*\}", "", text))
            if not re.fullmatch(r"[\s/()0-9]*", rest):
                bad.append(f"{name}: {where}: {text!r}")
    assert bad == []


def test_webapp_does_not_write_labels_directly():
    labels = term_labels()
    phrases = sorted({v for v in labels.values() if " " in v}, key=len, reverse=True)
    singles = {v for v in labels.values() if " " not in v}
    bad = []
    for p in js_files():
        if p.name == "vocab.js" and p.parent.name == "model":
            continue
        code = js_code(p)
        for ph in phrases:
            if re.search(rf"(?<![\w-]){re.escape(ph)}(?![\w-])", code):
                bad.append(f"{p.relative_to(ROOT)}: '{ph}'")
        _check_literal_labels(p, code, singles, bad)
        _check_japanese_labels(p, code, bad)
    assert bad == []
