"""Trivy policy regressions using reports with no dependency on today's database."""

import datetime as dt
import os
import tempfile
import zipfile
from pathlib import Path
from unittest import TestCase, mock

from scripts import scan


class SecurityPolicyTests(TestCase):
    def setUp(self):
        self.finding = {
            "VulnerabilityID": "CVE-test",
            "PkgName": "child",
            "InstalledVersion": "1",
            "FixedVersion": "2",
            "Severity": "LOW",
            "PkgIdentifier": {"PURL": "pkg:pypi/child@1"},
        }
        self.result = {
            "Target": "uv.lock",
            "Class": "lang-pkgs",
            "Type": "uv",
            "Packages": [{"Name": "child"}],
            "Vulnerabilities": [self.finding],
        }
        self.rule = {
            "id": "CVE-test",
            "purl": "pkg:pypi/child@1",
            "target": "uv.lock",
            "parent": "parent",
            "upstream": "pypi/parent",
            "parent_release": "1",
            "expires": dt.datetime.now(dt.timezone.utc).date() + dt.timedelta(days=7),
            "reason": "The released parent requires child < 2.",
            "evidence": "https://upstream.example/manifest",
        }
        self.lock = (
            {"parent": {"child"}},
            {"parent"},
            {("parent", "1"), ("child", "1")},
        )
        self.lock[0]["child"] = set()

    def gate(self, *rules):
        with mock.patch.object(scan, "locked_dependencies", return_value=self.lock):
            return scan.check({"Results": [self.result]}, rules, "lock")

    def test_fixed_version_gates_even_low_and_unknown(self):
        for severity in ("LOW", "UNKNOWN", "CRITICAL"):
            self.finding["Severity"] = severity
            self.assertEqual(self.gate(), 1)
        self.finding["FixedVersion"] = ""
        self.assertEqual(self.gate(), 0)

    def test_published_image_uses_its_release_revision(self):
        revision = "a" * 40
        report = {
            "Metadata": {
                "ImageConfig": {
                    "config": {
                        "Labels": {"org.opencontainers.image.revision": revision}
                    }
                }
            },
            "Results": [{"Class": "os-pkgs", "Type": "debian"}],
        }
        with mock.patch.object(
            scan, "locked_dependencies", return_value=self.lock
        ) as locked:
            self.assertEqual(scan.check(report, [self.rule], "published"), 0)
            locked.assert_called_once_with(revision)
        with self.assertRaises(ValueError):
            scan.locked_dependencies("invalid")

    def test_unrecognized_lock_fails(self):
        with self.assertRaises(ValueError):
            scan.check({"Results": []}, [], "lock")

    @mock.patch.object(scan, "parent_blocks_fix", return_value=True)
    @mock.patch.object(scan, "latest_release", return_value="1")
    def test_only_exact_blocked_transitive_is_waived(self, latest, blocked):
        self.assertEqual(self.gate(self.rule), 0)
        for field, value in (
            ("id", "other"),
            ("target", "Python"),
            ("purl", "pkg:pypi/child@2"),
            ("expires", dt.datetime.now(dt.timezone.utc).date()),
            ("parent", "unrelated"),
        ):
            with self.subTest(field=field):
                self.assertEqual(self.gate(self.rule | {field: value}), 1)
        blocked.return_value = False
        self.assertEqual(self.gate(self.rule), 1)
        blocked.return_value = True
        latest.return_value = "2"
        self.assertEqual(self.gate(self.rule), 1)
        latest.return_value = "1"
        self.lock[1].add("child")
        self.assertEqual(self.gate(self.rule), 1)

    @mock.patch.object(scan, "latest_release", return_value="v1")
    def test_binary_exception_needs_a_path_from_the_released_root(self, latest):
        root = {
            "ID": "app@1",
            "Name": "app",
            "Version": "1",
            "Relationship": "root",
            "DependsOn": ["child@1"],
        }
        self.result.update(Type="rustbinary", Target="usr/bin/app", Packages=[root])
        self.finding.update(
            PkgID="child@1", PkgIdentifier={"PURL": "pkg:cargo/child@1"}
        )
        rule = self.rule | {
            "purl": "pkg:cargo/child@1",
            "target": "usr/bin/app",
            "parent": "app",
            "parent_release": "v1",
            "upstream": "github/test/app",
        }
        self.assertEqual(
            scan.report_finding(self.finding, self.result, [rule], self.lock), 0
        )
        root["DependsOn"] = []
        self.assertEqual(
            scan.report_finding(self.finding, self.result, [rule], self.lock), 1
        )

    def test_resolves_each_candidate_across_release_branches(self):
        def wheel(directory, name, version, dependency=""):
            info = f"{name}-{version}.dist-info"
            metadata = f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n"
            if dependency:
                metadata += f"Requires-Dist: {dependency}\n"
            with zipfile.ZipFile(
                directory / f"{name}-{version}-py3-none-any.whl", "w"
            ) as archive:
                archive.writestr(f"{info}/METADATA", metadata)
                archive.writestr(
                    f"{info}/WHEEL", "Wheel-Version: 1.0\nTag: py3-none-any\n"
                )
                archive.writestr(f"{info}/RECORD", "")

        def advisory_database(command):
            pins = Path(command[-1]).read_text().splitlines()
            version = next(
                line.split("==")[1] for line in pins if line.startswith("child==")
            )
            vulnerable = [self.finding] if version == "2.0.7" else []
            return {
                "Results": [
                    {
                        "Type": "pip",
                        "Packages": [{"Name": "child", "Version": version}],
                        "Vulnerabilities": vulnerable,
                    }
                ]
            }

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            for version in ("1.9.9", "2.0.7", "2.0.8"):
                wheel(directory, "child", version)
            wheel(directory, "parent", "1", "child>=2.0,<2.0.8")
            wheel(directory, "parent", "2", "child>=2.0")
            with (
                mock.patch.dict(os.environ, {"UV_NO_INDEX": "1", "UV_FIND_LINKS": tmp}),
                mock.patch.object(scan, "scan_packages", side_effect=advisory_database),
            ):
                args = (
                    "child",
                    "2.0.6",
                    "1.9.9, 2.0.8",
                    self.finding["VulnerabilityID"],
                )
                self.assertTrue(scan.parent_blocks_fix("parent", "1", *args))
                self.assertFalse(scan.parent_blocks_fix("parent", "2", *args))
