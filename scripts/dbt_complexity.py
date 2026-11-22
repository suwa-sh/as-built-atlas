"""Report structural metrics for dbt models from their compiled DuckDB SQL."""

import argparse
import csv
import json
import os
import subprocess  # nosec B404 - run the installed dbt in an isolated project
import sys
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory

from sqlglot import exp, parse_one
from sqlglot.errors import ParseError

from abatlas import REPO_ROOT
from abatlas.build import render_dbt_project
from abatlas.etl import COLUMNS, write_seeds


def model_rows(manifest, context):
    for node in manifest["nodes"].values():
        if node["resource_type"] != "model" or node.get("language", "sql") != "sql":
            continue
        model = node["unique_id"]
        sql = node.get("compiled_code")
        if not sql:
            raise ValueError(f"{model}: expected compiled SQL in the manifest")
        try:
            query = parse_one(sql, read="duckdb")
        except ParseError as exc:
            raise ValueError(f"{model}: {exc}") from exc
        if not isinstance(query, exp.Query):
            raise ValueError(f"{model}: expected a DuckDB query")
        counts = Counter(type(part) for part in query.walk())
        yield (
            counts[exp.Join],
            counts[exp.CTE],
            len(set(node["depends_on"]["nodes"])),
            context,
            model,
            node["original_file_path"],
        )


def compiled_manifest(profile):
    with TemporaryDirectory() as tmp:
        work = render_dbt_project(Path(tmp), profile_id=profile)
        write_seeds(dict.fromkeys(COLUMNS, ()), work / "seeds")
        subprocess.run(  # nosec B603 - interpreter's dbt and a temporary local project
            [
                str(Path(sys.executable).with_name("dbt")),
                "compile",
                "--profiles-dir",
                str(work),
                "--quiet",
            ],
            cwd=work,
            env={
                **os.environ,
                "ABATLAS_DUCKDB": str(work / "target.duckdb"),
                "DBT_SEND_ANONYMOUS_USAGE_STATS": "false",
            },
            stdout=sys.stderr,
            check=True,
        )
        return json.loads((work / "target/manifest.json").read_bytes())


def distribution_rows():
    profiles = REPO_ROOT / "profiles"
    overlays = sorted(p.parent.name for p in profiles.glob("*/dbt-template"))
    # A project with no profile templates still has the core models.
    for profile in overlays or [min(profiles.glob("*/profile.yaml")).parent.name]:
        yield from model_rows(compiled_manifest(profile), profile)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "manifest",
        nargs="?",
        type=Path,
        help="manifest.json from an existing full dbt compile or build",
    )
    args = parser.parse_args()
    rows = (
        model_rows(json.loads(args.manifest.read_bytes()), "manifest")
        if args.manifest
        else distribution_rows()
    )
    ranked = sorted(rows, key=lambda r: (-r[0], -r[1], -r[2], *r[3:]))
    table = csv.writer(sys.stdout, delimiter="\t", lineterminator="\n")
    table.writerow(("joins", "ctes", "direct_dependencies", "context", "model", "path"))
    table.writerows(ranked)


if __name__ == "__main__":
    main()
