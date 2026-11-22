"""分析リポジトリの配置を作る・更新する (世代ギャップ)。

分析リポジトリに必要な依存は Docker だけ。このモジュールはコンテナの中で動き、マウントされた分析リポジトリに書く。

  OSS 所有 (upgrade で置き換える。手で直さない)
    compose.yaml                       docker compose の定義 (設定は .env)
    .abatlas/                          エージェントが読む参照物: schema / profiles / 見本 / 文書
    .agents/skills/abatlas-*           分析 skill (agent skills 規約)
    .agents/skills/mid-harness         同梱する中ハーネスの skill (生成スクリプトを含む)
    scripts/agent-hooks/pre-tool-policy.sh   中ハーネスの hook 本体 (mid-harness のテンプレート)
  中ハーネス (scaffold が初回だけ置く。以後は分析リポジトリのもの)
    AGENTS.md  CLAUDE.md  .agents/harness.yaml  .agents/agent-specs/  .agents/memory/  docs/
    .claude/ .codex/ .cursor/ .grok/ .github/ ...   製品別の生成物 (gen_adapters が所有。手で直さない)
  分析する側が所有 (保持)
    .env                               docker compose の設定 (対象リポジトリの場所など)
    analysis/work-definition.yaml  analysis/entry-list.yaml  analysis/results/  analysis/reviews/
    analysis/dbt/models/repo/          この分析リポジトリ独自の mart
  派生物 (git 管理外)
    analysis/data/                     DuckDB と dbt の作業ディレクトリ
"""

from __future__ import annotations

import os
import shutil
import subprocess  # nosec B404 - executes subprocesses with argument lists
import sys
import tempfile
from pathlib import Path

from . import ANALYSIS_DIR, DATA_DIR, OSS_DIR, REPO_ROOT
from .schemas import load_yaml

AGENTS_DIR = ".agents"


DEFAULT_TARGETS = "claude-code,codex,cursor,grok,copilot,antigravity"

# .abatlas/ に複製する参照物 (エージェントが読むもの。実行環境は含めない)
OSS_REFERENCE_ITEMS = [
    "schema",
    "profiles",
    "tests/fixtures",
    "docs/architecture",
    "README.md",
    "LICENSE",
]
OSS_SKILLS = [
    "abatlas-run-analysis",
    "abatlas-discover-entries",
    "abatlas-analyze-entry",
    "abatlas-review-entry",
    "abatlas-classify-data",
    "mid-harness",
]
HOOK_SCRIPT = "scripts/agent-hooks/pre-tool-policy.sh"
COMPOSE_FILE = "compose.yaml"
# 複製元 (イメージの中の /opt/abatlas、または開発中の checkout) に揃っていなければならないもの
OSS_REQUIRED = [
    "schema/analysis-result.schema.json",
    "dbt-template/dbt_project.yml",
    "abatlas/templates/compose.yaml",
    ".agents/skills/mid-harness/scripts/scaffold.py",
    ".agents/skills/mid-harness/scripts/gen_adapters.py",
    ".agents/skills/mid-harness/templates/tree/" + HOOK_SCRIPT,
    ".agents/skills/abatlas-analyze-entry/SKILL.md",
    ".agents/skills/abatlas-run-analysis/SKILL.md",
    "tests/fixtures/result-housekeeping.yaml",
]

_COPY_IGNORE = shutil.ignore_patterns(
    "__pycache__", "*.pyc", ".venv", ".pytest_cache", "target", "logs", "dbt-template"
)


def oss_root() -> Path:
    """いま動いているコードの配布物のルート (コンテナでは /opt/abatlas、開発中は git checkout)。"""
    return REPO_ROOT


def owned_paths() -> list[str]:
    """OSS が所有し、upgrade で置き換える分析リポジトリ内のパス (報告と .abatlas/OWNED.md に使う)。"""
    return [
        COMPOSE_FILE,
        OSS_DIR + "/",
        *(f".agents/skills/{s}/" for s in OSS_SKILLS),
        HOOK_SCRIPT,
    ]


def check_oss_layer(src: Path) -> None:
    """複製元が配布物として揃っているかを先に検査する (欠けていれば何も書かずに止まる)。"""
    missing = [rel for rel in OSS_REQUIRED if not (src / rel).exists()]
    if missing:
        raise SystemExit(f"配布物 {src} に必要なものが無い: " + ", ".join(missing))


