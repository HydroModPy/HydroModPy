"""Run a deterministic intermittency-only case from a TOML configuration."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tomllib
from typing import Any

repo_root = Path(__file__).resolve().parents[5]
if (repo_root / "hydromodpy").exists() and str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from hydromodpy.data.variables.intermittency.config import (
    IntermittencyConfig,
    IntermittencySourceConfig,
)
from hydromodpy.data.variables.intermittency.manager import IntermittencyManager


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, ensure_ascii=True)
        stream.write("\n")


def _load_case_config(config_toml: Path) -> dict[str, Any]:
    with config_toml.open("rb") as stream:
        raw = tomllib.load(stream)

    case_raw = dict(raw.get("intermittency_case", {}))
    source = str(case_raw.get("source", "custom"))
    data_path_raw = case_raw.get("data_path", "data")
    data_path = (config_toml.parent / str(data_path_raw)).resolve()

    return {
        "source": source,
        "data_path": data_path,
        "date_start": str(case_raw.get("date_start", "2018-01-01")),
        "date_end": str(case_raw.get("date_end", "2023-12-31")),
        "station_ids": case_raw.get("station_ids"),
        "code_departement": case_raw.get("code_departement"),
    }


def run_intermittency_case_from_toml(
    config_toml: str | Path,
    *,
    output_json: str | Path | None = None,
) -> dict[str, Any]:
    """Run one intermittency case and return a compact deterministic summary."""
    config_path = Path(config_toml).expanduser().resolve()
    cfg = _load_case_config(config_path)

    from datetime import datetime as dt

    start = dt.fromisoformat(cfg["date_start"])
    end = dt.fromisoformat(cfg["date_end"])

    if cfg["source"] == "custom":
        source_cfg = IntermittencySourceConfig(
            source="custom",
            path=cfg["data_path"],
        )
    else:
        source_cfg = IntermittencySourceConfig(
            source="hubeau",
            station_ids=cfg.get("station_ids"),
            code_departement=cfg.get("code_departement"),
        )

    intermittency_cfg = IntermittencyConfig(
        sources=[source_cfg],
        date_start=cfg["date_start"],
        date_end=cfg["date_end"],
    )

    manager = IntermittencyManager(
        config=intermittency_cfg,
        catalog=None,
        project_period=(start, end),
    )
    load_result = manager.load()

    station_ids = sorted({r.station_id for r in load_result.points})
    total_obs = sum(len(r.data) for r in load_result.points)

    flow_code_hist: dict[int, int] = {}
    date_min = None
    date_max = None
    for rec in load_result.points:
        for code in rec.data["value"]:
            code_int = int(code)
            flow_code_hist[code_int] = flow_code_hist.get(code_int, 0) + 1
        if not rec.data.empty:
            rec_min = rec.data["datetime"].min()
            rec_max = rec.data["datetime"].max()
            if date_min is None or rec_min < date_min:
                date_min = rec_min
            if date_max is None or rec_max > date_max:
                date_max = rec_max

    summary: dict[str, Any] = {
        "source": cfg["source"],
        "station_count": len(station_ids),
        "station_ids": station_ids,
        "total_observations": total_obs,
        "date_start": date_min.strftime("%Y-%m-%d") if date_min is not None else None,
        "date_end": date_max.strftime("%Y-%m-%d") if date_max is not None else None,
        "flow_code_hist": dict(sorted(flow_code_hist.items())),
    }

    if output_json is not None:
        _write_json(Path(output_json).expanduser().resolve(), summary)

    return summary


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a deterministic intermittency case from TOML and print a summary."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).with_name("run_intermittency_config.toml"),
        help="Path to intermittency case TOML configuration.",
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
    summary = run_intermittency_case_from_toml(args.config, output_json=args.output_json)
    print(json.dumps(summary, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
