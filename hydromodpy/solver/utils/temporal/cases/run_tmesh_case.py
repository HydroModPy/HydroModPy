"""Run temporal-mesh demo scenarios from a TOML configuration."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any

import numpy as np

# Support direct execution from file path and ensure local package precedence.
# Example: python hydromodpy/solver/utils/temporal/cases/run_tmesh_case.py
repo_root = Path(__file__).resolve().parents[5]
if (repo_root / "hydromodpy").exists() and str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

try:
    from hydromodpy.solver.utils.temporal.tmesh_generation import TMesh_Generation
    from hydromodpy.solver.utils.temporal.cases.run_tmesh_config import (
        load_tmesh_cases_toml,
    )
except Exception:
    temporal_root = Path(__file__).resolve().parents[1]
    cases_root = Path(__file__).resolve().parent

    def _load_module(module_name: str, module_path: Path):
        spec = importlib.util.spec_from_file_location(module_name, module_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load module from {module_path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module

    tmesh_module = _load_module(
        "_local_tmesh_generation",
        temporal_root / "tmesh_generation.py",
    )
    cfg_module = _load_module(
        "_local_tmesh_case_config",
        cases_root / "run_tmesh_config.py",
    )
    TMesh_Generation = tmesh_module.TMesh_Generation
    load_tmesh_cases_toml = cfg_module.load_tmesh_cases_toml


def _as_serializable(value: Any):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, (list, tuple)):
        return [_as_serializable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _as_serializable(v) for k, v in value.items()}
    return value


def _summarize_modeltime(tmesh, *, case_id: str, description: str | None) -> dict[str, Any]:
    perlen = np.asarray(getattr(tmesh, "perlen"), dtype=float)
    nstp = np.asarray(getattr(tmesh, "nstp"), dtype=int)
    tsmult = np.asarray(getattr(tmesh, "tsmult"), dtype=float)
    steady_state = np.asarray(getattr(tmesh, "steady_state"), dtype=bool)
    start_datetime = getattr(tmesh, "start_datetime", None)

    return {
        "case_id": str(case_id),
        "description": description,
        "start_datetime": None if start_datetime is None else str(start_datetime),
        "nper": int(len(perlen)),
        "perlen_days": perlen.tolist(),
        "perlen_total_days": float(np.sum(perlen)),
        "nstp": nstp.tolist(),
        "tsmult": tsmult.tolist(),
        "steady_state": steady_state.tolist(),
    }


def run_tmesh_cases_from_toml(
    config_toml: str | Path,
    *,
    section: str = "case",
) -> dict[str, dict[str, Any]]:
    """Run all configured temporal scenarios and return per-case summaries."""
    cfg = load_tmesh_cases_toml(config_toml, section=section)
    summaries: dict[str, dict[str, Any]] = {}

    for scenario in cfg.scenarios:
        builder = TMesh_Generation(**scenario.to_builder_kwargs())
        tmesh = builder.run()
        summaries[scenario.id] = _summarize_modeltime(
            tmesh,
            case_id=scenario.id,
            description=scenario.description,
        )

    if cfg.output_summary_json is not None:
        cfg.output_summary_json.parent.mkdir(parents=True, exist_ok=True)
        payload = {case_id: _as_serializable(data) for case_id, data in summaries.items()}
        cfg.output_summary_json.write_text(
            json.dumps(payload, indent=2),
            encoding="utf-8",
        )

    return summaries


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run temporal-mesh demo scenarios from one TOML file and print per-case summaries."
        )
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).with_name("run_tmesh_config.toml"),
        help="Path to temporal-mesh case TOML.",
    )
    parser.add_argument(
        "--section",
        type=str,
        default="case",
        help="TOML section to load (default: case).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    summaries = run_tmesh_cases_from_toml(args.config, section=args.section)

    for case_id, summary in summaries.items():
        print(f"[{case_id}] nper={summary['nper']}")
        print(f"[{case_id}] perlen_total_days={summary['perlen_total_days']:.6f}")
        print(f"[{case_id}] start_datetime={summary['start_datetime']}")
        print(f"[{case_id}] steady_state={summary['steady_state']}")
        print(f"[{case_id}] nstp={summary['nstp']}")
        print(f"[{case_id}] tsmult={summary['tsmult']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
