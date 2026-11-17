"""as-built-atlas core tools (配布物の本体。コンテナイメージの中で動く)。

- schemas: schema/ 配下の JSON Schema を読み、参照 ($ref) を解決する
- validate: 分析結果 YAML / 入口一覧 / プロファイル / 作業定義の機械チェック
- enumerate: 入口一覧の extractors を実行し、候補を entries に書く
- extractors: コア同梱の汎用抽出器 (structured-query: 定義ファイルを JMESPath で読む / nested-keys: 定義ファイルの入れ子のキーの組から入口を作る / glob: ファイルの置き場から入口を作る)
- layout: 分析リポジトリの初期化と更新 (OSS 所有ファイルの配置、中ハーネスの生成)
- build: ETL → dbt build (派生物は分析リポジトリの analysis/data/)
- api / mcp_server: 集計表 API と、その上の MCP。webapp/ (静的ファイル) も api が配信する
- declarations: mart 宣言 (meta.abatlas) の検査 (build が呼ぶ)
"""

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_DIR = REPO_ROOT / "schema"
VOCAB_DIR = SCHEMA_DIR / "vocab"

# 分析リポジトリの中の置き場。ルート直下は中ハーネス (AGENTS.md / .agents/ / 製品別の生成物) が使うので、
# 分析の資産は analysis/ の下にまとめる
OSS_DIR = ".abatlas"            # OSS が所有する参照物 (schema / profiles / 見本 / 文書)。upgrade で置き換える
ANALYSIS_DIR = "analysis"       # 分析する側が所有する資産 (work-definition / entry-list / results / reviews / dbt/models/repo)
DATA_DIR = "analysis/data"      # 派生物 (DuckDB、dbt の作業ディレクトリ)。git 管理外。消して作り直せる


def analysis_dir(repo: Path) -> Path:
    return repo / ANALYSIS_DIR


def data_dir(repo: Path) -> Path:
    return repo / DATA_DIR


def dbt_workdir(repo: Path) -> Path:
    """build が core / profile テンプレートと analysis/dbt/models/repo を合成して dbt を動かす場所 (派生物)。"""
    return data_dir(repo) / "dbt"


def duckdb_path(repo: Path) -> Path:
    env = os.environ.get("ABATLAS_DUCKDB")
    return Path(env) if env else data_dir(repo) / "abatlas.duckdb"



def result_file_name(entry_id: str) -> str:
    """入口 id → results/ と reviews/ のファイル名。`/` は `__` に置き換える (skill と ETL と検査が同じ規則を使う)。"""
    return entry_id.replace("/", "__") + ".yaml"


def file_name_collisions(entry_ids) -> dict[str, list[str]]:
    """同じファイル名になる入口 id の組 (例: `a/b` と `a__b`、`Daily` と `daily`)。入口一覧の検査で拒む。

    大小文字を同一視するファイルシステム (macOS / Windows の既定) でも 1 入口 = 1 ファイルが崩れないよう、
    比較は casefold したファイル名で行う。
    """
    by_name: dict[str, list[str]] = {}
    for eid in entry_ids:
        by_name.setdefault(result_file_name(eid).casefold(), []).append(eid)
    return {result_file_name(ids[0]): sorted(ids) for ids in by_name.values() if len(ids) > 1}
