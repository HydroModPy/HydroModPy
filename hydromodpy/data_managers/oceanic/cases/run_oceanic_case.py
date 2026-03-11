"""Run a deterministic oceanic-only case from a TOML configuration."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
import sys
import time
import tomllib
from typing import Any

import pandas as pd

# Support direct execution from file path and ensure local package precedence.
repo_root = Path(__file__).resolve().parents[4]
if (repo_root / "hydromodpy").exists() and str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from hydromodpy.data_managers.oceanic.oceanic import Oceanic


@dataclass(slots=True)
class _GeographicStub:
    """Minimal geographic payload required by Oceanic fetch helpers."""

    centroid: tuple[float, float]
    centroid_long_lat: tuple[float, float]
    centroid_long_lat_Greenwich: tuple[float, float]
    stable_folder: str


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, ensure_ascii=True)
        stream.write("\n")


def _load_case_config(config_toml: Path) -> dict[str, Any]:
    with config_toml.open("rb") as stream:
        raw = tomllib.load(stream)

    case_raw = dict(raw.get("oceanic_case", {}))
    geo_raw = dict(raw.get("geographic", {}))

    source = str(case_raw.get("source", "local"))
    run_local_extraction = bool(case_raw.get("run_local_extraction", False))
    raw_display_values = case_raw.get("display_values", [])
    display_values: list[str] = []
    if isinstance(raw_display_values, str):
        text = raw_display_values.strip()
        if text:
            display_values = [text]
    elif isinstance(raw_display_values, list):
        display_values = [str(v).strip() for v in raw_display_values if str(v).strip()]
    oceanic_path_raw = case_raw.get("oceanic_path")
    oceanic_path = None
    if oceanic_path_raw is not None:
        oceanic_path = (config_toml.parent / str(oceanic_path_raw)).resolve()
    out_path_raw = case_raw.get("out_path")
    out_path = None
    if out_path_raw is not None:
        out_path = (config_toml.parent / str(out_path_raw)).resolve()

    local_csv = case_raw.get("local_csv_path")
    local_csv_path = None
    if local_csv is not None:
        local_csv_path = (config_toml.parent / str(local_csv)).resolve()

    centroid_vals = geo_raw.get("centroid_long_lat", [48.0, -4.0])
    if len(centroid_vals) != 2:
        raise ValueError("geographic.centroid_long_lat must contain exactly two values")

    centroid_xy_vals = geo_raw.get("centroid_xy_l93")
    centroid_xy = None
    if centroid_xy_vals is not None:
        if len(centroid_xy_vals) != 2:
            raise ValueError("geographic.centroid_xy_l93 must contain exactly two values")
        centroid_xy = (float(centroid_xy_vals[0]), float(centroid_xy_vals[1]))

    centroid_greenwich_vals = geo_raw.get("centroid_long_lat_greenwich")
    if centroid_greenwich_vals is None:
        centroid_greenwich = (float(centroid_vals[0]), float(centroid_vals[1]))
    else:
        if len(centroid_greenwich_vals) != 2:
            raise ValueError(
                "geographic.centroid_long_lat_greenwich must contain exactly two values"
            )
        centroid_greenwich = (
            float(centroid_greenwich_vals[0]),
            float(centroid_greenwich_vals[1]),
        )

    stable_folder = (config_toml.parent / str(geo_raw.get("stable_folder", "outputs/stable"))).resolve()
    if out_path is None:
        out_path = stable_folder.parent

    if run_local_extraction:
        if oceanic_path is None:
            raise ValueError(
                "oceanic_case.run_local_extraction=true requires oceanic_case.oceanic_path"
            )
        if centroid_xy is None:
            raise ValueError(
                "oceanic_case.run_local_extraction=true requires geographic.centroid_xy_l93"
            )

    geographic = _GeographicStub(
        centroid=(centroid_xy if centroid_xy is not None else (0.0, 0.0)),
        centroid_long_lat=(float(centroid_vals[0]), float(centroid_vals[1])),
        centroid_long_lat_Greenwich=centroid_greenwich,
        stable_folder=str(stable_folder),
    )

    return {
        "source": source,
        "run_local_extraction": run_local_extraction,
        "display_values": display_values,
        "oceanic_path": oceanic_path,
        "out_path": out_path,
        "local_csv_path": local_csv_path,
        "default_msl": float(case_raw.get("default_msl", 0.0)),
        "start_date": str(case_raw.get("start_date", "2003-01-01")),
        "end_date": str(case_raw.get("end_date", "2003-01-30")),
        "geographic": geographic,
    }


def run_oceanic_case_from_toml(
    config_toml: str | Path,
    *,
    output_json: str | Path | None = None,
) -> dict[str, Any]:
    """Run one oceanic case and return a compact deterministic signature.

    Two execution scopes are supported:
    - default: MSL fetch only (local/web/auto via ``fetch_msl_or_default``),
    - extended: run local extraction first (``extract_local_data``) to cover
      expensive oceanic preprocessing paths.
    """
    config_path = Path(config_toml).expanduser().resolve()
    cfg = _load_case_config(config_path)

    oceanic = Oceanic()
    extraction_seconds = None
    if cfg["run_local_extraction"]:
        extraction_start = time.perf_counter()
        oceanic.extract_local_data(
            out_path=str(cfg["out_path"]),
            geographic=cfg["geographic"],
            oceanic_path=str(cfg["oceanic_path"]),
        )
        extraction_seconds = time.perf_counter() - extraction_start
        for value in cfg["display_values"]:
            oceanic.display_data(value)

    fetch_start = time.perf_counter()
    returned_msl = oceanic.fetch_msl_or_default(
        geographic=cfg["geographic"],
        start_date=cfg["start_date"],
        end_date=cfg["end_date"],
        default=cfg["default_msl"],
        source=cfg["source"],
        local_csv_path=(str(cfg["local_csv_path"]) if cfg["local_csv_path"] is not None else None),
    )
    fetch_seconds = time.perf_counter() - fetch_start

    if not hasattr(oceanic, "SHOM_data") or oceanic.SHOM_data is None:
        raise ValueError("Oceanic case produced no SHOM_data payload")

    frame = oceanic.SHOM_data.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"])
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    frame = frame.dropna(subset=["timestamp", "value"]).sort_values("timestamp").reset_index(drop=True)
    if frame.empty:
        raise ValueError("Oceanic case produced an empty SHOM_data payload")

    summary = {
        "source": str(cfg["source"]),
        "local_csv_name": (
            str(Path(cfg["local_csv_path"]).name) if cfg["local_csv_path"] is not None else None
        ),
        "row_count": int(len(frame)),
        "first_timestamp": str(frame["timestamp"].iloc[0].strftime("%Y-%m-%d %H:%M:%S")),
        "last_timestamp": str(frame["timestamp"].iloc[-1].strftime("%Y-%m-%d %H:%M:%S")),
        "mean_msl_m": round(float(frame["value"].mean()), 12),
        "min_msl_m": round(float(frame["value"].min()), 12),
        "max_msl_m": round(float(frame["value"].max()), 12),
        "returned_msl_m": round(float(returned_msl), 12),
    }
    if cfg["run_local_extraction"]:
        rsl = getattr(oceanic, "RSL", None)
        summary.update(
            {
                "run_local_extraction": True,
                "oceanic_path_name": str(Path(cfg["oceanic_path"]).name),
                "local_extraction_seconds": round(float(extraction_seconds), 6),
                "fetch_msl_seconds": round(float(fetch_seconds), 6),
                "has_rsl_outputs": bool(isinstance(rsl, dict) and len(rsl) > 0),
            }
        )

    if output_json is not None:
        _write_json(Path(output_json).expanduser().resolve(), summary)

    return summary


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a deterministic oceanic case from TOML and print a summary."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).with_name("run_oceanic_config.toml"),
        help="Path to oceanic case TOML configuration.",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=None,
        help="Optional path to persist the summary JSON payload.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    summary = run_oceanic_case_from_toml(args.config, output_json=args.output_json)
    print(json.dumps(summary, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
