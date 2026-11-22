"""Gate Trivy findings and recheck reviewed exceptions against the upstream release."""

import argparse
import datetime as dt
import json
import os
import re
import subprocess  # nosec B404 - invokes the repository toolchain without a shell
import sys
import tempfile
import tomllib
from functools import cache
from pathlib import Path
from urllib.request import urlopen

from packaging.utils import canonicalize_name
from packaging.version import Version


@cache
def latest_release(upstream):
    # Only query public release metadata on supported registries.
    if upstream.startswith("pypi/"):
        project = upstream.removeprefix("pypi/")
        if not re.fullmatch(r"[\w.-]+", project):
            raise ValueError(f"invalid PyPI project: {project}")
        url = f"https://pypi.org/pypi/{project}/json"
        with urlopen(url, timeout=20) as response:  # nosec B310
            return json.load(response)["info"]["version"]
    if not re.fullmatch(r"github/[\w.-]+/[\w.-]+", upstream):
        raise ValueError(f"invalid upstream: {upstream}")
    repo = upstream.removeprefix("github/")
    with urlopen(  # nosec B310
        f"https://api.github.com/repos/{repo}/releases/latest", timeout=20
    ) as response:
        return json.load(response)["tag_name"]


def locked_dependencies(revision=None):
    if revision is None:
        content = Path("uv.lock").read_bytes()
    else:
        if not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise ValueError("invalid release revision in image labels")
        # Use the dependency graph of the published revision and today's exception policy.
        command = ["git", "show", f"{revision}:uv.lock"]
        content = subprocess.check_output(command)  # nosec B603
    packages = tomllib.loads(content.decode("utf-8"))["package"]
    graph = {}
    for pkg in packages:
        edges = list(pkg.get("dependencies", []))
        for group in ("optional-dependencies", "dev-dependencies"):
            for dependencies in pkg.get(group, {}).values():
                edges.extend(dependencies)
        graph.setdefault(pkg["name"], set()).update(edge["name"] for edge in edges)
    root = next(pkg["name"] for pkg in packages if pkg["source"].get("editable") == ".")
    versions = {(pkg["name"], pkg["version"]) for pkg in packages}
    return graph, graph[root] | {root}, versions


def is_descendant(graph, parent, child):
    remaining = [parent]
    visited = set()
    while remaining:
        name = remaining.pop()
        if child in graph.get(name, ()):
            return True
        visited.add(name)
        remaining.extend(graph.get(name, set()) - visited)
    return False


def resolve(requirements, directory):
    command = [
        "uv",
        "pip",
        "compile",
        "--no-config",
        "--refresh",
        "--python-version",
        "3.12",
        "--no-header",
        "--no-annotate",
        "-",
    ]
    # Package constraints go to uv through stdin.
    result = subprocess.run(
        command,
        input=requirements,
        text=True,
        capture_output=True,
        cwd=directory,
        env={**os.environ, "NO_COLOR": "1"},
    )  # nosec B603
    if result.returncode == 0:
        return result.stdout
    if result.returncode == 1 and "No solution found" in result.stderr:
        return None
    raise RuntimeError(result.stderr)


def scan_packages(command):
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "report.json"
        options = [
            "--scanners",
            "vuln",
            "--ignorefile",
            "/dev/null",
            "--list-all-pkgs",
            "--format",
            "json",
            "--output",
            str(report),
        ]
        invocation = ["trivy", command[0], *options, *command[1:]]
        subprocess.run(invocation, check=True)  # nosec B603 - fixed scanner, no shell
        return json.loads(report.read_bytes())


@cache
def parent_blocks_fix(parent, version, child, installed, fixed, advisory):
    lower = min(Version(v.strip()) for v in fixed.split(","))
    parent_pin = f"{parent}=={version}"
    child_range = f"{child}>{installed},>={lower}"
    with tempfile.TemporaryDirectory() as tmp:
        if resolve(parent_pin, tmp) is None or resolve(child_range, tmp) is None:
            raise ValueError(
                "cannot independently resolve the parent and the upgrade candidate"
            )
        while True:
            pins = resolve(f"{parent_pin}\n{child_range}", tmp)
            if pins is None:
                return True
            requirements = Path(tmp) / "requirements.txt"
            requirements.write_text(pins)
            # A version above the first fixed release may still be vulnerable on
            # another maintenance branch. Ask the same Trivy database about it.
            report = scan_packages(["fs", str(requirements)])
            result = next(r for r in report["Results"] if r["Type"] == "pip")
            candidate = next(
                p["Version"]
                for p in result["Packages"]
                if canonicalize_name(p["Name"]) == child
            )
            if not any(
                canonicalize_name(v["PkgName"]) == child
                and v["VulnerabilityID"] == advisory
                for v in result.get("Vulnerabilities", [])
            ):
                return False
            child_range += f",!={Version(candidate)}"


def locked_transitive_dependency(lock, parent, version, child, installed):
    graph, direct, versions = lock
    return (
        parent in direct
        and child not in direct
        and (parent, version) in versions
        and (child, installed) in versions
        and is_descendant(graph, parent, child)
    )