def _copy(src: Path, dst: Path, ignore=_COPY_IGNORE) -> None:
    if src.is_dir():
        shutil.copytree(src, dst, ignore=ignore, symlinks=False)
    else:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def _remove(p: Path) -> None:
    if p.is_symlink() or p.is_file():
        p.unlink()
    elif p.is_dir():
        shutil.rmtree(p)


def _stage_reference(src: Path, stage: Path) -> None:
    """.abatlas/ (参照物) の新版を stage に作る。"""
    for item in OSS_REFERENCE_ITEMS:
        if (src / item).exists():
            _copy(src / item, stage / item)
    (stage / "OWNED.md").write_text(
        "# OSS が所有するパス\n\n`abatlas upgrade` が配布物の内容で置き換える。手で直さない (直すなら OSS 側へ)。\n\n"
        + "".join(f"- `{p}`\n" for p in owned_paths())
        + "\nそれ以外 (AGENTS.md、.agents/harness.yaml、.agents/memory/、.env、analysis/、製品別の生成物) は触らない。\n",
        encoding="utf-8",
    )


OLD_LAYOUT_ITEMS = [
    "work-definition.yaml",
    "entry-list.yaml",
    "results",
    "reviews",
    "dbt/models/repo",
]


def detect_old_layout(repo: Path) -> str | None:
    """段階 3 までの配置 (分析資産がルート直下) の残りがあれば、その移行手順を返す。部分的に移した状態も拾う。"""
    left = [rel for rel in OLD_LAYOUT_ITEMS if (repo / rel).exists()]
    if not left:
        return None
    return (
        "旧配置 (分析資産がルート直下) の残りを検出した: " + ", ".join(left) + "\n"
        f"  先に手で移す: mkdir -p {ANALYSIS_DIR}/dbt/models && git mv work-definition.yaml entry-list.yaml results reviews {ANALYSIS_DIR}/ "
        f"&& git mv dbt/models/repo {ANALYSIS_DIR}/dbt/models/repo && rm -rf .abatlas dbt && rm -f .agents/skills/*  (symlink)\n"
        "  その後、.env を書いて `abatlas upgrade .` をやり直す"
    )


def recover_interrupted_install(repo: Path) -> list[str]:
    """前回の install_owned が強制終了で止まっていたら (stage が残っている)、退避した旧版を欠けた場所へ戻す。戻したパスを返す。"""
    restored: list[str] = []
    owned = [
        OSS_DIR,
        *(f".agents/skills/{s}" for s in OSS_SKILLS),
        HOOK_SCRIPT,
        COMPOSE_FILE,
    ]
    for stage in sorted(repo.glob(".abatlas.stage.*")):
        for rel in owned:
            old, dst = stage / "old" / rel, repo / rel
            if (old.exists() or old.is_symlink()) and not (
                dst.exists() or dst.is_symlink()
            ):
                dst.parent.mkdir(parents=True, exist_ok=True)
                old.rename(dst)
                restored.append(rel)
        shutil.rmtree(stage, ignore_errors=True)
    return restored


def _swap_staged_files(repo, stage, plan):
    swapped: list[tuple[Path, Path | None]] = []  # (dst, 退避した旧版)
    try:
        for rel, new in plan:
            dst = repo / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            old = None
            if dst.exists() or dst.is_symlink():
                old = stage / "old" / rel
                old.parent.mkdir(parents=True, exist_ok=True)
                dst.rename(old)
            swapped.append((dst, old))
            new.rename(dst)
    except BaseException:
        for dst, old in reversed(swapped):  # 入れ替え済みを戻す
            _remove(dst)
            if old is not None and (old.exists() or old.is_symlink()):
                old.rename(dst)
        raise


