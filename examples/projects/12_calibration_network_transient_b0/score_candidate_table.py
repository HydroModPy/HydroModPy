"""Score a table of B0 candidate run pairs and rank them by objective."""

# ruff: noqa: E402,I001

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hydromodpy.calibration.network_transient_truth import (
    CandidateScore,
    score_network_transient_candidate,
    score_network_transient_candidate_from_runs,
)
from hydromodpy.results.catalog import Catalog


REQUIRED_COLUMNS = ("steady_catalog", "steady_ref", "transient_ref")
OPTIONAL_COLUMNS = (
    "candidate_id",
    "mK",
    "Sy",
    "steady_project",
    "transient_catalog",
    "transient_project",
)


def load_candidate_specs(path: str | Path) -> list[dict[str, str]]:
    """Load and validate a B0 candidate table."""

    csv_path = Path(path)
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError(f"Candidate table is empty: {csv_path}")
        missing = [name for name in REQUIRED_COLUMNS if name not in reader.fieldnames]
        if missing:
            raise ValueError(f"Candidate table missing required columns: {missing}")
        rows = []
        for index, raw in enumerate(reader, start=1):
            spec = {key: (value or "").strip() for key, value in raw.items()}
            for name in REQUIRED_COLUMNS:
                if not spec.get(name):
                    raise ValueError(f"Row {index} has empty required column {name!r}.")
            if not spec.get("candidate_id"):
                spec["candidate_id"] = f"candidate_{index:04d}"
            if not spec.get("transient_catalog"):
                spec["transient_catalog"] = spec["steady_catalog"]
            rows.append(spec)
    return rows


def score_candidate_specs(
    specs: list[dict[str, str]],
    *,
    truth_dir: str | Path,
) -> pd.DataFrame:
    """Score candidate specs against one B0 truth package."""

    catalog_cache: dict[Path, Catalog] = {}
    rows: list[dict[str, Any]] = []
    try:
        for spec in specs:
            rows.append(
                _score_one_spec(spec, truth_dir=Path(truth_dir), catalog_cache=catalog_cache)
            )
    finally:
        for catalog in catalog_cache.values():
            catalog.close()
    frame = pd.DataFrame(rows)
    if "objective" in frame.columns:
        frame["_status_rank"] = (frame.get("status") == "completed").astype(int)
        frame = (
            frame.sort_values(
                by=["_status_rank", "objective"],
                ascending=[False, True],
                na_position="last",
            )
            .drop(columns=["_status_rank"])
            .reset_index(drop=True)
        )
        frame.insert(0, "rank", range(1, len(frame) + 1))
    return frame


def _score_one_spec(
    spec: dict[str, str],
    *,
    truth_dir: Path,
    catalog_cache: dict[Path, Catalog],
) -> dict[str, Any]:
    base = {
        "candidate_id": spec.get("candidate_id", ""),
        "mK": _float_or_nan(spec.get("mK")),
        "Sy": _float_or_nan(spec.get("Sy")),
        "steady_catalog": spec.get("steady_catalog", ""),
        "steady_ref": spec.get("steady_ref", ""),
        "transient_catalog": spec.get("transient_catalog", ""),
        "transient_ref": spec.get("transient_ref", ""),
    }
    try:
        steady_catalog = _catalog_for(spec["steady_catalog"], catalog_cache)
        transient_catalog = _catalog_for(spec["transient_catalog"], catalog_cache)
        steady_run = steady_catalog[
            steady_catalog.resolve(
                spec["steady_ref"],
                project=_empty_to_none(spec.get("steady_project")),
            )
        ]
        transient_run = transient_catalog[
            transient_catalog.resolve(
                spec["transient_ref"],
                project=_empty_to_none(spec.get("transient_project")),
            )
        ]
        score = _score_from_runs_with_b0_fallback(
            truth_dir,
            steady_run=steady_run,
            transient_run=transient_run,
        )
    except Exception as exc:
        base.update({"status": "failed", "objective": math.nan, "error": str(exc)})
        return base

    base.update({"status": "completed", "objective": float(score.total), "error": ""})
    base.update({key: float(value) for key, value in score.components.items()})
    return base


def _score_from_runs_with_b0_fallback(
    truth_dir: Path,
    *,
    steady_run: Any,
    transient_run: Any,
) -> CandidateScore:
    """Score a B0 pair, falling back to persisted catchment discharge.

    The canonical helper reads the full transient ``outflow_drain`` field stack.
    That path imports ``dask`` for lazy field access.  The B0 MF6 runs also
    persist the total catchment discharge as a catalog time series, which is the
    same ``Q_total_release`` quantity used by the current truth package.  Use it
    only when the full field-stack path is unavailable.
    """

    try:
        return score_network_transient_candidate_from_runs(
            truth_dir,
            steady_run=steady_run,
            transient_run=transient_run,
        )
    except ModuleNotFoundError as exc:
        if exc.name != "dask":
            raise
    except Exception as exc:
        if "No module named 'dask'" not in str(exc):
            raise

    steady_drain = np.asarray(steady_run.field("outflow_drain", timestep=-1), dtype=float).reshape(
        -1
    )
    q_total_release = transient_run.timeseries("discharge", "_catchment").to_numpy(dtype=float)
    return score_network_transient_candidate(
        truth_dir,
        candidate_steady_drain_by_cell=steady_drain,
        candidate_q_total_release=q_total_release,
    )


def _catalog_for(path_value: str, cache: dict[Path, Catalog]) -> Catalog:
    path = Path(path_value).expanduser().resolve()
    if path not in cache:
        cache[path] = Catalog(path)
    return cache[path]


def _float_or_nan(value: str | None) -> float:
    if value is None or str(value).strip() == "":
        return math.nan
    return float(value)


def _empty_to_none(value: str | None) -> str | None:
    if value is None or str(value).strip() == "":
        return None
    return str(value).strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--truth-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "truth",
        help="B0 truth package directory.",
    )
    parser.add_argument(
        "--candidates-csv",
        type=Path,
        required=True,
        help="CSV table listing candidate steady/transient run references.",
    )
    parser.add_argument(
        "--output-csv",
        type=Path,
        default=Path(__file__).resolve().parent / "outputs" / "candidate_scores.csv",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=None,
        help="Optional JSON copy of the scored table.",
    )
    args = parser.parse_args(argv)

    specs = load_candidate_specs(args.candidates_csv)
    frame = score_candidate_specs(specs, truth_dir=args.truth_dir)

    args.output_csv.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(args.output_csv, index=False)
    if args.output_json is not None:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(
            json.dumps(frame.to_dict(orient="records"), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    completed = frame[frame["status"] == "completed"] if "status" in frame else frame.iloc[0:0]
    print(f"Wrote scores: {args.output_csv}")
    print(f"  candidates={len(frame)}")
    print(f"  completed={len(completed)}")
    if not completed.empty:
        best = completed.iloc[0]
        print(
            "  best="
            f"{best['candidate_id']} "
            f"J={float(best['objective']):.12g} "
            f"mK={float(best['mK']):.6g} "
            f"Sy={float(best['Sy']):.6g}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
