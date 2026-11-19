"""見本は、プロファイルごとに 1 つ (docs/rules/examples.md)。どの見本にも当てはまる検査。

見本ごとの中身の検査は、ことり書店が tests/test_examples.py、umami が tests/test_examples_umami.py。
ここで確かめるのは、対象の clone が無くても分かることだけ (根拠の行の実在は、対象を隣に clone して `abatlas validate result --work` で確かめる)。
"""

from __future__ import annotations

import importlib.util
import re
import shutil
from pathlib import Path

import pytest
import yaml

from abatlas import ANALYSIS_DIR, REPO_ROOT
from abatlas.build import build_repo
from abatlas.layout import init_repo
from abatlas.validate import validate_analysis_result, validate_entry_list, validate_review, validate_work_definition

EXAMPLES = REPO_ROOT / "examples"
# 写すスクリプトは、パッケージではない (examples/generator/ の下の、単独のスクリプト)
_spec = importlib.util.spec_from_file_location("import_atlas", EXAMPLES / "generator" / "import_atlas.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
import_atlas, replace_clone_path = _mod.import_atlas, _mod.replace_clone_path
# 見本は、examples/ の直下の、名前が -atlas で終わるディレクトリ (作業定義を入れ忘れた見本も、検査から漏らさない)
ATLASES = sorted(p for p in EXAMPLES.iterdir() if p.is_dir() and p.name.endswith("-atlas"))
GENERATED = {"kotori-books-atlas"}   # 生成スクリプトが作る正解。対象を同梱し、レビューを持たない


def _load(p: Path) -> dict:
    return yaml.safe_load(p.read_text(encoding="utf-8"))


def _profile_id(atlas: Path) -> str:
    return _load(atlas / ANALYSIS_DIR / "work-definition.yaml")["profile"]["id"]


def _same_target(a: dict, b: dict) -> bool:
    """どの対象の、どの範囲の、どのコミットか。表示名と clone の場所は、比べない (結果に写さない書き方もある)。"""
    return all(a.get(k) == b.get(k) for k in ("repo", "scope", "commit"))


def test_every_profile_has_exactly_one_example():
    assert [a.name for a in ATLASES if not (a / ANALYSIS_DIR / "work-definition.yaml").is_file()] == [], "作業定義の無い見本"
    stray = sorted(p.parent.parent.name for p in EXAMPLES.glob(f"*/{ANALYSIS_DIR}/work-definition.yaml") if p.parent.parent not in ATLASES)
    assert stray == [], "分析リポジトリの資産は、名前が -atlas で終わるディレクトリに置く"
    profiles = sorted(p.parent.name for p in (REPO_ROOT / "profiles").glob("*/profile.yaml"))
    by_profile: dict[str, list[str]] = {}
    for atlas in ATLASES:
        by_profile.setdefault(_profile_id(atlas), []).append(atlas.name)
    assert sorted(by_profile) == profiles, f"見本の無いプロファイル: {sorted(set(profiles) - set(by_profile))}、プロファイルの無い見本: {sorted(set(by_profile) - set(profiles))}"
    assert {k: v for k, v in by_profile.items() if len(v) != 1} == {}, "見本は、プロファイルごとに 1 つ"


@pytest.mark.parametrize("atlas", ATLASES, ids=lambda p: p.name)
def test_example_is_consistent_without_its_target(atlas: Path):
    an = atlas / ANALYSIS_DIR
    work, el = _load(an / "work-definition.yaml"), _load(an / "entry-list.yaml")
    pid = work["profile"]["id"]
    profile = _load(REPO_ROOT / "profiles" / pid / "profile.yaml")
    assert validate_work_definition(work) == [] and validate_entry_list(el, profile) == []
    assert _same_target(el["target"], work["target"]) and el["profile"] == {"id": pid, "version": profile["version"]}
    by_id = {e["id"]: e for e in el["entries"]}
    results = {p.stem: _load(p) for p in sorted((an / "results").glob("*.yaml"))}
    assert len(results) >= 3, "プロファイルの書き方が分かる数 (3 件以上) の結果を置く"
    assert set(results) == {i for i, e in by_id.items() if e["status"] == "approved"}, "承認済みの入口と、分析結果は、1 対 1 (承認して、結果を置き忘れない)"
    clone = work["target"]["clone_path"]
    assert el["target"].get("clone_path", clone) == clone
    for eid, r in results.items():
        assert by_id[eid]["status"] == "approved", f"{eid}: 承認済みの入口の結果だけを置く"
        assert validate_analysis_result(r, profile, None, entry_ids=set(by_id)) == [], eid
        assert r["entry"]["id"] == eid and r["entry"]["layer"] == by_id[eid]["layer"] and _same_target(r["target"], work["target"]), eid
        assert r["target"].get("clone_path", clone) == clone, f"{eid}: 結果の clone の場所が、作業定義と違う"
        assert r["analyzer"]["profile"] == {"id": pid, "version": profile["version"]}, f"{eid}: 今のプロファイルの版で分析した結果だけを置く"
        if atlas.name not in GENERATED:
            assert validate_review(_load(an / "reviews" / f"{eid}.yaml"), r) == [], eid
    if atlas.name not in GENERATED:
        assert {p.stem for p in (an / "reviews").glob("*.yaml")} == set(results), "結果とレビューは、1 対 1"


# 手元の環境の絶対パス。URL の形のパス (/api/…、/(shell)/root/… など) は分析結果にふつうに現れるので、OS のルート直下の名前で見分ける
_LOCAL_PATH = re.compile(
    r"(?<![\w.$\]})/-])/(?:Users|home|private|var|tmp|mnt|opt|root|Volumes|workspace|workspaces|ws|srv|etc|usr)/|(?<![\w$])[A-Za-z]:\\(?![nrt](?:\W|$))|~/", re.A
)
_CODE_SUFFIXES = {".ts", ".tsx", ".js", ".jsx", ".vue", ".svelte", ".kt", ".swift", ".go", ".rb", ".java", ".sql"}


def test_local_path_pattern():
    assert all(_LOCAL_PATH.search(s) for s in ("clone_path: /Users/me/umami", "at /private/tmp/x", "C:\\work", "see ~/src"))
    assert not _LOCAL_PATH.search("GET /api/users/[userId] と /home の画面、basePath + /api、`${base}/tmp/x`、/(shell)/root/AppView、-> $R:\\n    $$$BODY")


@pytest.mark.parametrize("atlas", [a for a in ATLASES if a.name not in GENERATED], ids=lambda p: p.name)
def test_example_ships_no_local_paths_or_target_code(atlas: Path):
    an = atlas / ANALYSIS_DIR
    files = [p for p in atlas.rglob("*") if p.is_file()]
    assert not [p.name for p in files if p.suffix in _CODE_SUFFIXES], "対象のコードは入れない"
    assert {p.suffix for p in files} <= {".yaml", ".md", "", ".env", ".gitignore"}
    for p in files:
        text = p.read_text(encoding="utf-8")
        if p == atlas / "README.md":
            # 使い方の説明に書く 2 つの場所だけは許す: 試す場所 ~/abatlas-try と、コンテナの中の /ws/analysis
            text = text.replace("~/abatlas-try", "<try>").replace('"$PWD:/ws/analysis" -w /ws/analysis', "<mount>")
        hit = _LOCAL_PATH.search(text)
        assert hit is None, f"{p.relative_to(atlas)}: 手元の絶対パスらしい文字列が残っている: {hit.group(0)!r}"
    clone = _load(an / "work-definition.yaml")["target"]["clone_path"]
    assert re.fullmatch(r"\.\./[\w.-]+", clone), "対象は、見本の隣に clone する"
    assert f"ABATLAS_TARGET={clone}\n" in (atlas / ".env").read_text(encoding="utf-8")
    readme = (atlas / "README.md").read_text(encoding="utf-8")
    assert "License" in readme or "ライセンス" in readme, "対象と、そのライセンスを README に書く"
    assert "git clone" in readme and clone[3:] in readme, "対象を隣に clone する手順を README に書く"


# ことり書店と umami は、それぞれのテストが init → build を確かめている
@pytest.mark.parametrize("atlas", [a for a in ATLASES if a.name not in GENERATED | {"umami-atlas"}], ids=lambda p: p.name)
def test_example_builds_outside_the_checkout(atlas: Path, tmp_path: Path):
    """見本を checkout の外にコピーし、init → build まで通す (対象の clone は、集計には要らない)。"""
    repo = tmp_path / atlas.name
    shutil.copytree(atlas, repo)
    env = (repo / ".env").read_text(encoding="utf-8")
    init_repo(repo, _profile_id(atlas), targets="claude-code")
    assert (repo / ".env").read_text(encoding="utf-8") == env, "見本の .env は、上書きされない"
    rep = build_repo(repo)
    assert rep["dbt_ok"] == rep["dbt_nodes"] and rep["stale_results"] == 0, rep


def test_import_replaces_only_the_target_clone_path():
    text = "format_version: 1\ntarget:\n  repo: github.com/x/y\n  clone_path: /Users/me/y   # 手元の場所\n  commit: abc\nnotes: |\n  clone_path: /Users/me/example-in-explanation\ncallstack:\n  - clone_path: keep\n"
    out = replace_clone_path(text, "../y")
    assert out == text.replace("clone_path: /Users/me/y   # 手元の場所", "clone_path: ../y"), "置き換えるのは、いちばん上の target の中の 1 行だけ"
    # ファイルの最後の行 (改行なし) でも、間に空行があっても、置き換える
    assert replace_clone_path("target:\n  repo: github.com/x/y\n  clone_path: /Users/me/y", "../y").endswith("clone_path: ../y")
    assert "clone_path: ../y\n" in replace_clone_path("target:\n  repo: github.com/x/y\n\n  clone_path: /Users/me/y\nnotes: x\n", "../y")
    # 置き換えられない書き方は、手元の場所を残して写さずに、止まる
    with pytest.raises(ValueError):
        replace_clone_path("target: { repo: github.com/x/y, clone_path: /Users/me/y }\n", "../y")
    assert replace_clone_path("target:\n  repo: github.com/x/y\n  commit: abc\n", "../y") == "target:\n  repo: github.com/x/y\n  commit: abc\n", "clone_path を持たない結果は、変えない"


def _fake_repo(root: Path, results: list[str]) -> Path:
    an = root / "analysis"
    (an / "results").mkdir(parents=True)
    (an / "reviews").mkdir()
    for name in ("work-definition.yaml", "entry-list.yaml"):
        (an / name).write_text("target:\n  repo: github.com/x/y\n  clone_path: /Users/me/y\n", encoding="utf-8")
    for r in results:
        (an / "results" / f"{r}.yaml").write_text("target:\n  repo: github.com/x/y\n", encoding="utf-8")
        (an / "reviews" / f"{r}.yaml").write_text("findings: []\n", encoding="utf-8")
    return root


def test_import_checks_its_input_before_touching_the_example(tmp_path: Path):
    examples = tmp_path / "examples"
    first = _fake_repo(tmp_path / "first", ["a", "b"])
    assert import_atlas(first, "x-atlas", "y", examples=examples) == {"results": 2, "reviews": 2}
    assert "clone_path: ../y\n" in (examples / "x-atlas" / "analysis" / "work-definition.yaml").read_text(encoding="utf-8")
    assert "ABATLAS_TARGET=../y\n" in (examples / "x-atlas" / ".env").read_text(encoding="utf-8")
    kept = sorted(p.name for p in (examples / "x-atlas" / "analysis" / "results").iterdir())
    # 入力が足りないとき、見本の名前や clone の名前が置き場の外を指すときは、見本に触らずに止まる
    for src, name, clone in [(tmp_path / "missing", "x-atlas", "y"), (_fake_repo(tmp_path / "empty", []), "x-atlas", "y"),
                             (first, "../x-atlas", "y"), (first, str(tmp_path / "abs-atlas"), "y"), (first, "x", "y"), (first, "x-atlas", "../y")]:
        with pytest.raises(ValueError):
            import_atlas(src, name, clone, examples=examples)
        assert sorted(p.name for p in (examples / "x-atlas" / "analysis" / "results").iterdir()) == kept
    assert not (tmp_path / "abs-atlas").exists()
    # 手元の場所そのもの (分析リポジトリの場所、元の clone_path) が文の中に残っていれば、止まる。よくあるルートの名前でなくても
    for leak in (str(tmp_path / "leaky"), "/data/company/y"):
        leaky = _fake_repo(tmp_path / "leaky", ["a"])
        (leaky / "analysis" / "work-definition.yaml").write_text("target:\n  repo: github.com/x/y\n  clone_path: /data/company/y\n", encoding="utf-8")
        (leaky / "analysis" / "results" / "a.yaml").write_text(f"target:\n  repo: github.com/x/y\nnotes: 'see {leak}/src'\n", encoding="utf-8")
        with pytest.raises(ValueError, match="手元の場所"):
            import_atlas(leaky, "x-atlas", "y", examples=examples)
        shutil.rmtree(leaky)
    assert sorted(p.name for p in (examples / "x-atlas" / "analysis" / "results").iterdir()) == kept
    # 消えた入口の結果は、写し直すと消える
    second = _fake_repo(tmp_path / "second", ["a"])
    assert import_atlas(second, "x-atlas", "y", examples=examples) == {"results": 1, "reviews": 1}
