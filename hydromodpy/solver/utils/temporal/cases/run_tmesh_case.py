"""Run temporal-mesh demo scenarios from a TOML configuration."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# Support direct execution from file path and ensure local package precedence.
# Example: python hydromodpy/solver/utils/temporal/cases/run_tmesh_case.py
repo_root = Path(__file__).resolve().parents[5]
if (repo_root / "hydromodpy").exists() and str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

try:
    from hydromodpy.solver.utils.temporal.cases.run_tmesh_config import (
        load_tmesh_cases_toml,
    )
    from hydromodpy.solver.utils.temporal.tmesh_generation import TmeshGenerator
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
    TmeshGenerator = tmesh_module.TmeshGenerator
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


def _extract_datetime_vector(tmesh) -> list[pd.Timestamp]:
    datetimes_raw = getattr(tmesh, "datetimes", None)
    if datetimes_raw is not None:
        try:
            out = [pd.Timestamp(dt) for dt in datetimes_raw]
            if len(out) > 0:
                return out
        except Exception:
            pass

    start_datetime = getattr(tmesh, "start_datetime", None)
    if start_datetime is None:
        return []
    perlen = np.asarray(getattr(tmesh, "perlen", []), dtype=float)
    if perlen.size == 0:
        return []
    start = pd.Timestamp(start_datetime)
    cumulative_days = np.cumsum(perlen)
    return [start + pd.to_timedelta(float(days), unit="D") for days in cumulative_days]


def _extract_elapsed_vector(tmesh, *, n: int) -> np.ndarray:
    totim = getattr(tmesh, "totim", None)
    if totim is not None:
        try:
            arr = np.asarray(totim, dtype=float)
            if arr.size == n:
                return arr
        except Exception:
            pass
    return np.arange(1, n + 1, dtype=float)


def _plot_datetime_vector(
    tmesh,
    *,
    case_id: str,
    output_dirs: list[Path],
    show_plot: bool,
) -> tuple[Path | None, list[str]]:
    datetimes = _extract_datetime_vector(tmesh)
    datetime_vector = [dt.strftime("%Y-%m-%dT%H:%M:%S") for dt in datetimes]
    if len(datetimes) == 0:
        return None, datetime_vector

    elapsed = _extract_elapsed_vector(tmesh, n=len(datetimes))

    fig, ax = plt.subplots(1, 1, figsize=(8.2, 3.6), dpi=120)
    ax.plot(datetimes, elapsed, marker="o", markersize=3.5, linewidth=1.2, color="#1f77b4")
    ax.set_title(f"{case_id} | ModelTime datetime vector", fontsize=9)
    ax.set_xlabel("Datetime", fontsize=8)
    if getattr(tmesh, "totim", None) is not None:
        ax.set_ylabel("Elapsed model time", fontsize=8)
    else:
        ax.set_ylabel("Time-step index", fontsize=8)
    ax.grid(True, linestyle="--", linewidth=0.5, alpha=0.5)
    ax.tick_params(labelsize=7)
    fig.autofmt_xdate(rotation=35)
    fig.tight_layout()

    fig_path: Path | None = None
    for idx, output_dir in enumerate(output_dirs):
        output_dir.mkdir(parents=True, exist_ok=True)
        out = output_dir / f"{case_id}_modeltime_datetimes.png"
        fig.savefig(out, bbox_inches="tight")
        if idx == 0:
            fig_path = out

    if show_plot:
        plt.show(block=True)
    else:
        plt.close(fig)

    return fig_path, datetime_vector


def _summarize_modeltime(
    tmesh,
    *,
    case_id: str,
    description: str | None,
    datetime_vector: list[str],
    figure_path: Path | None,
) -> dict[str, Any]:
    perlen = np.asarray(tmesh.perlen, dtype=float)
    nstp = np.asarray(tmesh.nstp, dtype=int)
    tsmult = np.asarray(tmesh.tsmult, dtype=float)
    steady_state = np.asarray(tmesh.steady_state, dtype=bool)
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
        "datetime_vector": list(datetime_vector),
        "datetime_vector_size": int(len(datetime_vector)),
        "figure": None if figure_path is None else str(figure_path),
    }


def run_tmesh_cases_from_toml(
    config_toml: str | Path,
    *,
    section: str = "case",
    show_plot: bool = False,
) -> dict[str, dict[str, Any]]:
    """Run all configured temporal scenarios and return per-case summaries."""
    cfg = load_tmesh_cases_toml(config_toml, section=section)
    summaries: dict[str, dict[str, Any]] = {}
    config_parent = Path(config_toml).expanduser().resolve().parent
    output_dirs: list[Path] = []
    if cfg.output_figures_dir is not None:
        output_dirs.append(Path(cfg.output_figures_dir))
    compat_dir = config_parent / "output" / "figures"
    if compat_dir not in output_dirs:
        output_dirs.append(compat_dir)

    for scenario in cfg.scenarios:
        builder = TmeshGenerator(**scenario.to_builder_kwargs())
        tmesh = builder.run()
        figure_path, datetime_vector = _plot_datetime_vector(
            tmesh,
            case_id=scenario.id,
            output_dirs=output_dirs,
            show_plot=bool(show_plot),
        )
        summaries[scenario.id] = _summarize_modeltime(
            tmesh,
            case_id=scenario.id,
            description=scenario.description,
            datetime_vector=datetime_vector,
            figure_path=figure_path,
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
    parser.add_argument(
        "--no-show-plot",
        action="store_true",
        help="Disable interactive display of generated datetime-vector figures.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    summaries = run_tmesh_cases_from_toml(
        args.config,
        section=args.section,
        show_plot=(not bool(args.no_show_plot)),
    )

    for case_id, summary in summaries.items():
        print(f"[{case_id}] nper={summary['nper']}")
        print(f"[{case_id}] perlen_total_days={summary['perlen_total_days']:.6f}")
        print(f"[{case_id}] start_datetime={summary['start_datetime']}")
        print(f"[{case_id}] datetime_vector_size={summary['datetime_vector_size']}")
        print(f"[{case_id}] steady_state={summary['steady_state']}")
        print(f"[{case_id}] nstp={summary['nstp']}")
        print(f"[{case_id}] tsmult={summary['tsmult']}")
        print(f"[{case_id}] figure={summary['figure']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
