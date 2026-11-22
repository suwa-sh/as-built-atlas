"""Run the upstream adapter and hook regression suites against the vendored copy."""

from pathlib import Path
import subprocess  # nosec B404 - run the regression suites shipped with mid-harness

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / ".agents/skills/mid-harness/scripts"


@pytest.mark.parametrize(
    "suite",
    [
        ("test_scripts.sh",),
        ("test_hook.sh",),
        ("test_hook.sh", ROOT / "scripts/agent-hooks/pre-tool-policy.sh"),
    ],
)
def test_mid_harness_suite(suite, tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    monkeypatch.setenv("PYTHONDONTWRITEBYTECODE", "1")
    subprocess.run([SCRIPTS / suite[0], *suite[1:]], check=True)  # nosec B603 - fixed local suites
