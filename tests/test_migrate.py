"""abatlas migrate: 前の項目名の分析リポジトリを、いまの形式に書き換える (docs/adr/0010)。"""

import re
import shutil
from pathlib import Path

import pytest
import yaml

from abatlas.cli import main
from abatlas.migrate import migrate_repo
from abatlas.schemas import load_yaml
from abatlas.validate import (
    validate_analysis_result,
    validate_entry_list,
    validate_profile,
)

ROOT = Path(__file__).resolve().parent.parent
KOTORI = ROOT / "examples" / "kotori-books-atlas"
PROFILE = ROOT / "profiles" / "batch-kestra"


def _key(name: str) -> re.Pattern:
    return re.compile(r"(?m)(^[ \t]*(?:- )?)" + name + r"(:(?:[ \t]|$))")


def _old_result(text: str) -> str:
    """いまの形式の入口の一覧・分析結果を、前の項目名に戻す。"""
    return _key("layer").sub(r"\1tier\2", text)


def _old_profile(text: str) -> str:
    text = _key("tier").sub(r"\1zone\2", text)
    text = _key("layer").sub(r"\1tier\2", text)
    return _key("layers").sub(r"\1tiers\2", text)


@pytest.fixture
def old_repo(tmp_path):
    """前の項目名で書かれた分析リポジトリ (ことり書店の見本から作る)。自分用のプロファイルと、独自の集計表を持つ。"""
    repo = tmp_path / "atlas"
    shutil.copytree(
        KOTORI / "analysis", repo / "analysis", ignore=shutil.ignore_patterns("data")
    )
    an = repo / "analysis"
    now = {}
    for f in [an / "entry-list.yaml", *sorted((an / "results").glob("*.yaml"))]:
        now[f] = f.read_text(encoding="utf-8")
        f.write_text(_old_result(now[f]), encoding="utf-8")
    prof = an / "profiles" / "mine"
    shutil.copytree(PROFILE, prof)
    now[prof / "profile.yaml"] = (prof / "profile.yaml").read_text(encoding="utf-8")
    (prof / "profile.yaml").write_text(
        _old_profile(now[prof / "profile.yaml"]), encoding="utf-8"
    )
    wd = an / "work-definition.yaml"
    d = yaml.safe_load(wd.read_text(encoding="utf-8"))
    d["profile"]["dir"] = "analysis/profiles/mine"
    wd.write_text(
        yaml.safe_dump(d, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    models = an / "dbt" / "models" / "repo"
    models.mkdir(parents=True, exist_ok=True)
    (models / "mine.yml").write_text(
        "models:\n  - name: mart_mine\n    meta:\n      abatlas:\n        tier: repo   # 持ち主\n        view: table\n",
        encoding="utf-8",
    )
    (models / "mart_mine.sql").write_text(
        "select tier, count(*) as n from {{ ref('frames') }} group by 1\n",
        encoding="utf-8",
    )
    return repo, now


def test_migrate_restores_current_names_and_keeps_format(old_repo):
    """項目名だけが変わり、書式 (コメント、並び) はそのまま: 見本を前の名前に戻したものが、元の文字に戻る。"""
    repo, now = old_repo
    an = repo / "analysis"
    assert "tier:" in (an / "entry-list.yaml").read_text(encoding="utf-8")
    lines, rc = migrate_repo(repo)
    assert rc == 0, lines
    for f, text in now.items():
        assert f.read_text(encoding="utf-8") == text, f
    decl = (an / "dbt" / "models" / "repo" / "mine.yml").read_text(encoding="utf-8")
    assert "origin: repo   # 持ち主" in decl and "tier:" not in decl
    assert any("mart_mine.sql" in ln and "手で直す" in ln for ln in lines), (
        "SQL は書き換えず、知らせる"
    )
    assert "select tier," in (
        an / "dbt" / "models" / "repo" / "mart_mine.sql"
    ).read_text(encoding="utf-8")
    # 書き換えた後は、検査に通る
    prof = load_yaml(an / "profiles" / "mine" / "profile.yaml")
    assert validate_profile(prof) == []
    assert validate_entry_list(load_yaml(an / "entry-list.yaml"), prof) == []
    one = sorted((an / "results").glob("*.yaml"))[0]
    assert (
        validate_analysis_result(load_yaml(one), prof, None) == []
    )  # 根拠の実在は見ない (対象のコードを写していない)


def test_migrate_is_idempotent_and_dry_run_writes_nothing(old_repo):
    repo, _ = old_repo
    before = {f: f.read_bytes() for f in repo.rglob("*") if f.is_file()}
    lines, rc = migrate_repo(repo, dry=True)
    assert rc == 0 and "dry-run" in lines[0] and "書き換え 0" not in lines[0]
    assert {f: f.read_bytes() for f in repo.rglob("*") if f.is_file()} == before, (
        "dry-run は書かない"
    )
    migrate_repo(repo)
    after = {f: f.read_bytes() for f in repo.rglob("*") if f.is_file()}
    lines, rc = migrate_repo(repo)
    assert rc == 0 and "書き換え 0 " in lines[0], lines
    assert {f: f.read_bytes() for f in repo.rglob("*") if f.is_file()} == after, (
        "2 回目は何も変えない (新しい形式の tier = 区分を、layer にしない)"
    )


def test_migrate_refuses_file_when_more_than_names_would_change(old_repo):
    """文の中に、項目と同じ形の行があるファイルは、書き換えずに知らせる (ほかのファイルは書き換える)。"""
    repo, _ = old_repo
    bad = sorted((repo / "analysis" / "results").glob("*.yaml"))[0]
    text = (
        bad.read_text(encoding="utf-8")
        + "notes: |\n  次の行は、文。\n  tier: これは項目ではない\n"
    )
    bad.write_text(text, encoding="utf-8")
    lines, rc = migrate_repo(repo)
    assert rc == 1
    assert any(bad.name in ln and "NG" in ln and "手で直す" in ln for ln in lines), (
        lines
    )
    assert bad.read_text(encoding="utf-8") == text
    assert "tier:" not in (repo / "analysis" / "entry-list.yaml").read_text(
        encoding="utf-8"
    )


def test_migrate_leaves_oss_copy_and_reports_missing_repo(tmp_path, capsys):
    """配布物のコピー (.abatlas/) は触らない (upgrade が置き換える)。分析リポジトリでない場所は、理由を出して止まる。"""
    repo = tmp_path / "atlas"
    (repo / "analysis" / "results").mkdir(parents=True)
    (repo / "analysis" / "work-definition.yaml").write_text(
        "profile:\n  id: batch-kestra\n  dir: .abatlas/profiles/batch-kestra\n",
        encoding="utf-8",
    )
    oss = repo / ".abatlas" / "profiles" / "batch-kestra"
    oss.mkdir(parents=True)
    old = _old_profile((PROFILE / "profile.yaml").read_text(encoding="utf-8"))
    (oss / "profile.yaml").write_text(old, encoding="utf-8")
    assert main(["migrate", str(repo)]) == 0
    assert (oss / "profile.yaml").read_text(encoding="utf-8") == old
    assert "書き換え 0 " in capsys.readouterr().out
    assert main(["migrate", str(tmp_path / "nowhere")]) == 2
    assert "analysis/ が無い" in capsys.readouterr().err


def _result_repo(tmp_path, text: str):
    repo = tmp_path / "atlas"
    (repo / "analysis" / "results").mkdir(parents=True)
    f = repo / "analysis" / "results" / "a.yaml"
    f.write_text(text, encoding="utf-8")
    return repo, f


@pytest.mark.parametrize(
    "text, why",
    [
        (
            "entry:\n  tier: old\n  layer: current\n",
            "入れ替え先の項目",
        ),  # 前の名前と、いまの名前が並ぶ (片方が失われる)
        (
            "entry:\n  tier : scheduler\n",
            "置き換えられない書き方",
        ),  # 項目名の後ろの空白
        ("entry:\n  &k tier: scheduler\n", "置き換えられない書き方"),  # アンカー
        (
            "entry:\n  tier: a\ncallstack:\n  - tier : b\n",
            "置き換えられない書き方",
        ),  # 一部だけ置き換えられる
        (
            'entry:\n  tier: a\n# 参考 (tier: a)\nnotes: "入口 (tier: a)"\n',
            "コメント",
        ),  # コメントの中の書き方も変わってしまう
        (
            "entry:\n  tier: a\n# see {tier: legacy}\n",
            "コメント",
        ),  # コメントの中の、項目と同じ形
        (
            "entries:\n  - tier: a\n    attributes:\n      tier: gold\n",
            "attributes",
        ),  # 自由に書ける対応表の中の tier は、項目ではない
        ("extractors:\n  - tier: a\n    params: {tier: x}\n", "params"),
    ],
)
def test_migrate_refuses_what_it_cannot_move_safely(tmp_path, text, why):
    """機械で安全に移せないファイルは、書き換えずに、理由を知らせる (止まる条件ごと)。"""
    repo, f = _result_repo(tmp_path, text)
    lines, rc = migrate_repo(repo)
    assert rc == 1 and any(
        "a.yaml" in ln and "NG" in ln and why in ln for ln in lines
    ), lines
    assert f.read_text(encoding="utf-8") == text
    assert not [x for x in f.parent.iterdir() if x != f], "一時ファイルを残さない"


def test_migrate_handles_quotes_inline_and_prose(tmp_path):
    """引用符つきの項目、{ } の中の項目、文の中の「(tier: <id>)」を移す。コメントと改行の形 (CRLF) は、そのまま。"""
    text = 'entry: {"tier": scheduler, id: a}\r\ncallstack:\r\n  - \'tier\': shell   # tier のコメント\r\nnotes: "入口 (tier: scheduler) を見た"\r\n'
    repo, f = _result_repo(tmp_path, "")
    f.write_bytes(text.encode("utf-8"))
    lines, rc = migrate_repo(repo)
    assert rc == 0, lines
    assert (
        f.read_bytes().decode("utf-8")
        == 'entry: {"layer": scheduler, id: a}\r\ncallstack:\r\n  - \'layer\': shell   # tier のコメント\r\nnotes: "入口 (layer: scheduler) を見た"\r\n'
    )


def test_migrate_declaration_keeps_other_tier_values(tmp_path):
    """宣言の tier のうち、値が core / profile / repo のものだけを origin にする。値が対応表のものは、そのまま (落ちない)。"""
    repo = tmp_path / "atlas"
    models = repo / "analysis" / "dbt" / "models" / "repo"
    models.mkdir(parents=True)
    f = models / "mine.yml"
    f.write_text(
        "models:\n  - name: m\n    meta:\n      abatlas:\n        tier: repo\n      other:\n        tier: {name: core}\n",
        encoding="utf-8",
    )
    lines, rc = migrate_repo(repo)
    assert rc == 0, lines
    assert (
        f.read_text(encoding="utf-8")
        == "models:\n  - name: m\n    meta:\n      abatlas:\n        origin: repo\n      other:\n        tier: {name: core}\n"
    )


@pytest.mark.parametrize("rel", ["analysis/../.abatlas/profiles/x", "../outside"])
def test_migrate_never_writes_outside_repo_or_into_oss_copy(tmp_path, rel):
    """作業定義の profile.dir が、回り道で配布物のコピーや、分析リポジトリの外を指しても、そこを書き換えない。"""
    repo = tmp_path / "atlas"
    (repo / "analysis").mkdir(parents=True)
    (repo / "analysis" / "work-definition.yaml").write_text(
        f"profile:\n  id: x\n  dir: {rel}\n", encoding="utf-8"
    )
    old = _old_profile((PROFILE / "profile.yaml").read_text(encoding="utf-8"))
    target = (repo / rel).resolve() / "profile.yaml"
    target.parent.mkdir(parents=True)
    target.write_text(old, encoding="utf-8")
    lines, rc = migrate_repo(repo)
    assert rc == 0 and "書き換え 0 " in lines[0], lines
    assert target.read_text(encoding="utf-8") == old
    if rel.startswith(".."):
        assert any("外を指す" in ln for ln in lines), "触らない理由を知らせる"


def test_migrate_refuses_symlink_leaving_repo(tmp_path):
    """分析結果が、分析リポジトリの外へのリンクなら、リンクの先を書き換えない。"""
    repo, f = _result_repo(tmp_path, "")
    outside = tmp_path / "outside.yaml"
    outside.write_text("entry:\n  tier: a\n", encoding="utf-8")
    f.unlink()
    f.symlink_to(outside)
    lines, rc = migrate_repo(repo)
    assert rc == 1 and any("a.yaml" in ln and "リンク" in ln for ln in lines), lines
    assert outside.read_text(encoding="utf-8") == "entry:\n  tier: a\n"


def test_migrate_refuses_symlink_inside_repo(tmp_path):
    """分析リポジトリの中へのリンクも、書き換えない (入れ替えると、リンクが普通のファイルになり、リンクの先が前の形式のまま残る)。"""
    repo, f = _result_repo(tmp_path, "")
    shared = repo / "analysis" / "shared.yaml"
    shared.write_text("entry:\n  tier: a\n", encoding="utf-8")
    f.unlink()
    f.symlink_to(shared)
    lines, rc = migrate_repo(repo)
    assert rc == 1 and any("a.yaml" in ln and "リンク" in ln for ln in lines), lines
    assert (
        f.is_symlink() and shared.read_text(encoding="utf-8") == "entry:\n  tier: a\n"
    )


def test_migrate_skips_oss_copy_that_is_a_symlink(tmp_path):
    """.abatlas 自体が、分析リポジトリの中へのリンクでも、その下のプロファイルを書き換えない。"""
    repo = tmp_path / "atlas"
    real = repo / "vendor" / "profiles" / "x"
    real.mkdir(parents=True)
    old = _old_profile((PROFILE / "profile.yaml").read_text(encoding="utf-8"))
    (real / "profile.yaml").write_text(old, encoding="utf-8")
    (repo / ".abatlas").symlink_to(repo / "vendor")
    (repo / "analysis").mkdir()
    (repo / "analysis" / "work-definition.yaml").write_text(
        "profile:\n  id: x\n  dir: .abatlas/profiles/x\n", encoding="utf-8"
    )
    lines, rc = migrate_repo(repo)
    assert rc == 0 and "書き換え 0 " in lines[0], lines
    assert (real / "profile.yaml").read_text(encoding="utf-8") == old


def test_migrate_absolute_profile_dir_inside_repo_and_unreadable_work_definition(
    tmp_path,
):
    """profile.dir が、分析リポジトリの中の絶対パスなら移す。作業定義が読めないときは、黙って飛ばさず、指摘にする。"""
    repo = tmp_path / "atlas"
    prof = repo / "analysis" / "profiles" / "mine"
    shutil.copytree(PROFILE, prof)
    now = (prof / "profile.yaml").read_text(encoding="utf-8")
    (prof / "profile.yaml").write_text(_old_profile(now), encoding="utf-8")
    wd = repo / "analysis" / "work-definition.yaml"
    wd.write_text(f"profile:\n  id: x\n  dir: {prof}\n", encoding="utf-8")
    lines, rc = migrate_repo(repo)
    assert rc == 0 and (prof / "profile.yaml").read_text(encoding="utf-8") == now, lines
    wd.write_text("profile: [\n", encoding="utf-8")
    lines, rc = migrate_repo(repo)
    assert rc == 1 and any(
        "work-definition.yaml" in ln and "NG" in ln for ln in lines
    ), lines


def test_migrate_declaration_only_under_abatlas(tmp_path):
    """宣言で直すのは、abatlas: の直下の tier だけ。ほかの場所に同じ形の tier があるファイルは、書き換えずに知らせる。"""
    repo = tmp_path / "atlas"
    models = repo / "analysis" / "dbt" / "models" / "repo"
    models.mkdir(parents=True)
    f = models / "mine.yml"
    text = "models:\n  - name: m\n    meta:\n      abatlas:\n        tier: repo\n      owner:\n        tier: repo\n"
    f.write_text(text, encoding="utf-8")
    lines, rc = migrate_repo(repo)
    assert rc == 1 and any("mine.yml" in ln and "NG" in ln for ln in lines), lines
    assert f.read_text(encoding="utf-8") == text


def test_migrate_relative_repo_with_absolute_profile_dir(tmp_path, monkeypatch):
    """分析リポジトリを「.」で渡し、profile.dir が中の絶対パスでも、報告まで通る。"""
    repo = tmp_path / "atlas"
    prof = repo / "analysis" / "profiles" / "mine"
    shutil.copytree(PROFILE, prof)
    now = (prof / "profile.yaml").read_text(encoding="utf-8")
    (prof / "profile.yaml").write_text(_old_profile(now), encoding="utf-8")
    (repo / "analysis" / "work-definition.yaml").write_text(
        f"profile:\n  id: x\n  dir: {prof.resolve()}\n", encoding="utf-8"
    )
    monkeypatch.chdir(repo)
    assert main(["migrate", ".", "--dry-run"]) == 0
    assert main(["migrate", "."]) == 0
    assert (prof / "profile.yaml").read_text(encoding="utf-8") == now


def test_migrate_declaration_refuses_comment_with_same_shape(tmp_path):
    """宣言のファイルでも、コメントの中の、項目と同じ形の書き方が変わるなら、書き換えない。"""
    repo = tmp_path / "atlas"
    models = repo / "analysis" / "dbt" / "models" / "repo"
    models.mkdir(parents=True)
    text = "models:\n  - name: m\n    meta:\n      abatlas:\n        tier: repo\n# see {tier: repo}\n"
    (models / "mine.yml").write_text(text, encoding="utf-8")
    lines, rc = migrate_repo(repo)
    assert rc == 1 and any("mine.yml" in ln and "コメント" in ln for ln in lines), lines
    assert (models / "mine.yml").read_text(encoding="utf-8") == text