def install_owned(repo: Path, src: Path | None = None) -> list[str]:
    """OSS 所有のパスをすべて配布物から置き換える。戻り値は置いたパス。

    手順: (1) 新版を全部 stage に作る (2) 旧版を退避してから新版を入れる (3) どこかで失敗したら退避した旧版を戻す。
    途中で止まっても、各パスは旧版か新版のどちらかが揃っている。
    """
    src = (src or oss_root()).resolve()
    check_oss_layer(src)
    repo = repo.resolve()
    repo.mkdir(parents=True, exist_ok=True)
    recover_interrupted_install(repo)
    plan: list[tuple[str, Path]] = []  # (分析リポジトリ内の相対パス, stage 内の新版)
    stage = Path(tempfile.mkdtemp(prefix=".abatlas.stage.", dir=repo))
    try:
        _stage_reference(src, stage / OSS_DIR)
        plan.append((OSS_DIR, stage / OSS_DIR))
        for sk in OSS_SKILLS:
            _copy(src / AGENTS_DIR / "skills" / sk, stage / AGENTS_DIR / "skills" / sk)
            plan.append((f".agents/skills/{sk}", stage / AGENTS_DIR / "skills" / sk))
        _copy(
            src
            / AGENTS_DIR
            / "skills"
            / "mid-harness"
            / "templates"
            / "tree"
            / HOOK_SCRIPT,
            stage / HOOK_SCRIPT,
        )
        (stage / HOOK_SCRIPT).chmod(0o755)
        plan.append((HOOK_SCRIPT, stage / HOOK_SCRIPT))
        _copy(src / "abatlas" / "templates" / COMPOSE_FILE, stage / COMPOSE_FILE)
        plan.append((COMPOSE_FILE, stage / COMPOSE_FILE))

        _swap_staged_files(repo, stage, plan)
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    return [rel + ("/" if (repo / rel).is_dir() else "") for rel, _ in plan]


def _profile_id(repo: Path) -> str:
    wd = repo / ANALYSIS_DIR / "work-definition.yaml"
    if not wd.exists():
        raise SystemExit(
            f"{wd} が無いのでプロファイルが分からない (--profile で指定する)"
        )
    return load_yaml(wd)["profile"]["id"]


# ---------------------------------------------------------------- 対象層の初期ファイル

AGENTS_MD = """# AGENTS.md (分析リポジトリ)

このリポジトリは as-built-atlas の**分析リポジトリ**です。対象システムの入口を 1 件ずつ分析し、結果 YAML を `analysis/results/` に置きます。
必要な依存は Docker だけです (ツールと dbt はコンテナイメージの中にあります)。

## 置き場の約束

| 場所 | 所有 | 扱い |
|---|---|---|
| `.abatlas/`、`compose.yaml`、`.agents/skills/*`、`scripts/agent-hooks/` | OSS | `abatlas upgrade` で置き換わる。**手で直さない** (一覧は `.abatlas/OWNED.md`) |
| `AGENTS.md`、`.agents/harness.yaml`、`.agents/agent-specs/`、`.agents/memory/`、`docs/` | 中ハーネス (このリポジトリ) | 育てる。製品別の生成物 (`.claude/` など) は手修正せず再生成 |
| `.env`、`analysis/` | このリポジトリ | 分析の資産。保持される |
| `analysis/data/` | 派生物 | git 管理外。`build` が作り直す |

skill 内の `<oss>` は `.abatlas/`、`<abatlas>` は `docker compose run --rm abatlas` に読み替える。

## 標準コマンド (リポジトリのルートで)

```bash
docker compose run --rm abatlas validate work analysis/work-definition.yaml
docker compose run --rm abatlas enumerate analysis/entry-list.yaml   # プロファイルは、作業定義の profile.dir から読む
docker compose run --rm abatlas build .            # ETL → dbt build (派生物は analysis/data/)
docker compose up -d api                            # webapp http://localhost:8765 、集計表 API (同 URL 配下) と MCP http://localhost:8765/mcp
docker compose pull && docker compose run --rm abatlas upgrade . && docker compose up -d --force-recreate api   # 配布物の更新 (OSS 所有だけ置き換わる。稼働中の api も新しいイメージで作り直す)
```

コーディングエージェントへの MCP 登録は URL `http://localhost:8765/mcp` (streamable HTTP)。例: `claude mcp add --transport http abatlas http://localhost:8765/mcp`

## 知識の読み分け

- 作業開始時に `.agents/memory/index.md` を読む。**このリポジトリ固有の分析の癖** (unknown の扱い、データの当てはめ) は `.agents/memory/desired-state/analysis-conventions.md` にあり、分析 skill はこれを読んで振る舞いを変える
- 対象リポジトリ (`analysis/work-definition.yaml` の `target.clone_path`。コンテナには `/ws/target` として読み取り専用で見える) のファイルは変更しない

## 中ハーネスの構成

portable core (`AGENTS.md` / `.agents/`) と生成した製品別 adapter (`.claude/` / `.codex/` など) に分かれています。adapter は手修正せず `.agents/harness.yaml` を直して再生成します (`docker compose run --rm abatlas upgrade .` でも再生成される)。
hook (`scripts/agent-hooks/pre-tool-policy.sh`) を各製品が実行するには、製品ごとに利用者側の trust 設定が要ります (`.agents/skills/mid-harness/references/adapters/`)。
"""

