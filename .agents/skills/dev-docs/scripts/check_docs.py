"""文書の検査: リンク切れ、配布先で切れるリンク、mermaid の危ない書き方、mermaid を実際に描く (mmdc があれば)。

使い方: python3 .agents/skills/dev-docs/scripts/check_docs.py [--no-render]
終了コード: 問題があれば 1。
tests/test_docs.py が、描くところを除いて (--no-render)、同じ検査を呼ぶ。
"""
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

LINK = re.compile(r"\]\(([^)\s#]+)(#[^)]*)?\)")
MERMAID = re.compile(r"```mermaid\n(.*?)```", re.S)
# 引用符で包まずに、箱の文字へ かっこ・波かっこ を入れている ([(…)] = 円柱 は除く)
RISKY_BOX = re.compile(r"\[(?!\()[^\]\"]*[(){}][^\]\"]*\]")
RISKY_SLASH = re.compile(r"\[/|/\]")


def files_of(root: Path) -> list[Path]:
    top = [root / n for n in ("README.md", "AGENTS.md", "DESIGN.md", "PRODUCT.md")]
    return [p for p in [*top, *sorted((root / "docs").rglob("*.md"))] if p.exists()]


def check(root: Path, render: bool = False) -> tuple[list[str], list[str]]:
    """(問題, 注記) を返す。root はリポジトリのルート。"""
    root = root.resolve()
    shipped = root / "docs" / "architecture"  # 分析リポジトリには、この中だけが配られる
    problems: list[str] = []
    notes: list[str] = []
    files = files_of(root)
    for md in files:
        text = md.read_text(encoding="utf-8")
        rel = md.relative_to(root)
        for m in LINK.finditer(text):
            target = m.group(1)
            if target.startswith(("http://", "https://", "mailto:", "<")):
                continue
            dest = (md.parent / target).resolve()
            if not dest.exists():
                problems.append(f"{rel}: リンク切れ: {target}")
            elif shipped in md.parents and shipped not in dest.parents and dest != shipped:
                problems.append(f"{rel}: 配布先で切れるリンク (docs/architecture/ の外): {target}。リンクにせず、文で指す")
        for block in MERMAID.findall(text):
            for line in block.splitlines():
                if RISKY_SLASH.search(line) and '"' not in line:
                    problems.append(f"{rel}: mermaid: スラッシュで始まる・終わる箱の文字は、引用符で包む: {line.strip()}")
                if RISKY_BOX.search(line):
                    problems.append(f"{rel}: mermaid: かっこを含む箱の文字は、引用符で包む: {line.strip()}")
    if not render:
        notes.append("mermaid は描いていない (--no-render)")
    elif not shutil.which("mmdc"):
        notes.append("mermaid は描いていない (mmdc が無い)。描いていないと報告する")
    else:
        with tempfile.TemporaryDirectory() as tmp:
            n = 0
            for md in files:
                text = md.read_text(encoding="utf-8")
                want = len(MERMAID.findall(text))
                if not want:
                    continue
                out = Path(tmp) / (str(md.relative_to(root)).replace("/", "_") + ".md")
                r = subprocess.run(["mmdc", "-q", "-i", str(md), "-o", str(out), "-e", "png"], capture_output=True, text=True)
                made = len(list(Path(tmp).glob(out.stem + "*.png")))
                n += made
                if r.returncode != 0 or made != want:
                    problems.append(f"{md.relative_to(root)}: mermaid を描けない ({made} / {want} 枚): {(r.stderr or r.stdout).strip()[-300:]}")
            notes.append(f"mermaid を {n} 枚描いた")
    return problems, notes


if __name__ == "__main__":
    found, said = check(Path(__file__).resolve().parents[4], render="--no-render" not in sys.argv)
    for line in said:
        print(line)
    if found:
        print("\n".join(found))
        sys.exit(1)
    print("ok")
