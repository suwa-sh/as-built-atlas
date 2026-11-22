"""手元の分析リポジトリの資産を、見本 (examples/<名前>/) へ写す。

使い方:
    uv run python examples/generator/import_atlas.py <分析リポジトリ> <見本の名前> --clone-dir <対象の clone のディレクトリ名>

写すのは、分析リポジトリの資産だけ (作業定義、入口の一覧、分析結果、レビュー、リポジトリ独自の集計の置き場の説明)。
対象のコード、派生物 (analysis/data/)、OSS 所有のファイル (.abatlas/ など) は写さない。
手元の場所が残らないように、いちばん上の `target` の `clone_path` を `../<対象の clone のディレクトリ名>` に置き換える (ほかの値は変えない)。
置き換えた後に、手元の場所そのもの (ホーム、分析リポジトリの場所、元の `clone_path`) が文の中に残っていれば、見本に触らずに止まる。
見本の README.md は、このスクリプトでは書かない (人が読む説明なので、見本ごとに書く)。

写す前に、人が確かめること: 作業定義の `target.commit` が、対象の公開のリポジトリにあること (手元にだけあるコミットを分析した結果は、見本にしない)。
"""

from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path

import yaml

YAML_GLOB = "*.yaml"


EXAMPLES = Path(__file__).resolve().parents[1]
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*-atlas")
_CLONE_DIR = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_CLONE_PATH = re.compile(r"([ \t]+clone_path:[ \t]*).*")
_GITIGNORE = "# 派生物 (build が作り直す)\nanalysis/data/\n*.duckdb\n__pycache__/\n"


def _env(clone: str) -> str:
    return (
        "# docker compose の設定 (このリポジトリのもの。upgrade で触らない)\n"
        f"# 対象の clone の場所。隣に clone する前提\nABATLAS_TARGET={clone}\n"
        "# 配布物のイメージ。既定は ghcr.io/suwa-sh/as-built-atlas:latest (公開前はローカルで同じタグを build する)\n"
        "#ABATLAS_IMAGE=ghcr.io/suwa-sh/as-built-atlas:latest\n#ABATLAS_PORT=8765\n"
    )


def _target_clone(text: str) -> str | None:
    target = (yaml.safe_load(text) or {}).get("target")
    return target.get("clone_path") if isinstance(target, dict) else None


def replace_clone_path(text: str, clone: str) -> str:
    """いちばん上の `target` の `clone_path` だけを置き換える。文の中の同じ綴りや、ほかの項目は変えない。"""
    lines, inside = text.split("\n"), False
    for i, line in enumerate(lines):
        if not inside:
            inside = line.rstrip() == "target:"
            continue
        if (
            line.strip() and not line[0].isspace()
        ):  # 字下げの無い行で、target のブロックが終わる (空行は、ブロックの中)
            break
        m = _CLONE_PATH.fullmatch(line)
        if m:
            lines[i] = m.group(1) + clone
            break
    out = "\n".join(lines)
    # 置き換えられない書き方 (1 行に並べた target など) で、手元の場所が残ったまま写さない
    left = _target_clone(out)
    if left is not None and left != clone:
        raise ValueError(
            f"target.clone_path を置き換えられなかった (target を、項目ごとに 1 行ずつ書く): {left!r}"
        )
    return out


def _read_assets(source: Path, paths: list[Path], clone: str):
    texts = {}
    old_clones = set()
    for path in paths:
        text = path.read_text(encoding="utf-8")
        original = _target_clone(text)
        if isinstance(original, str):
            old_clones.add(original.rstrip("/"))
        texts[path.relative_to(source)] = replace_clone_path(text, clone)
    return texts, old_clones - {"", ".", "..", clone}


def check_local_paths(src: Path, old_clones: set[str], texts: dict[Path, str]):
    # 公開用の ../app-public と、別の手元の ../app を取り違えないよう、パスの境目で照合する。
    known = old_clones | {
        str(Path.home()),
        str(src.resolve()),
        str(src.resolve().parent),
    }
    names = sorted(known - {"/"}, key=len, reverse=True)
    local = re.compile(
        r"(?<![\w./~-])(?:file://)?(?:~/|(?:"
        + "|".join(map(re.escape, names))
        + r")(?![\w-]|\.[\w.-]))",
        re.ASCII,
    )
    for rel, text in texts.items():
        if match := local.search(text):
            raise ValueError(
                f"手元の場所が、文の中に残っている (分析リポジトリの側で直してから写す): {rel}: {match[0]}"
            )


def import_atlas(
    src: Path, name: str, clone_dir: str, examples: Path = EXAMPLES
) -> dict[str, int]:
    if not _NAME.fullmatch(name):
        raise ValueError(
            f"見本の名前は、examples/ の直下のディレクトリ名 (…-atlas) にする: {name!r}"
        )
    if not _CLONE_DIR.fullmatch(clone_dir):
        raise ValueError(
            f"対象の clone の名前は、ディレクトリ名 1 つにする: {clone_dir!r}"
        )
    src_an, dst, clone = src / "analysis", examples / name, f"../{clone_dir}"
    required = [src_an / "work-definition.yaml", src_an / "entry-list.yaml"]
    results, reviews = (
        sorted((src_an / "results").glob(YAML_GLOB)),
        sorted((src_an / "reviews").glob(YAML_GLOB)),
    )
    missing = [str(p) for p in required if not p.is_file()]
    if missing or not results:
        raise ValueError(
            f"分析リポジトリの資産が足りない (作業定義、入口の一覧、1 件以上の分析結果が要る): {missing or src_an / 'results'}"
        )
    readme = src_an / "dbt" / "models" / "repo" / "README.md"
    # 先に全部を読んで、置き換えまで済ませる (読めないファイルがあれば、見本に触る前に止まる)
    texts, old_clones = _read_assets(src_an, [*required, *results, *reviews], clone)
    if readme.is_file():  # 説明の文は、そのまま写す (YAML ではない)
        texts[readme.relative_to(src_an)] = readme.read_text(encoding="utf-8")
    check_local_paths(src, old_clones, texts)
    dst_an = dst / "analysis"
    for sub in (
        "results",
        "reviews",
    ):  # 消えた入口の結果を残さないように、置き場ごと作り直す
        shutil.rmtree(dst_an / sub, ignore_errors=True)
        (dst_an / sub).mkdir(parents=True)
    if not readme.is_file():  # 元に無くなった説明を、残さない
        (dst_an / readme.relative_to(src_an)).unlink(missing_ok=True)
    for rel, text in texts.items():
        out = dst_an / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
    (dst / ".env").write_text(_env(clone), encoding="utf-8")
    (dst / ".gitignore").write_text(_GITIGNORE, encoding="utf-8")
    return {
        sub: len(list((dst_an / sub).glob(YAML_GLOB))) for sub in ("results", "reviews")
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "source", type=Path, help="手元の分析リポジトリ (analysis/ を持つディレクトリ)"
    )
    ap.add_argument(
        "name", help="見本の名前 (examples/ の直下のディレクトリ名。例: chat-ui-atlas)"
    )
    ap.add_argument(
        "--clone-dir",
        required=True,
        help="対象の clone のディレクトリ名 (見本の隣に clone する名前。例: chat-ui)",
    )
    a = ap.parse_args()
    try:
        print(f"{a.name}: {import_atlas(a.source.resolve(), a.name, a.clone_dir)}")
    except ValueError as e:
        raise SystemExit(f"error: {e}") from e


if __name__ == "__main__":
    main()