WORK_DEFINITION = """format_version: 1
target:
  repo: github.com/<org>/<repo>        # 対象リポジトリ (識別子)
  # name: <システムの名前>             # 画面の見出しに出す表示名 (任意。省略すると repo の最後の区切りより後ろ)
  clone_path: ../<repo>                # 対象の clone。相対なら分析リポジトリのルート (.env と同じ基準)。.env の ABATLAS_TARGET と同じ場所を書く。コンテナには /ws/target として見える
  scope: .                             # 分析範囲 (clone_path からの相対)
  commit: <40 桁の commit>             # 固定する対象コミット
profile:
  id: {profile_id}
  dir: .abatlas/profiles/{profile_id}   # build / validate / enumerate が読むプロファイル。layer などを自分用に直すなら analysis/profiles/{profile_id} に写して、ここを書き換える (.abatlas/ は upgrade で置き換わる)
# analysis:
#   models:                            # 分析とレビューを任せるサブエージェントのモデル (任意)。書かないと、起動した側と同じモデルで動く (入口が多いと、費用がかさむ)
#     analyze: <モデルの名前>
#     review: <モデルの名前>
#   tests: true                        # 処理の段を通るテストも分析する (範囲にテストのコードが入っているときだけ)
"""

DOTENV = """# docker compose の設定 (このリポジトリのもの。upgrade で触らない)
# 対象リポジトリの clone の場所 (analysis/work-definition.yaml の target.clone_path と同じ場所。compose.yaml からの相対か絶対パス)
ABATLAS_TARGET=../<repo>
# 配布物のイメージ。既定は ghcr.io/suwa-sh/as-built-atlas:latest
#ABATLAS_IMAGE=ghcr.io/suwa-sh/as-built-atlas:latest
# API / MCP を出すホスト側のポート。既定は 8765 (127.0.0.1 にだけ bind する)
#ABATLAS_PORT=8765
# ループバック以外の名前で API / MCP を使うときだけ (カンマ区切り)。ABATLAS_BIND で bind 先も変える
#ABATLAS_ALLOWED_HOSTS=
#ABATLAS_BIND=127.0.0.1
"""

ANALYSIS_CONVENTIONS = """---
okf_version: "0.2"
kind: desired-state
title: この分析リポジトリでの分析の癖
---

# この分析リポジトリでの分析の癖

分析 skill (`abatlas-analyze-entry`) と レビュー skill (`abatlas-review-entry`) は、作業の最初にこのファイルを読み、
プロファイルの `context.md` より**こちらを優先**します。OSS 層の skill は変えずに、リポジトリごとの振る舞いをここで変えます。

## 層とフォルダの対応

<!-- プロファイルが、層を役割で分けているとき (cli、api)。例: `internal/core` は logic、`queries` と `internal/store` は adapter -->

## 名前と値の綴り、木の書き方

<!-- 入口をまたいでそろえる書き方。例: 権限の確認の value は、確認する関数の名前だけを書く。全操作に共通の認証の経路は、読み書きを持つ最初の段まで -->

## unknown の扱い

<!-- 例: 環境変数で決まる接続先は `generated_at_runtime` とし、`note` に変数名を書く -->

## データの当てはめ

<!-- 例: `ops_logs` DB は host を `localhost` に固定して書く -->

## このリポジトリで見なくてよいもの

<!-- 例: vendor/ 配下は `binary_or_vendored` で閉じる -->
"""

GITIGNORE = f"""# 派生物 (build が作り直す)
{DATA_DIR}/
*.duckdb
__pycache__/
"""

REPO_MODELS_README = """# analysis/dbt/models/repo

この分析リポジトリ独自の mart を置く (保持される。upgrade で上書きされない)。
build のたびに、イメージの中の core / profile のテンプレートと合成して dbt を動かす (作業ディレクトリは `analysis/data/dbt/`)。
宣言は core と同じく `schema.yml` の `meta.abatlas` に書く (origin: repo)。`{{ ref('stg_entries') }}` など staging を参照できる。
"""


def _mid_harness_scripts(repo: Path) -> Path:
    return repo / AGENTS_DIR / "skills" / "mid-harness" / "scripts"


