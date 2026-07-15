"""Score one B0 candidate from two persisted HydroModPy runs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hydromodpy.calibration.observations.network_transient_truth import (  # noqa: E402
    score_network_transient_candidate_from_runs,
)
from hydromodpy.results.catalog import Catalog  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--truth-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "truth",
        help="B0 truth package directory.",
    )
    parser.add_argument(
        "--steady-catalog",
        type=Path,
        required=True,
        help="Workspace or hydromodpy.duckdb file containing the candidate steady run.",
    )
    parser.add_argument("--steady-ref", required=True)
    parser.add_argument("--steady-project", default=None)
    parser.add_argument(
        "--transient-catalog",
        type=Path,
        default=None,
        help="Workspace or hydromodpy.duckdb file containing the candidate transient run. Defaults to --steady-catalog.",
    )
    parser.add_argument("--transient-ref", required=True)
    parser.add_argument("--transient-project", default=None)
    parser.add_argument(
        "--output-json",
        type=Path,
        default=None,
        help="Optional path where the score components are written as JSON.",
    )
    args = parser.parse_args(argv)

    steady_catalog = Catalog(args.steady_catalog)
    transient_catalog = None
    try:
        steady_sim_id = steady_catalog.resolve(args.steady_ref, project=args.steady_project)
        steady_run = steady_catalog[steady_sim_id]

        transient_catalog_path = args.transient_catalog or args.steady_catalog
        if Path(transient_catalog_path).resolve() == Path(args.steady_catalog).resolve():
            transient_catalog = steady_catalog
        else:
            transient_catalog = Catalog(transient_catalog_path)
        transient_sim_id = transient_catalog.resolve(
            args.transient_ref,
            project=args.transient_project,
        )
        transient_run = transient_catalog[transient_sim_id]

        score = score_network_transient_candidate_from_runs(
            args.truth_dir,
            steady_run=steady_run,
            transient_run=transient_run,
        )
    finally:
        if transient_catalog is not None and transient_catalog is not steady_catalog:
            transient_catalog.close()
        steady_catalog.close()

    payload = {
        "objective": float(score.total),
        "components": {key: float(value) for key, value in score.components.items()},
    }
    text = json.dumps(payload, indent=2, sort_keys=True)
    if args.output_json is not None:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