def python_exception(rule, finding, result, lock):
    parent = rule["parent"]
    version = rule["parent_release"].removeprefix("v")
    child = canonicalize_name(finding["PkgName"])
    installed = finding["InstalledVersion"]
    if (
        result["Type"] not in ("uv", "python-pkg")
        or rule["upstream"] != f"pypi/{parent}"
    ):
        return False
    # Only the application environment inherits the constraints in uv.lock.
    if result["Type"] == "python-pkg" and not finding.get("PkgPath", "").startswith(
        "opt/abatlas/.venv/"
    ):
        return False
    return (
        locked_transitive_dependency(lock, parent, version, child, installed)
        and latest_release(rule["upstream"]) == rule["parent_release"]
        and parent_blocks_fix(
            parent,
            version,
            child,
            installed,
            finding["FixedVersion"],
            finding["VulnerabilityID"],
        )
    )


def binary_exception(rule, finding, result):
    parent = rule["parent"]
    release = rule["parent_release"]
    version = release.removeprefix("v")
    # Compiled dependencies must actually be reachable from the scanned binary's root.
    packages = result.get("Packages", [])
    roots = [
        p
        for p in packages
        if p.get("Relationship") == "root"
        and p["Name"] == parent
        and p["Version"] == version
    ]
    graph = {p["ID"]: set(p.get("DependsOn", [])) for p in packages if "ID" in p}
    return (
        result["Type"] in ("rustbinary", "gobinary")
        and any(
            p["ID"] != finding["PkgID"]
            and is_descendant(graph, p["ID"], finding["PkgID"])
            for p in roots
        )
        and latest_release(rule["upstream"]) == release
    )


def eligible(rule, finding, result, lock):
    """Verify a reviewed upstream block for this package and exact parent release."""
    if not rule["reason"].strip() or not rule["evidence"].startswith("https://"):
        raise ValueError("exception needs an upstream explanation and evidence URL")
    if rule["expires"] <= dt.datetime.now(dt.timezone.utc).date():
        return False
    if rule["purl"].startswith("pkg:pypi/"):
        return python_exception(rule, finding, result, lock)
    return binary_exception(rule, finding, result)


def report_finding(finding, result, rules, lock, show_unfixed=False):
    if not finding.get("FixedVersion"):
        if show_unfixed:
            print(
                f"UNFIXED {result['Target']} {finding['VulnerabilityID']} {finding['Severity']} "
                f"{finding['PkgName']} {finding['InstalledVersion']}"
            )
        return 0
    purl = finding.get("PkgIdentifier", {}).get("PURL")
    # For images the OS target contains the image ID. Use the OS type for
    # that result; language and embedded-binary targets have stable paths.
    target = result["Type"] if result["Class"] == "os-pkgs" else result["Target"]
    matches = (
        r
        for r in rules
        if (r["id"], r["purl"], r["target"])
        == (finding["VulnerabilityID"], purl, target)
    )
    waived = any(eligible(r, finding, result, lock) for r in matches)
    status = "EXCEPTION" if waived else "ERROR"
    print(
        f"{status} {target} {finding['VulnerabilityID']} {finding['Severity']} "
        f"{finding['PkgName']} {finding['InstalledVersion']} -> {finding['FixedVersion']}"
    )
    return int(not waived)


def validate_scan_targets(results, kind):
    if kind == "lock" and not any(
        r["Type"] == "uv" and r.get("Packages") for r in results
    ):
        raise ValueError("Trivy did not identify packages in uv.lock")
    if kind != "lock" and not any(r.get("Class") == "os-pkgs" for r in results):
        raise ValueError("Trivy did not identify the distribution's OS packages")


def check(report, rules, kind, show_unfixed=False):
    results = report["Results"]
    validate_scan_targets(results, kind)
    revision = None
    if rules and kind == "published":
        revision = report["Metadata"]["ImageConfig"]["config"]["Labels"][
            "org.opencontainers.image.revision"
        ]
    lock = locked_dependencies(revision) if rules else None
    failures = 0
    unfixed = 0
    for result in results:
        for finding in result.get("Vulnerabilities", []):
            unfixed += not finding.get("FixedVersion")
            failures += report_finding(finding, result, rules, lock, show_unfixed)
    print(f"Trivy: {failures} unexcepted fixable finding(s)")
    if show_unfixed:
        print(f"Trivy: {unfixed} finding(s) awaiting a fix (see UNFIXED in the log)")
    return int(bool(failures))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=["lock", "image", "archive", "published"])
    parser.add_argument("artifact", nargs="?")
    parser.add_argument("--arch", choices=["amd64", "arm64"])
    parser.add_argument("--show-unfixed", action="store_true")
    args = parser.parse_args()
    if (args.kind == "lock") != (args.artifact is None):
        parser.error("image scans require an artifact; lock reads uv.lock")
    if args.kind == "lock":
        command = ["fs", "--include-dev-deps", "uv.lock"]
    elif args.kind == "published":
        if not args.arch or not re.fullmatch(
            r"[^@]+@sha256:[0-9a-f]{64}", args.artifact
        ):
            parser.error("published requires an image digest and --arch")
        command = [
            "image",
            "--image-src",
            "remote",
            "--platform",
            f"linux/{args.arch}",
            args.artifact,
        ]
    elif args.kind == "archive":
        command = ["image", "--input", args.artifact]
    else:
        command = ["image", "--image-src", "docker", args.artifact]
    data = scan_packages(command)
    if args.arch and data["Metadata"]["ImageConfig"]["architecture"] != args.arch:
        raise ValueError(f"expected a {args.arch} image")
    rules = tomllib.loads(Path(".trivy-exceptions.toml").read_text())["exception"]
    return check(data, rules, args.kind, args.show_unfixed)


if __name__ == "__main__":
    sys.exit(main())
