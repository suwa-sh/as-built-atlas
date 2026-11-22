# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Rank Qlty function metrics, or fail lint on functions over the same limit."""

import argparse
import csv
import json
import subprocess  # nosec B404 - invokes the project's Qlty CLI
import sys

MAX_CYCLOMATIC = 10


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="show violations and fail on them"
    )
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument(
        "--all", action="store_true", help="measure all source files (default)"
    )
    scope.add_argument("--upstream", metavar="REF", help="measure changed source files")
    args = parser.parse_args()
    targets = ["--upstream", args.upstream] if args.upstream else ["--all"]
    result = subprocess.run(  # nosec B603 B607 - trusted mise tool, no shell
        [
            "qlty",
            "metrics",
            "--functions",
            "--exclude-tests",
            "--json",
            "--quiet",
            *targets,
        ],
        stdout=subprocess.PIPE,
        check=True,
    )
    functions = [
        s
        for s in json.loads(result.stdout)["stats"]
        if s["kind"] == "COMPONENT_TYPE_FUNCTION"
    ]
    if args.check:
        functions = [s for s in functions if s["cyclomatic"] > MAX_CYCLOMATIC]
        if not functions:
            return 0
        print(f"Cyclomatic complexity exceeds {MAX_CYCLOMATIC}:", file=sys.stderr)

    functions.sort(
        key=lambda s: (
            -s["cyclomatic"],
            -s["complexity"],
            s["path"],
            s["fullyQualifiedName"],
        )
    )
    table = csv.writer(sys.stdout, delimiter="\t", lineterminator="\n")
    table.writerow(("cyclomatic", "cognitive", "path", "function"))
    for row in functions:
        table.writerow(
            (
                row["cyclomatic"],
                row["complexity"],
                row["path"],
                row["fullyQualifiedName"],
            )
        )
    return int(args.check)


if __name__ == "__main__":
    sys.exit(main())
