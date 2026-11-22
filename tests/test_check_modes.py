"""Exercise the public check command without installing scanners or building images."""

import json
import os
import subprocess  # nosec B404 - exercises the repository CLI
import sys
import tempfile
from pathlib import Path
from unittest import TestCase


CHECK = Path(__file__).resolve().parents[1] / "scripts/check"


class CheckModesTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name)
        self.env = {**os.environ, "PATH": f"{self.tmp.name}:{os.environ['PATH']}"}
        self.env.pop("CHECK_BASE", None)
        for name in ("qlty", "gitleaks", "uv", "docker"):
            stub = self.repo / name
            stub.write_text('#!/bin/sh\nprintf "%s %s\\n" "${0##*/}" "$*"\n')
            stub.chmod(0o755)
        self.call("git", "init", "-q").check_returncode()
        self.call(
            "git",
            "-c",
            "user.email=test@example.invalid",
            "-c",
            "user.name=test",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "core.hooksPath=/dev/null",
            "commit",
            "--allow-empty",
            "-qm",
            "fixture",
        ).check_returncode()

    def call(self, *command):
        return subprocess.run(
            command, cwd=self.repo, env=self.env, text=True, capture_output=True
        )  # nosec B603

    def test_modes_select_scope(self):
        head = self.call("git", "rev-parse", "HEAD").stdout.strip()
        self.call(
            "git", "update-ref", "refs/remotes/origin/main", head
        ).check_returncode()
        for args, option in (
            (("dev", "lint"), "--upstream"),
            (("main", "lint"), "--all"),
            (("pr", "lint"), f"--upstream {head}"),
        ):
            with self.subTest(args=args):
                result = self.call(CHECK, *args)
                result.check_returncode()
                self.assertIn(option, result.stdout)
                self.assertIn(f"scripts/complexity.py --check {option}", result.stdout)

    def test_complexity_listing_and_threshold(self):
        script = CHECK.with_name("complexity.py")
        tool = self.repo / "qlty"
        tool.write_text("#!/bin/sh\ncat metrics.json\n")
        stats = [
            {
                "kind": "COMPONENT_TYPE_FUNCTION",
                "path": "example.py",
                "fullyQualifiedName": name,
                "complexity": 4,
                "cyclomatic": score,
            }
            for name, score in (("boundary", 10), ("over", 11))
        ]
        metrics = self.repo / "metrics.json"
        metrics.write_text(json.dumps({"stats": stats}))
        report = self.call(sys.executable, script)
        report.check_returncode()
        self.assertEqual(
            report.stdout.splitlines()[1:],
            ["11\t4\texample.py\tover", "10\t4\texample.py\tboundary"],
        )
        gate = self.call(sys.executable, script, "--check", "--all")
        self.assertEqual(gate.returncode, 1)
        self.assertIn("over", gate.stdout)
        self.assertNotIn("boundary", gate.stdout)
        metrics.write_text(json.dumps({"stats": stats[:1]}))
        self.call(sys.executable, script, "--check", "--all").check_returncode()
        tool.write_text("#!/bin/sh\nexit 2\n")
        self.assertNotEqual(self.call(sys.executable, script).returncode, 0)

    def test_default_commands_dispatch_checks_for_the_scene(self):
        self.env["CHECK_BASE"] = "HEAD"
        runner = self.repo / "scripts" / "check"
        runner.parent.mkdir()
        runner.write_bytes(CHECK.read_bytes())
        runner.chmod(0o755)
        docker = self.repo / "docker"
        docker.write_text(
            '#!/bin/sh\nwhile [ "$#" -gt 0 ]; do\n'
            '  if [ "$1" = --iidfile ]; then echo image-id > "$2"; break; fi\n'
            "  shift\ndone\n"
        )
        for mode, phases in (
            ("dev", ["format", "generate", "lint", "test", "security"]),
            ("pr", ["generate", "format", "lint", "build", "test", "security"]),
            ("main", ["generate", "format", "lint", "build", "test", "security"]),
        ):
            with self.subTest(mode=mode):
                run = self.call(runner, mode)
                run.check_returncode()
                self.assertEqual(
                    [s for s in run.stdout.splitlines() if s.startswith("[")],
                    [f"[{mode}] {phase}" for phase in phases],
                )
                self.assertIn("scripts/scan.py lock", run.stdout)
                self.assertEqual(
                    "scripts/scan.py image image-id" in run.stdout, mode != "dev"
                )
                self.assertEqual("qlty fmt" in run.stdout, mode == "dev")
        for args in (("dev", "diff"), ("ci", "full"), ("main", "diff", "format")):
            with self.subTest(args=args):
                self.assertEqual(self.call(runner, *args).returncode, 2)

    def test_hook_is_staged_only(self):
        result = self.call(CHECK, "hook", "security")
        result.check_returncode()
        self.assertIn("gitleaks git --staged", result.stdout)
        self.assertNotIn("scan.py", result.stdout)
        self.assertEqual(self.call(CHECK, "hook", "full").returncode, 2)

    def test_hook_checks_active_index_and_preserves_worktree(self):
        # A path-limited commit can give the hook an index other than .git/index.
        target = self.repo / "partially staged.py"
        target.write_text("ordinary index")
        self.call("git", "add", target.name).check_returncode()
        self.env["GIT_INDEX_FILE"] = str(self.repo / ".git" / "alternate-index")
        target.write_text("commit candidate")
        self.call("git", "add", target.name).check_returncode()
        target.write_text("unstaged changes")
        tree = self.call("git", "write-tree").stdout
        tool = self.repo / "qlty"
        tool.write_text(
            '#!/bin/sh\nprintf "%s\\n" "$*"\ncat "partially staged.py"\nexit 1\n'
        )
        for phase, flag in (
            ((), "--no-fix"),
            (
                ("format",),
                "ruff:fmt,markdownlint:fmt,sqlfluff:fmt,prettier:fmt,shfmt:fmt,dockerfmt:fmt",
            ),
            (("lint",), "--no-formatters"),
        ):
            with self.subTest(phase=phase):
                result = self.call(CHECK, "hook", *phase)
                self.assertEqual(result.returncode, 1)
                self.assertIn(flag, result.stdout)
                self.assertIn("commit candidate", result.stdout)
                self.assertNotIn("unstaged changes", result.stdout)
        self.assertEqual(self.call("git", "write-tree").stdout, tree)
        self.assertEqual(target.read_text(), "unstaged changes")
        self.env.pop("GIT_INDEX_FILE")
        self.assertEqual(
            self.call("git", "show", f":{target.name}").stdout, "ordinary index"
        )
        self.assertFalse((self.repo / ".git" / "abatlas-hook-check").exists())

    def test_hook_checks_links_when_only_target_is_removed_from_index(self):
        self.env["CHECK_TEST_PYTHON"] = sys.executable
        (self.repo / "uv").write_text(
            '#!/bin/sh\n[ "$2" != "--script" ] || exit 0\n'
            '[ "$*" = "run --isolated --locked --only-group docs python .agents/skills/dev-docs/scripts/check_docs.py --no-render" ] || exit 2\n'
            'exec "$CHECK_TEST_PYTHON" "$7" "$8"\n'
        )
        checker = Path(".agents/skills/dev-docs/scripts/check_docs.py")
        (self.repo / checker.parent).mkdir(parents=True)
        (self.repo / checker).write_bytes((CHECK.parents[1] / checker).read_bytes())
        target = self.repo / "example.txt"
        target.touch()
        (self.repo / "README.ja.md").write_text("[Example](example.txt)\n")
        self.call(
            "git", "add", str(checker), "README.ja.md", target.name
        ).check_returncode()
        self.call(
            "git",
            "-c",
            "user.name=test",
            "-c",
            "user.email=test@example.invalid",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-qm",
            "linked document",
        ).check_returncode()
        self.call("git", "rm", "--cached", target.name).check_returncode()
        for phase in ((), ("test",)):
            with self.subTest(phase=phase):
                result = self.call(CHECK, "hook", *phase)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("README.ja.md: リンク切れ: example.txt", result.stdout)
        self.assertTrue(target.exists())

    def test_missing_diff_base_does_not_skip_independent_checks(self):
        self.env["CHECK_BASE"] = "missing-ref"
        self.call(CHECK, "dev", "lint").check_returncode()
        self.call(CHECK, "main", "lint").check_returncode()
        self.call(CHECK, "pr", "test").check_returncode()
        result = self.call(CHECK, "pr", "security")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("scripts/scan.py lock", result.stdout)
