"""Run a deterministic oceanic-only case from a TOML configuration.

Run with:
    python -m hydromodpy.data.variables.oceanic.cases.run_oceanic_case

The ``web`` mode names its tide gauge with ``station_id`` rather than handing
over a centroid to search from. That is what a deterministic case wants: which
gauge is read is the thing being pinned, not something re-derived on every run
from a point the TOML happened to carry.

``cache_dir`` has **no default**. A ``DataStore`` handed a ``data_root``
creates the directory and opens a DuckDB catalog with a lock file in it, and
this module sits inside the installed package: the committed configuration
leaves it unset so running the case writes nothing where the source lives.
"""

from __future__ import annotations

import argparse
import json
import time
import tomllib
from pathlib import Path
from typing import Any

import pandas as pd

from hydromodpy.data.loading.store import DataStore
from hydromodpy.data.variables.oceanic.config import OceanicConfig, OceanicSourceConfig


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, ensure_ascii=True)
        stream.write("\n")


def _load_case_config(config_toml: Path) -> dict[str, Any]:
    with config_toml.open("rb") as stream:
        raw = tomllib.load(stream)

    case_raw = dict(raw.get("oceanic_case", {}))

    source = str(case_raw.get("source", "local"))
    local_csv = case_raw.get("local_csv_path")
    local_csv_path = None
    if local_csv is not None:
        local_csv_path = (config_toml.parent / str(local_csv)).resolve()

    # No default: giving DataStore a data_root makes it create the directory and
    # open a DuckDB catalog there, and this module ships inside the package tree.
    raw_cache_dir = case_raw.get("cache_dir")
    cache_dir = None
    if raw_cache_dir is not None:
        cache_dir = (config_toml.parent / str(raw_cache_dir)).resolve()

    return {
        "source": source,
        "local_csv_path": local_csv_path,
        "station_id": str(case_raw.get("station_id", "152")),
        "cache_dir": cache_dir,
        "default_msl": float(case_raw.get("default_msl", 0.0)),
        "start_date": str(case_raw.get("start_date", "2003-01-01")),
        "end_date": str(case_raw.get("end_date", "2003-01-30")),
    }


def run_oceanic_case_from_toml(
    config_toml: str | Path,
    *,
    output_json: str | Path | None = None,
) -> dict[str, Any]:
    """Run one oceanic case and return a compact deterministic signature."""
    config_path = Path(config_toml).expanduser().resolve()
    cfg = _load_case_config(config_path)

    source_mode = cfg["source"]
    from datetime import datetime as dt

    start = dt.fromisoformat(cfg["start_date"])
    end = dt.fromisoformat(cfg["end_date"])

    if source_mode == "local" and cfg["local_csv_path"] is not None:
        csv_path = Path(cfg["local_csv_path"])
        source_cfg = OceanicSourceConfig(
            source="custom",
            path=csv_path.parent,
            col_datetime="timestamp",
        )
    elif source_mode == "web":
        source_cfg = OceanicSourceConfig(source="shom", station_ids=[cfg["station_id"]])
    elif source_mode == "auto":
        if cfg["local_csv_path"] is not None and Path(cfg["local_csv_path"]).exists():
            csv_path = Path(cfg["local_csv_path"])
            source_cfg = OceanicSourceConfig(
                source="custom",
                path=csv_path.parent,
                col_datetime="timestamp",
            )
        else:
            source_cfg = OceanicSourceConfig(source="shom", station_ids=[cfg["station_id"]])
    else:
        source_cfg = OceanicSourceConfig(source="shom", station_ids=[cfg["station_id"]])

    oceanic_cfg = OceanicConfig(
        sources=[source_cfg],
        date_start=cfg["start_date"],
        date_end=cfg["end_date"],
    )

    fetch_start = time.perf_counter()
    store = DataStore(
        data_root=cfg["cache_dir"],
        project_period=(start, end),
    )
    load_result = store.load_oceanic(oceanic_cfg)
    fetch_seconds = time.perf_counter() - fetch_start

    sea_records = [r for r in load_result.points if r.variable in ("sea_level", "oceanic")]
    if not sea_records:
        msl_records = [r for r in load_result.points if r.variable == "mean_sea_level"]
        if not msl_records:
            raise ValueError("Oceanic case produced no data records")
        rec = msl_records[0]
        frame = rec.data.copy()
        frame["timestamp"] = frame["datetime"]
    else:
        rec = sea_records[0]
        frame = rec.data.copy()
        frame["timestamp"] = frame["datetime"]

    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    frame = (
        frame.dropna(subset=["timestamp", "value"]).sort_values("timestamp").reset_index(drop=True)
    )
    if frame.empty:
        raise ValueError("Oceanic case produced an empty data payload")

    returned_msl = float(frame["value"].mean())
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
        "fetch_seconds": round(float(fetch_seconds), 6),
    }

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