def _python() -> str:
    if Path(sys.executable).exists():
        return sys.executable
    found = shutil.which("python3") or shutil.which("python")
    if not found:
        raise SystemExit("python3 が見つからない")
    return found


def _run(cmd: list[str], cwd: Path) -> None:
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    r = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, env=env)  # nosec B603 - local adapter generator and Git CLI
    if r.returncode != 0:
        raise SystemExit(
            f"{' '.join(cmd)} が失敗 (exit {r.returncode}):\n{r.stdout}\n{r.stderr}"
        )


def _gen_adapters(repo: Path) -> None:
    _run(
        [
            _python(),
            str(_mid_harness_scripts(repo) / "gen_adapters.py"),
            str(repo),
            "--quiet",
        ],
        cwd=repo,
    )


def init_repo(
    repo: Path, profile_id: str, targets: str = DEFAULT_TARGETS, src: Path | None = None
) -> list[str]:
    """分析リポジトリを初期化する。OSS 所有は置き、対象層は無いものだけ作る。戻り値は作ったものの一覧。"""
    repo = repo.resolve()
    src = (src or oss_root()).resolve()
    check_oss_layer(src)
    if not (src / "profiles" / profile_id / "profile.yaml").exists():
        raise SystemExit(
            f"プロファイル {profile_id} が配布物に無い ({src / 'profiles'})"
        )
    repo.mkdir(parents=True, exist_ok=True)
    old = detect_old_layout(repo)
    if old:
        raise SystemExit(old)
    made: list[str] = []
    if not (repo / ".git").exists():
        _run(
            ["git", "init", "-q"], cwd=repo
        )  # 分析リポジトリは git 管理が前提 (mid-harness も要求する)
        made.append(".git (git init)")
    made += install_owned(repo, src)

    def put(rel: str, text: str) -> None:
        p = repo / rel
        if p.exists():
            return
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        made.append(rel)

    put(
        f"{ANALYSIS_DIR}/work-definition.yaml",
        WORK_DEFINITION.format(profile_id=profile_id),
    )
    put(".env", DOTENV)
    put("AGENTS.md", AGENTS_MD.format(profile_id=profile_id))
    put("CLAUDE.md", "@AGENTS.md\n")
    put(".gitignore", GITIGNORE)
    for d in ("results", "reviews"):
        put(f"{ANALYSIS_DIR}/{d}/.gitkeep", "")
    put(f"{ANALYSIS_DIR}/dbt/models/repo/README.md", REPO_MODELS_README)

    # mid-harness: core の骨格 → memory → adapter 生成 (skill は OSS 所有の実ディレクトリとして置いてある)
    mh = _mid_harness_scripts(repo)
    if not (repo / AGENTS_DIR / "harness.yaml").exists():
        _run(
            [
                _python(),
                str(mh / "scaffold.py"),
                str(repo),
                "--targets",
                targets,
                "--skills-mode",
                "symlink",
            ],
            cwd=repo,
        )
        made.append(f".agents/ (mid-harness scaffold, targets: {targets})")
    put(".agents/memory/desired-state/analysis-conventions.md", ANALYSIS_CONVENTIONS)
    idx = repo / AGENTS_DIR / "memory" / "index.md"
    if idx.exists() and "analysis-conventions.md" not in idx.read_text(
        encoding="utf-8"
    ):
        with idx.open("a", encoding="utf-8") as fh:
            fh.write(
                "\n## as-built-atlas\n- 入口を分析・レビューする前に: [この分析リポジトリでの分析の癖](desired-state/analysis-conventions.md)\n"
            )
        made.append(".agents/memory/index.md (追記)")
    _gen_adapters(repo)
    made.append("製品別 adapter (gen_adapters)")
    return made


def upgrade_repo(repo: Path, src: Path | None = None) -> list[str]:
    """OSS 所有のパスだけ置き換えて製品別 adapter を再生成する。対象層と中ハーネスの正本は触らない。"""
    repo = repo.resolve()
    if not (repo / AGENTS_DIR / "harness.yaml").exists():
        raise SystemExit(
            f"{repo} は初期化されていない (.agents/harness.yaml が無い)。先に `abatlas init` を実行する"
        )
    old = detect_old_layout(repo)
    if old:
        raise SystemExit(old)
    placed = install_owned(repo, src)
    _gen_adapters(repo)
    return placed
