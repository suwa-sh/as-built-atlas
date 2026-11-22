"""文書の検査: リンク切れ、配布先で切れるリンク、mermaid の危ない書き方、mermaid を実際に描く (mmdc があれば)。

使い方: uv run --locked python .agents/skills/dev-docs/scripts/check_docs.py [--no-render]
終了コード: 問題があれば 1。
tests/test_docs.py が、描くところを除いて (--no-render)、同じ検査を呼ぶ。
"""

import re
import shutil
import subprocess  # nosec B404 - executes subprocesses with argument lists
import sys
import tempfile
from pathlib import Path
from urllib.parse import unquote, urlsplit

from markdown_it import MarkdownIt

MARKDOWN = MarkdownIt("commonmark").enable("table")
# 引用符で包まずに、箱の文字へ かっこ・波かっこ を入れている ([(…)] = 円柱 は除く)
RISKY_BOX = re.compile(r"\[(?!\()[^\]\"]*[(){}][^\]\"]*\]")
RISKY_SLASH = re.compile(r"\[/|/\]")


def files_of(root: Path) -> list[Path]:
    return sorted(root.glob("*.md")) + sorted((root / "docs").rglob("*.md"))


def local_links(children):
    for child in children:
        if child.type not in {"link_open", "image"}:
            continue
        url = urlsplit(str(child.attrs["src" if child.type == "image" else "href"]))
        if not url.scheme and not url.netloc and url.path:
            yield unquote(url.path)


def link_problems(root, md, children):
    shipped = root / "docs" / "architecture"
    rel = md.relative_to(root)
    for target in local_links(children):
        base = root if target.startswith("/") else md.parent
        dest = (base / target.lstrip("/")).resolve()
        if not dest.exists():
            yield f"{rel}: リンク切れ: {target}"
        elif md.is_relative_to(shipped) and not dest.is_relative_to(shipped):
            yield f"{rel}: 配布先で切れるリンク (docs/architecture/ の外): {target}。リンクにせず、文で指す"


def diagram_problems(rel, content):
    for line in content.splitlines():
        if RISKY_SLASH.search(line) and '"' not in line:
            yield f"{rel}: mermaid: スラッシュで始まる・終わる箱の文字は、引用符で包む: {line.strip()}"
        if RISKY_BOX.search(line):
            yield f"{rel}: mermaid: かっこを含む箱の文字は、引用符で包む: {line.strip()}"


def render_diagrams(root, diagrams, renderer, problems):
    total = 0
    with tempfile.TemporaryDirectory() as tmp:
        for index, (md, expected) in enumerate(diagrams.items()):
            out = Path(tmp) / f"diagram-{index}.md"
            result = subprocess.run(  # nosec B603 - local renderer with separate path arguments
                [renderer, "-q", "-i", str(md), "-o", str(out), "-e", "png"],
                capture_output=True,
                text=True,
            )
            made = len(list(Path(tmp).glob(f"{out.stem}-*.png")))
            total += made
            if result.returncode != 0 or made != expected:
                problems.append(
                    f"{md.relative_to(root)}: mermaid を描けない ({made} / {expected} 枚): {(result.stderr or result.stdout).strip()[-300:]}"
                )
    return f"mermaid を {total} 枚描いた"


def check(root: Path, render: bool = False) -> tuple[list[str], list[str]]:
    """(問題, 注記) を返す。root はリポジトリのルート。"""
    root = root.resolve()
    problems = []
    diagrams = {}
    for md in files_of(root):
        for token in MARKDOWN.parse(md.read_text(encoding="utf-8")):
            problems.extend(link_problems(root, md, token.children or ()))
            if token.type == "fence" and token.info.strip() == "mermaid":
                diagrams[md] = diagrams.get(md, 0) + 1
                problems.extend(diagram_problems(md.relative_to(root), token.content))
    if not render:
        note = "mermaid は描いていない (--no-render)"
    elif renderer := shutil.which("mmdc"):
        note = render_diagrams(root, diagrams, renderer, problems)
    else:
        note = "mermaid は描いていない (mmdc が無い)。描いていないと報告する"
    return problems, [note]


if __name__ == "__main__":
    found, said = check(
        Path(__file__).resolve().parents[4], render="--no-render" not in sys.argv
    )
    for line in said:
        print(line)
    if found:
        print("\n".join(found))
        sys.exit(1)
    print("ok")
