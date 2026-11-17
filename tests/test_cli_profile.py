"""cli プロファイル (コマンドラインの道具) を、小さな見本の置き場で確かめる。

既定の抽出器が、実行ファイルを入口にし、置き場のフォルダ (bin) と拡張子を階層から落とすこと。
"""

from pathlib import Path

import yaml

from abatlas.enumerate import enumerate_entries
from abatlas.layout import init_repo
from abatlas.validate import validate_entry_list, validate_profile

REPO_ROOT = Path(__file__).resolve().parent.parent
PROFILE = REPO_ROOT / "profiles" / "cli" / "profile.yaml"

# 架空の題材。(ファイル, 中身)
FILES = {
    "bin/kotori": "#!/usr/bin/env bash\n# 入口\nset -euo pipefail\nexec \"$(dirname \"$0\")/../src/main.sh\" \"$@\"\n",
    "gateway/bin/validate-config.sh": "#!/usr/bin/env bash\nset -euo pipefail\n",
    "gateway/bin/rerun.py": "#!/usr/bin/env python3\nimport sys\n",
    "gateway/src/usecase/validate.sh": "validate() { :; }\n",   # source されるだけ。入口ではない
    "src/main.sh": "#!/usr/bin/env bash\n",
}


def test_profile_is_valid():
    assert validate_profile(yaml.safe_load(PROFILE.read_text(encoding="utf-8"))) == []


def test_executables_become_entries(tmp_path: Path):
    target = tmp_path / "target"
    for rel, text in FILES.items():
        p = target / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    repo = tmp_path / "atlas"
    repo.mkdir()
    init_repo(repo, "cli", targets="claude-code")
    profile = yaml.safe_load(PROFILE.read_text(encoding="utf-8"))
    ex = {k: v for k, v in profile["extractors"][0].items() if k != "hint"}
    ex["rationale"] = "実行ファイルは bin/ と <部品>/bin/ にある"
    el_path = repo / "analysis" / "entry-list.yaml"
    el_path.write_text(yaml.safe_dump({
        "format_version": 1, "target": {"repo": "example/kotori-cli", "clone_path": str(target), "scope": ".", "commit": "0a1b2c3d4e"},
        "profile": {"id": "cli", "version": profile["version"]}, "extractors": [ex], "entries": []}, allow_unicode=True, sort_keys=False), encoding="utf-8")
    enumerate_entries(el_path, PROFILE)
    el = yaml.safe_load(el_path.read_text(encoding="utf-8"))
    assert validate_entry_list(el, profile) == []
    got = {e["id"]: (e["path"], e["layer"], e["source"]["file"], e["source"]["line"]) for e in el["entries"]}
    assert got == {
        "kotori": ("/kotori", "command", "bin/kotori", 3),                       # 行は、コメントでない最初の行
        "gateway.validate-config": ("/gateway/validate-config", "command", "gateway/bin/validate-config.sh", 2),
        "gateway.rerun": ("/gateway/rerun", "command", "gateway/bin/rerun.py", 2),
    }
