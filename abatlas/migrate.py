"""分析リポジトリの資産を、いまの形式の項目名に書き換える (abatlas migrate)。

形式の項目名を入れ替えたとき (docs/adr/0009)、利用者が持つファイルを、分析し直さずに移すための道具 (docs/adr/0010)。
書き換えるのは項目の名前だけで、値と書式 (コメント、並び、引用符) は変えない。
例外は 1 つ: 文 (値) の中で項目を指している「(tier: <id>)」という書き方は、「(layer: <id>)」に直す。

  対象 (分析する側が持つもの。配布物のコピー .abatlas/ は upgrade が置き換えるので、触らない)
    analysis/entry-list.yaml、analysis/results/*.yaml      tier → layer。文の中の「(tier: <id>)」も「(layer: <id>)」に
    analysis/dbt/models/repo/**/*.yml                       宣言の tier: core|profile|repo → origin
    自分用のプロファイル (作業定義の profile.dir が、分析リポジトリの中で、.abatlas/ の外を指すとき)
      profile.yaml                                          tiers → layers、tier → layer、zone → tier (tiers がある、前の形式のときだけ)
      dbt-template/models/**/*.yml                          宣言の tier → origin
  報告だけ (手で直す)
    上の dbt の *.sql の中の語 tier / tiers / zone (列の名前なら直す)

1 ファイルごとに、読み込んだ YAML の上で「項目名だけを入れ替えた、あるべき姿」を作り、文字の置き換えの結果を読み直して突き合わせる。
合わないファイル (文の中に項目と同じ形の行がある、書き方が特殊で置き換えられない、入れ替え先の名前が既にある、コメントも変わる) は、
書き換えずに知らせる。2 回動かしても、2 回目は何も変えない。
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from pathlib import Path

import yaml

from . import ANALYSIS_DIR, OSS_DIR
from .declarations import ORIGINS

PROSE = re.compile(r"\(tier: (\w+)\)", re.ASCII)  # 文の中で項目を指している書き方
DECL = re.compile(
    r"(?m)(^[ \t]*(?:- )?|[{,][ \t]*)([\"']?)tier\2(:[ \t]+[\"']?(?:"
    + "|".join(sorted(ORIGINS))
    + r")\b)"
)
SQL_WORD = re.compile(r"\b(?:tier|tiers|zone)\b")

# 入れ替える場所 (形式の定義で、その項目があった場所だけ。params や attributes のような、利用者が自由に書く対応表の中は触らない)。
# 場所は、前の項目名で書く。"*" は、並びの各要素
RESULT_SPEC = {
    ("entry",): {"tier": "layer"},
    ("callstack", "*"): {"tier": "layer"},  # 分析結果
    ("entries", "*"): {"tier": "layer"},
    ("extractors", "*"): {"tier": "layer"},
}  # 入口の一覧
PROFILE_SPEC = {
    (): {"tiers": "layers"},
    ("tiers", "*"): {"zone": "tier"},
    ("extractors", "*"): {"tier": "layer"},
    ("within", "*"): {"tier": "layer"},
}
RESULT_KEYS = {"tier": "layer"}
PROFILE_KEYS = {
    "tier": "layer",
    "tiers": "layers",
    "zone": "tier",
}  # 文字の置き換えは、この順で行う (移り先を、先に空ける)

HAND = "書き換えていない。手で直す"


class _Refuse(Exception):
    """このファイルは、機械では移せない。"""


def _key_re(name: str) -> re.Pattern:
    """項目の名前 (行頭、リストの項目の先頭、{ } の中)。値や文の中の語には当たらない。"""
    return re.compile(
        r"(?m)(^[ \t]*(?:- )?|[{,][ \t]*)([\"']?)"
        + re.escape(name)
        + r"\2(:(?:[ \t]|$))"
    )


def _put(out: dict, k, v) -> None:
    if k in out:
        raise _Refuse(
            f"同じ場所に、入れ替え先の項目 '{k}' が既にある (前の名前と、いまの名前が並んでいる)"
        )
    out[k] = v


def _rename(o, spec: dict, prose: bool, path: tuple = ()) -> tuple[object, int]:
    """読み込んだ YAML の上で、項目名を入れ替えた「あるべき姿」と、入れ替えた項目の数を返す。元の名前だけを見るので、入れ替えが連鎖しない。

    入れ替え先の名前が、同じ場所に既にあるとき (tier と layer が並ぶ、など) は、片方が失われるので断る。
    """
    if isinstance(o, dict):
        keys, out, n = spec.get(path, {}), {}, 0
        for k, v in o.items():
            nv, c = _rename(v, spec, prose, (*path, k))
            n += c + (1 if k in keys else 0)
            _put(out, keys.get(k, k) if isinstance(k, str) else k, nv)
        return out, n
    if isinstance(o, list):
        pairs = [_rename(v, spec, prose, (*path, "*")) for v in o]
        return [x for x, _ in pairs], sum(c for _, c in pairs)
    if isinstance(o, str) and prose:
        return PROSE.sub(r"(layer: \1)", o), 0
    return o, 0


def _rename_decl(o, decl: bool = False) -> tuple[object, int]:
    """集計表の宣言 (abatlas: の直下) の、値が core / profile / repo の tier だけを origin にする。ほかの場所の tier は、そのまま。"""
    if isinstance(o, dict):
        out, n = {}, 0
        for k, v in o.items():
            hit = decl and k == "tier" and isinstance(v, str) and v in ORIGINS
            nv, c = _rename_decl(v, k == "abatlas")
            n += c + (1 if hit else 0)
            _put(out, "origin" if hit else k, nv)
        return out, n
    if isinstance(o, list):
        pairs = [_rename_decl(v) for v in o]
        return [x for x, _ in pairs], sum(c for _, c in pairs)
    return o, 0


def _prose_in_values(o) -> int:
    """値 (文) の中の「(tier: <id>)」の数。文字全体の数と違えば、コメントや項目名の中にもある。"""
    if isinstance(o, dict):
        return sum(_prose_in_values(v) for v in o.values())
    if isinstance(o, list):
        return sum(_prose_in_values(v) for v in o)
    return len(PROSE.findall(o)) if isinstance(o, str) else 0


def _write(path: Path, text: str) -> None:
    """同じ場所の一時ファイルに書いてから、入れ替える (途中で止まっても、元のファイルが半端にならない)。"""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        shutil.copymode(path, tmp)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _mismatch_reason(new, old):
    why = (
        "前の項目名が、機械で置き換えられない書き方 (アンカー、項目名の後ろの空白など) で書かれている"
        if new == old
        else "項目名のほかも変わってしまう (文の中や、形式で決まった場所のほか (params、attributes、宣言でない場所) に、項目と同じ形の行がある) か、置き換えられない書き方の項目が残る"
    )
    return f"NG: {why}。{HAND}"


def _migration_jobs(repo, an):
    jobs: list[tuple[Path, object]] = []
    if (an / "entry-list.yaml").exists():
        jobs.append((an / "entry-list.yaml", migrate_result))
    jobs += [(f, migrate_result) for f in sorted((an / "results").glob("*.yaml"))]
    dbt_dirs = [an / "dbt" / "models" / "repo"]
    prof, note = _custom_profile(repo)
    if prof is not None:
        if (prof / "profile.yaml").exists():
            jobs.append((prof / "profile.yaml", migrate_profile))
        dbt_dirs.append(prof / "dbt-template" / "models")
    for d in dbt_dirs:
        jobs += [
            (f, migrate_declaration)
            for f in sorted([*d.rglob("*.yml"), *d.rglob("*.yaml")])
        ]
    return jobs, dbt_dirs, note


def _report_sql_names(repo, dbt_dirs, lines):
    for d in dbt_dirs:
        for q in sorted(d.rglob("*.sql")):
            words = sorted(
                set(SQL_WORD.findall(q.read_text(encoding="utf-8", errors="replace")))
            )
            if words:
                lines.append(
                    f"  {_show(repo, q)}: SQL の中に {', '.join(words)} がある。前の名前の列なら、手で直す (tier → layer、宣言の持ち主は origin)"
                )


def _apply(path: Path, new_text, expect, dry: bool, prose: bool = False) -> str:
    """1 ファイルを書き換える。返すのは「変更なし」「書き換え」「NG: 理由」。

    new_text は (元の文字) を受けて (置き換えた文字, 置き換えた項目の数) を、expect は (読み込んだ元の YAML) を受けて (あるべき姿, 入れ替える項目の数) を返す関数。
    """
    try:
        with path.open(encoding="utf-8", newline="") as f:  # 改行の形を保つ
            old = f.read()
        before = yaml.safe_load(old)
    except Exception as ex:
        return f"NG: 読めない ({str(ex).splitlines()[0]})"
    try:
        want, n_want = expect(before)
    except _Refuse as ex:
        return f"NG: {ex}。{HAND}"
    if want == before:
        return "変更なし"
    if prose and len(PROSE.findall(old)) != _prose_in_values(before):
        return f"NG: 文のほか (コメントなど) にも「(tier: <id>)」がある。機械で書き換えると、そこも変わる。{HAND}"
    new, n_new = new_text(old)
    try:
        after = yaml.safe_load(new)
    except Exception as ex:
        return f"NG: 書き換えると YAML として読めなくなる ({str(ex).splitlines()[0]})。{HAND}"
    if after != want:
        return _mismatch_reason(new, old)
    if (
        n_new != n_want
    ):  # 読み直しでは見えない場所 (コメント) の、項目と同じ形の書き方も変わる
        return f"NG: コメントの中にも、項目と同じ形の書き方がある。機械で書き換えると、そこも変わる。{HAND}"
    if not dry:
        _write(path, new)
    return "書き換え"


def _keys(text: str, keys: dict[str, str]) -> tuple[str, int]:
    total = 0
    for old, new in keys.items():
        text, n = _key_re(old).subn(
            lambda m, new=new: f"{m.group(1)}{m.group(2)}{new}{m.group(2)}{m.group(3)}",
            text,
        )
        total += n
    return text, total


def migrate_result(path: Path, dry: bool) -> str:
    """入口の一覧、分析結果: tier → layer。"""

    def text(s: str) -> tuple[str, int]:
        t, n = _keys(s, RESULT_KEYS)
        return PROSE.sub(r"(layer: \1)", t), n

    return _apply(path, text, lambda d: _rename(d, RESULT_SPEC, True), dry, prose=True)


def migrate_profile(path: Path, dry: bool) -> str:
    """プロファイル: tiers → layers、tier → layer、zone → tier。前の形式 (tiers がある) のときだけ (新しい形式の tier は、区分)。"""
    try:
        cur = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as ex:
        return f"NG: 読めない ({str(ex).splitlines()[0]})"
    if not isinstance(cur, dict) or "tiers" not in cur:
        return "変更なし"
    return _apply(
        path,
        lambda s: _keys(s, PROFILE_KEYS),
        lambda d: _rename(d, PROFILE_SPEC, False),
        dry,
    )


def migrate_declaration(path: Path, dry: bool) -> str:
    """集計表の宣言: tier: core|profile|repo → origin。"""
    return _apply(
        path,
        lambda s: DECL.subn(
            lambda m: f"{m.group(1)}{m.group(2)}origin{m.group(2)}{m.group(3)}", s
        ),
        _rename_decl,
        dry,
    )


def _inside(repo: Path, p: Path) -> bool:
    """p の実体 (リンクを辿った先) が、分析リポジトリの中で、配布物のコピーの外にあるか。"""
    root, real = repo.resolve(), p.resolve()
    lexical = Path(
        os.path.normpath(
            os.path.join(root, os.path.relpath(p.absolute(), repo.absolute()))
        )
    )  # リンクを辿らない場所 (.abatlas 自体がリンクのとき)
    oss = (root / OSS_DIR, (root / OSS_DIR).resolve())
    return real.is_relative_to(root) and not any(
        x.is_relative_to(o) for x in (real, lexical) for o in oss
    )


def _custom_profile(repo: Path) -> tuple[Path | None, str | None]:
    """自分用のプロファイルの場所と、触らないときの知らせ。作業定義の profile.dir が、分析リポジトリの中で、配布物のコピーの外を指すときだけ返す。"""
    wd = repo / ANALYSIS_DIR / "work-definition.yaml"
    if not wd.exists():
        return None, None
    try:
        doc = yaml.safe_load(wd.read_text(encoding="utf-8"))
        prof = doc.get("profile") if isinstance(doc, dict) else None
        rel = prof.get("dir") if isinstance(prof, dict) else None
    except Exception as ex:
        return (
            None,
            f"  {ANALYSIS_DIR}/work-definition.yaml: NG: 読めない ({str(ex).splitlines()[0]})。自分用のプロファイルがあるかを確かめられない。直してから、やり直す",
        )
    if not isinstance(rel, str) or not rel:
        return None, None
    d = repo / rel  # 絶対パスなら、そのパス
    if not d.resolve().is_relative_to(repo.resolve()):
        return (
            None,
            f"  作業定義の profile.dir '{rel}' は、分析リポジトリの外を指すので、触らない",
        )
    if not _inside(repo, d) or not d.is_dir():
        return None, None  # 配布物のコピー (upgrade が置き換える) か、無い
    return d, None


def _show(repo: Path, p: Path) -> str:
    """報告に出す場所 (分析リポジトリからの相対)。"""
    return os.path.relpath(p, repo)


def _migrate_file(repo, path, fn, dry):
    if (
        path.is_symlink()
    ):  # 入れ替えると、リンクが普通のファイルになり、リンクの先は前の形式のまま残る
        r = f"NG: リンク。リンクの先のファイルを、{HAND}"
    elif not _inside(
        repo, path
    ):  # 途中のディレクトリがリンクで、実体が外や、配布物のコピーにある
        r = f"NG: 実体が、分析リポジトリの外か、配布物のコピー ({OSS_DIR}/) にある。{HAND}"
    else:
        r = fn(path, dry)
    return r


def migrate_repo(repo: Path, dry: bool = False) -> tuple[list[str], int]:
    """分析リポジトリを書き換える。返すのは (報告の行, 終了コード)。終了コード: 0 = 済み (変更なしを含む) / 1 = 書き換えられなかったファイルがある。"""
    repo = (
        repo.resolve()
    )  # 相対パスで渡されても、報告の場所を、分析リポジトリからの相対で出せるように
    an = repo / ANALYSIS_DIR
    if not an.is_dir():
        raise SystemExit(
            f"{repo} に {ANALYSIS_DIR}/ が無い。分析リポジトリのルートを渡す"
        )
    jobs, dbt_dirs, note = _migration_jobs(repo, an)

    lines: list[str] = [note] if note else []
    counts = {"書き換え": 0, "変更なし": 0, "NG": 1 if note and "NG:" in note else 0}
    for path, fn in jobs:
        r = _migrate_file(repo, path, fn, dry)
        counts[r.split(":")[0]] += 1
        if r != "変更なし":
            lines.append(f"  {_show(repo, path)}: {r}")
    _report_sql_names(repo, dbt_dirs, lines)
    return _migration_summary(lines, counts, dry)


def _migration_summary(lines, counts, dry):
    head = f"migrate{' (dry-run。書き換えていない)' if dry else ''}: 書き換え {counts['書き換え']} / 変更なし {counts['変更なし']} / 書き換えられなかった {counts['NG']}"
    tail = (
        []
        if dry or not counts["書き換え"]
        else [
            "  次: 検査 (validate entries / validate result) と、集計 (build) をやり直す"
        ]
    )
    return [head, *lines, *tail], (1 if counts["NG"] else 0)
