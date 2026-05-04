"""Validate already materialized comparison outputs against stability targets."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from hydromodpy.analysis.comparison.stability import (
    format_stability_report,
    validate_stability_targets,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Check comparison metrics, audit status, variants and key figures "
            "against a TOML stability target file."
        )
    )
    parser.add_argument(
        "--targets",
        default=Path(__file__).with_name("stability_targets.toml"),
        type=Path,
        help="Path to the stability target TOML file.",
    )
    parser.add_argument(
        "--case",
        dest="case_ids",
        action="append",
        help="Restrict validation to one case id. Can be passed more than once.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Write a compact JSON status instead of text.",
    )
    args = parser.parse_args(argv)

    report = validate_stability_targets(args.targets, case_ids=args.case_ids)
    if args.json:
        print(
            json.dumps(
                {
                    "ok": report.ok,
                    "targets_path": str(report.targets_path),
                    "cases": [
                        {
                            "id": case.target.case_id,
                            "ok": case.ok,
                            "comparison_root": str(case.target.comparison_root),
                            "findings": [
                                {
                                    "level": finding.level,
                                    "message": finding.message,
                                }
                                for finding in case.findings
                            ],
                        }
                        for case in report.cases
                    ],
                },
                indent=2,
            )
        )
    else:
        print(format_stability_report(report))
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
