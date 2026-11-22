"""batch-github-actions プロファイルを、小さな見本の置き場で確かめる。

既定の抽出器が、workflow ファイル 1 つを入口 1 件にし、起動のきっかけの印を付けること。
"""

from pathlib import Path

import yaml

from abatlas.enumerate import enumerate_entries
from abatlas.layout import init_repo
from abatlas.validate import validate_entry_list, validate_profile

REPO_ROOT = Path(__file__).resolve().parent.parent
PROFILE = REPO_ROOT / "profiles" / "batch-github-actions" / "profile.yaml"

# 架空の題材。(ファイル, 中身)
FILES = {
    ".github/workflows/test.yml": "name: test\n\non: [push, pull_request]\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n      - run: make test\n",
    ".github/workflows/nightly-report.yaml": "name: nightly\non:\n  schedule:\n    - cron: '0 18 * * *'\n  workflow_dispatch:\njobs: {}\n",
    ".github/workflows/publish.yml": "on:\n  workflow_call:\n    inputs: {}\njobs: {}\n",
    ".github/workflows/notes.md": "# workflow ではない\n",
    ".github/actions/setup/action.yml": "name: setup\nruns:\n  using: composite\n  steps: []\n",  # リポジトリの中の action。入口ではない
}


def test_profile_is_valid():
    assert validate_profile(yaml.safe_load(PROFILE.read_text(encoding="utf-8"))) == []


def test_workflow_files_become_entries(tmp_path: Path):
    target = tmp_path / "target"
    for rel, text in FILES.items():
        p = target / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    repo = tmp_path / "atlas"
    repo.mkdir()
    init_repo(repo, "batch-github-actions", targets="claude-code")
    profile = yaml.safe_load(PROFILE.read_text(encoding="utf-8"))
    ex = {k: v for k, v in profile["extractors"][0].items() if k != "hint"}
    ex["rationale"] = "workflow は .github/workflows の直下"
    el_path = repo / "analysis" / "entry-list.yaml"
    el_path.write_text(
        yaml.safe_dump(
            {
                "format_version": 1,
                "target": {
                    "repo": "example/kotori-ci",
                    "clone_path": str(target),
                    "scope": ".",
                    "commit": "0a1b2c3d4e",
                },
                "profile": {
                    "id": "batch-github-actions",
                    "version": profile["version"],
                },
                "extractors": [ex],
                "entries": [],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    enumerate_entries(el_path, PROFILE)
    el = yaml.safe_load(el_path.read_text(encoding="utf-8"))
    assert validate_entry_list(el, profile) == []
    got = {e["id"]: (e["path"], e["layer"], e["source"]["line"]) for e in el["entries"]}
    assert got == {
        "test": ("/test", "workflow", 3),  # 行は、on の行
        "nightly-report": ("/nightly-report", "workflow", 2),
        "publish": ("/publish", "workflow", 1),
    }
    flags = {
        e["id"]: {k: v for k, v in e["attributes"].items() if k != "file_segments"}
        for e in el["entries"]
    }
    assert flags["test"] == {
        "schedule": False,
        "workflow_dispatch": False,
        "workflow_call": False,
        "push": True,
        "pull_request": True,
    }
    assert flags["nightly-report"] == {
        "schedule": True,
        "workflow_dispatch": True,
        "workflow_call": False,
        "push": False,
        "pull_request": False,
    }
    assert flags["publish"] == {
        "schedule": False,
        "workflow_dispatch": False,
        "workflow_call": True,
        "push": False,
        "pull_request": False,
    }
