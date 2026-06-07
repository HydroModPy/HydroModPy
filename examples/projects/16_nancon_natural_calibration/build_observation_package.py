"""Build the Nancon natural observation package from prepared observations."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hydromodpy.calibration.natural_observations import (  # noqa: E402
    write_natural_observation_package,
)

SCRIPT_DIR = Path(__file__).resolve().parent
GAUGED_CONTEXT = REPO_ROOT / "examples" / "projects" / "15_nancon_gauged_context"
DEFAULT_OBSERVED_Q = GAUGED_CONTEXT / "outputs" / "context" / "observed_discharge_daily.csv"
DEFAULT_OUTPUT_DIR = SCRIPT_DIR / "outputs" / "natural_observation_package"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observed-discharge-csv", type=Path, default=DEFAULT_OBSERVED_Q)
    parser.add_argument("--network-mask-npz", type=Path, required=True)
    parser.add_argument("--network-distance-npz", type=Path, required=True)
    parser.add_argument("--geometry-npz", type=Path, required=True)
    parser.add_argument("--mesh-bundle", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--start", default="2000-01-01")
    parser.add_argument("--end", default="2002-12-31")
    parser.add_argument("--freq", default="ME", help="Pandas resampling frequency.")
    parser.add_argument("--warmup-periods", type=int, default=0)
    parser.add_argument("--scored-periods", type=int, default=None)
    args = parser.parse_args(argv)

    observed = _monthly_observed_discharge(
        args.observed_discharge_csv,
        start=args.start,
        end=args.end,
        freq=args.freq,
    )
    mask = _load_mask(args.network_mask_npz)
    distance = _load_distance(args.network_distance_npz)
    centroids, cell_area = _load_geometry(args.geometry_npz)

    metadata: dict[str, Any] = {
        "site_id": "nancon",
        "observed_discharge_csv": str(args.observed_discharge_csv.resolve()),
        "observed_network_mask_npz": str(args.network_mask_npz.resolve()),
        "observed_network_distance_npz": str(args.network_distance_npz.resolve()),
        "geometry_npz": str(args.geometry_npz.resolve()),
        "discharge_resample_frequency": args.freq,
        "discharge_window_start": args.start,
        "discharge_window_end": args.end,
    }
    if args.mesh_bundle is not None:
        metadata["mesh_bundle"] = str(args.mesh_bundle.resolve())

    summary = write_natural_observation_package(
        args.output_dir,
        observed_q_total_release=observed["q_total_release"].to_numpy(dtype=float),
        observed_network_mask=mask,
        observed_network_distance_by_cell=distance,
        centroids=centroids,
        cell_area=cell_area,
        time_index=pd.DatetimeIndex(observed["datetime"]),
        metadata=metadata,
        warmup_periods=args.warmup_periods,
        scored_periods=args.scored_periods,
    )
    print(summary.output_dir)
    return 0


def _monthly_observed_discharge(
    path: Path,
    *,
    start: str,
    end: str,
    freq: str,
) -> pd.DataFrame:
    frame = pd.read_csv(path)
    frame["datetime"] = pd.to_datetime(frame["datetime"], errors="coerce")
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    frame = frame.dropna(subset=["datetime", "value"])
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    frame = frame[(frame["datetime"] >= start_ts) & (frame["datetime"] <= end_ts)]
    if frame.empty:
        raise ValueError(f"No observed discharge values in [{start}, {end}] from {path}")
    series = frame.set_index("datetime")["value"].sort_index().resample(freq).mean()
    series = series.dropna()
    if series.empty:
        raise ValueError(f"Resampling observed discharge with freq={freq!r} produced no value.")
    return pd.DataFrame({"datetime": series.index, "q_total_release": series.to_numpy()})


def _load_mask(path: Path) -> np.ndarray:
    with np.load(path) as data:
        for key in ("active_mask", "observed_network_mask", "network_mask"):
            if key in data:
                return np.asarray(data[key], dtype=bool).reshape(-1)
    raise ValueError(f"{path} must contain active_mask, observed_network_mask or network_mask.")


def _load_distance(path: Path) -> np.ndarray:
    with np.load(path) as data:
        for key in ("distance_to_network", "observed_network_distance", "distance"):
            if key in data:
                return np.asarray(data[key], dtype=float).reshape(-1)
    raise ValueError(
        f"{path} must contain distance_to_network, observed_network_distance or distance."
    )


def _load_geometry(path: Path) -> tuple[np.ndarray, np.ndarray]:
    with np.load(path) as data:
        centroids = np.asarray(data["centroids"], dtype=float)
        cell_area = np.asarray(data["cell_area"], dtype=float).reshape(-1)
    return centroids, cell_area


if __name__ == "__main__":
    raise SystemExit(main())
