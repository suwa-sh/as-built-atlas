"""ETL → dbt build。派生物はすべて分析リポジトリの analysis/data/ に置く (git 管理外、作り直せる)。

dbt のプロジェクトは build のたびに合成する:
  配布物の dbt-template/ (core)  +  プロファイルの dbt-template/ (profile)  +  analysis/dbt/models/repo/ (この分析リポジトリ独自)
プロファイルは作業定義の profile.dir (分析リポジトリの中。検査や列挙に渡すのと同じファイル) から読む。未記入なら配布物の profiles/<id>。
プロファイルの dbt-template は、そのディレクトリにあればそれ、無ければ配布物の profiles/<id>/dbt-template。
  → analysis/data/dbt/ (作業ディレクトリ)
分析リポジトリには core / profile の dbt モデルを置かないので、世代ギャップの管理対象は analysis/dbt/models/repo/ だけ。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import ANALYSIS_DIR, OSS_DIR, REPO_ROOT, analysis_dir, dbt_workdir, duckdb_path
from .declarations import check_manifest, declared_models, publish_declarations, publish_meta
from .etl import run_etl
from .schemas import load_yaml, resource_kinds, profile_term_problems

# 合成のたびに作業ディレクトリから作り直すもの (target/ と logs/ は残す。manifest は API が読む)
RENDERED = ["dbt_project.yml", "profiles.yml", "macros", "models", "seeds"]
_IGNORE = shutil.ignore_patterns("__pycache__", "README.md")


def _profile_id(repo: Path) -> str:
    wd = analysis_dir(repo) / "work-definition.yaml"
    if not wd.exists():
        raise SystemExit(f"{wd} が無いのでプロファイルが分からない")
    return load_yaml(wd)["profile"]["id"]


def profile_dir(repo: Path, src: Path | None = None) -> Path:
    """プロファイルのディレクトリ。作業定義の profile.dir (分析リポジトリのルートからの相対) があればそこ、無ければ配布物の profiles/<id>。

    検査 (validate) と列挙 (enumerate) に渡すファイルと、集計が読むファイルを同じにする。書いてある場所に無ければ、配布物へ黙って切り替えずに止める。
    """
    repo = repo.resolve()
    pid = _profile_id(repo)
    prof = load_yaml(analysis_dir(repo) / "work-definition.yaml")["profile"]
    rel = prof.get("dir")
    if "dir" in prof and not (isinstance(rel, str) and rel.strip()):
        raise SystemExit("work-definition.yaml の profile.dir が空。場所を書くか、項目ごと消す (消すと配布物のプロファイルを使う)")
    if rel is None:
        base = (src or REPO_ROOT).resolve() / "profiles" / pid
        if not (base / "profile.yaml").exists():
            raise SystemExit(f"プロファイル {pid} が配布物に無い ({base.parent})。work-definition.yaml の profile.id か配布物の版を確かめる")
        return base
    base = (repo / rel).resolve()
    if not base.is_relative_to(repo):
        raise SystemExit(f"work-definition.yaml の profile.dir '{rel}' が分析リポジトリの外を指している")
    if (base / "profile.yaml").exists() and not (base / "profile.yaml").resolve().is_relative_to(repo):
        raise SystemExit(f"work-definition.yaml の profile.dir '{rel}' の profile.yaml が、分析リポジトリの外を指すリンクになっている")
    if not (base / "profile.yaml").exists():
        raise SystemExit(f"work-definition.yaml の profile.dir '{rel}' に profile.yaml が無い。`abatlas upgrade .` で配布物のコピーを置き直すか、profile.dir を直す (消すと配布物の profiles/{pid} を使う)")
    return base


def _profile(repo: Path) -> dict:
    """ツールが読むプロファイル (profile_dir の profile.yaml)。id が作業定義と合い、検査に通るものだけ使う。"""
    from .validate import validate_profile

    path = profile_dir(repo) / "profile.yaml"
    profile = load_yaml(path)
    pid = _profile_id(repo)
    if not isinstance(profile, dict) or profile.get("id") != pid:
        raise SystemExit(f"{path}: id が work-definition.yaml の profile.id '{pid}' と違う")
    findings = validate_profile(profile)
    if findings:
        raise SystemExit(f"{path}: プロファイルが検査に通らない:\n" + "\n".join(f"  {f}" for f in findings))
    return profile


def oss_copy_outdated(repo: Path) -> str | None:
    """読んだプロファイルが配布物のコピー (.abatlas/profiles/<id>) で、中身が配布物と違うとき、その旨の文を返す (違わなければ None)。

    イメージだけ新しくして upgrade を忘れると、集計は古いコピーで動く。止めはしない (自分用に写したプロファイルは対象外)。
    """
    repo = repo.resolve()
    base = profile_dir(repo)
    if not base.is_relative_to(repo / OSS_DIR):
        return None
    bundled = REPO_ROOT / "profiles" / _profile_id(repo) / "profile.yaml"
    if not bundled.exists() or bundled.read_bytes() == (base / "profile.yaml").read_bytes():
        return None
    return (f"分析リポジトリの中のプロファイルのコピー ({base.relative_to(repo)}/profile.yaml) が、配布物と違う。"
            "配布物を更新した後なら `abatlas upgrade .` でコピーを置き換える (集計は、このコピーで進めた)")


def _overlay(src: Path, dst: Path) -> None:
    if not src.exists():
        return
    if src.is_dir():
        shutil.copytree(src, dst, ignore=_IGNORE, dirs_exist_ok=True)
    else:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def render_dbt_project(repo: Path, profile_id: str | None = None, src: Path | None = None) -> Path:
    """core + profile のテンプレートと analysis/dbt/models/repo を analysis/data/dbt/ に合成する。戻り値は作業ディレクトリ。"""
    repo = repo.resolve()
    src = (src or REPO_ROOT).resolve()
    core = src / "dbt-template"
    if not (core / "dbt_project.yml").exists():
        raise SystemExit(f"配布物に dbt-template が無い ({core})")
    if profile_id:  # 明示したとき (配布物のプロファイルをそのまま使う)
        if not (src / "profiles" / profile_id / "profile.yaml").exists():
            raise SystemExit(f"プロファイル {profile_id} が配布物に無い ({src / 'profiles'})。work-definition.yaml の profile.id か配布物の版を確かめる")
        prof = src / "profiles" / profile_id / "dbt-template"
    else:
        profile_id = _profile_id(repo)
        prof = profile_dir(repo, src) / "dbt-template"
        if not prof.exists():  # 分析リポジトリのコピーは dbt-template を持たない。配布物のものを使う
            prof = src / "profiles" / profile_id / "dbt-template"  # 無くてもよい (mart を足さないプロファイル)
    work = dbt_workdir(repo)
    work.mkdir(parents=True, exist_ok=True)
    for rel in RENDERED:
        p = work / rel
        if p.is_dir():
            shutil.rmtree(p)
        elif p.exists():
            p.unlink()
    for rel in ("dbt_project.yml", "profiles.yml", "macros", "models"):
        _overlay(core / rel, work / rel)
        _overlay(prof / rel, work / rel)  # 同名は profile が勝つ
    for rel in ("models/core", "models/profile", "models/staging", "models/repo", "macros", "seeds"):
        (work / rel).mkdir(parents=True, exist_ok=True)  # 空でも置く (dbt が paths を読めるように)
    _overlay(repo / ANALYSIS_DIR / "dbt" / "models" / "repo", work / "models" / "repo")
    (work / "README.md").write_text(
        "# 派生物 (abatlas build が毎回作り直す)\n\n"
        "core / profile のテンプレートは配布物 (コンテナイメージ) の中、独自の mart は `analysis/dbt/models/repo/`。ここを手で直しても次の build で消える。\n",
        encoding="utf-8")
    return work


def build_repo(repo: Path, select: str | None = None) -> dict:
    """ETL (analysis/results → seeds) → dbt build → analysis/data/abatlas.duckdb。"""
    repo = repo.resolve()
    work = render_dbt_project(repo)
    profile = _profile(repo)
    outdated = oss_copy_outdated(repo)
    if outdated:
        print(f"warning: {outdated}", file=sys.stderr)
    counts = run_etl(analysis_dir(repo), work / "seeds", profile)  # 入口を包む入口 (within) が、プロファイルの宣言と合っているかも見る
    db = duckdb_path(repo)
    db.parent.mkdir(parents=True, exist_ok=True)
    # dbt は別プロセスで動かす (同一プロセスだと dbt-duckdb が接続を握り続け、API の read_only 接続と設定が衝突する)。
    # API が読んでいる最中でも壊れないように、別ファイルに作ってから入れ替える
    building = db.with_name(db.name + ".building")
    if building.exists():
        building.unlink()
    for leftover in db.parent.glob(db.name + ".building.wal"):
        leftover.unlink()
    dbt_bin = Path(sys.executable).parent / "dbt"
    cmd = [str(dbt_bin)] if dbt_bin.exists() else [sys.executable, "-m", "dbt.cli.main"]
    cmd += ["build", "--project-dir", str(work), "--profiles-dir", str(work), "--quiet"]
    if select:
        cmd += ["--select", select]
    if select and db.exists():
        shutil.copy2(db, building)  # 部分 build は既存の表を引き継ぐ (宣言検査は全 mart を見る)
    env = {**os.environ, "ABATLAS_DUCKDB": str(building)}
    r = subprocess.run(cmd, cwd=work, text=True, capture_output=True, env=env)
    if r.returncode != 0:
        building.unlink(missing_ok=True)
        raise SystemExit(f"dbt build が失敗 (exit {r.returncode}):\n{r.stdout[-3000:]}\n{r.stderr[-2000:]}")
    # mart 宣言 (meta.abatlas) が形式に合い、keys の列が実在するか。部分 build (--select) でも全宣言を見る (選ばなかった表は引き継いだ DB にある)。
    # 合わなければ DuckDB も manifest も入れ替えない (webapp / MCP が読めない宣言を出さない)
    manifest_src = work / "target" / "manifest.json"
    problems = check_manifest(manifest_src, building) + profile_term_problems(profile)  # プロファイルの表示項目の用語も、配る前に見る
    if problems:
        building.unlink(missing_ok=True)
        raise SystemExit("mart 宣言かプロファイルの表示項目が形式に合わない:\n  " + "\n  ".join(problems))
    # 検査に通った宣言を DuckDB の中に書いてから、ファイルを 1 回で入れ替える (API は宣言も表も同じファイルから読むので新旧が混ざらない。
    # dbt の作業先の manifest は失敗した build でも書き換わるので、API は読まない)
    import duckdb

    with duckdb.connect(str(building)) as con:
        publish_declarations(con, declared_models(json.loads(manifest_src.read_text(encoding="utf-8"))))
        target = load_yaml(analysis_dir(repo) / "work-definition.yaml").get("target")
        publish_meta(con, profile, resource_kinds(), target)  # 階層の概念名と操作の語彙、分析対象の名前 (webapp のナビ・見出し・凡例)
    os.replace(building, db)
    run_results = json.loads((work / "target" / "run_results.json").read_text(encoding="utf-8")).get("results", [])
    ok = sum(1 for x in run_results if x.get("status") in ("success", "pass"))
    return {**counts, "dbt_nodes": len(run_results), "dbt_ok": ok, "duckdb": str(db)}
