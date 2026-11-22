"""文書の検査: リンク切れ、分析リポジトリに配ると切れるリンク、mermaid の危ない書き方 (描くところまではしない)。"""

import subprocess  # nosec B404 - executes subprocesses with argument lists
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHECK = ROOT / ".agents" / "skills" / "dev-docs" / "scripts" / "check_docs.py"


def test_docs_links_and_diagram_syntax():
    r = subprocess.run(  # nosec B603 - run the local checker with the test interpreter
        [sys.executable, str(CHECK), "--no-render"], capture_output=True, text=True
    )
    assert r.returncode == 0, r.stdout + r.stderr


def test_check_docs_finds_broken_and_unshipped_links(tmp_path: Path):
    """検査そのものが、壊れたリンクと、配布先で切れるリンクを見つけること (見つけない検査は、通っても意味が無い)。"""
    import runpy

    arch = tmp_path / "docs" / "architecture"
    arch.mkdir(parents=True)
    (tmp_path / "DESIGN.md").write_text("# d\n", encoding="utf-8")
    (tmp_path / "README.md").write_text(
        "![画像][shot]\n\n[shot]: docs/none.md\n\n"
        "`[例](code.md)`\n\n```md\n[例](code.md)\n```\n",
        encoding="utf-8",
    )
    (arch / "README.md").write_text(
        "[外](../../DESIGN.md)\n\n```mermaid\nflowchart LR\n  A[a (b)] --> B\n```\n",
        encoding="utf-8",
    )
    guide = tmp_path / "docs" / "guide"
    guide.mkdir()
    (guide / "README.md").write_text(
        "[仕組み](../architecture/README.md)\n\n[外](../../README.md)\n\n"
        "[ルートから](/docs/architecture/README.md)\n",
        encoding="utf-8",
    )
    sample = tmp_path / "examples" / "x-atlas"
    sample.mkdir(parents=True)
    (sample / "README.md").write_text(
        "[一覧](../../docs/none-examples.md)\n\n[入口](../../README.md)\n",
        encoding="utf-8",
    )
    mod = runpy.run_path(str(CHECK), run_name="check_docs_lib")
    problems = mod["check"](tmp_path)[0]
    # 見本の README のリンク切れも見つける (文書を動かしたときに、置き去りになりやすい)
    assert any(
        "examples/x-atlas/README.md" in p and "none-examples.md" in p for p in problems
    ), problems
    assert not any(
        "examples/x-atlas/README.md" in p and "../../README.md" in p for p in problems
    ), problems
    assert not any("code.md" in p for p in problems)  # nosec B101 - pytest assertion
    # 配る置き場どうしのリンクは切れない。配る置き場から外へのリンクだけを止める
    assert not any("../architecture/README.md" in p for p in problems), problems
    assert any(
        "docs/guide/README.md" in p and "の外" in p and "../../README.md" in p
        for p in problems
    ), problems
    # 配布先では、リポジトリのルートが変わる。ルートからの指定は、配る置き場の中を指していても止める
    assert any(
        "ルートからの指定" in p and "/docs/architecture/README.md" in p
        for p in problems
    ), problems
    # 配る置き場の一覧は、配布の実装と同じ
    from abatlas.layout import OSS_REFERENCE_ITEMS

    assert set(mod["SHIPPED"]) == {
        item for item in OSS_REFERENCE_ITEMS if item.startswith("docs/")
    }
    assert any("リンク切れ" in p and "docs/none.md" in p for p in problems), problems
    assert any(
        "docs/architecture/README.md" in p and "の外" in p and "../../DESIGN.md" in p
        for p in problems
    ), problems
    assert any("mermaid" in p for p in problems), problems
