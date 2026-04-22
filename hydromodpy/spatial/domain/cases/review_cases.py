"""Sequential launcher for all domain/cases TOML configurations.

This script runs every discovered domain-case config one after another and,
by default, keeps figures in blocking mode so each window must be closed
before moving to the next case.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Any

# Ensure repository root is importable when script is launched directly.
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hydromodpy.spatial.domain.cases.run_domain_case import (
    plot_domain_summary,
    run_domain_case_from_toml,
)


CASES_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = CASES_DIR / "outputs" / "review_cases"


@dataclass(frozen=True, slots=True)
class CaseReviewSpec:
    """Describe one domain-case configuration available for visual review."""

    name: str
    description: str
    config_path: Path


def _case_name_from_config_path(config_path: Path) -> str:
    stem = config_path.stem
    if stem.endswith("_config"):
        return stem[: -len("_config")]
    return stem


def _discover_case_review_specs() -> tuple[CaseReviewSpec, ...]:
    specs: list[CaseReviewSpec] = []
    for config_path in sorted(CASES_DIR.glob("*config*.toml")):
        specs.append(
            CaseReviewSpec(
                name=_case_name_from_config_path(config_path),
                description=f"Domain case from {config_path.name}",
                config_path=config_path.resolve(),
            )
        )
    return tuple(specs)


CASE_REVIEW_SPECS: tuple[CaseReviewSpec, ...] = _discover_case_review_specs()


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Run all domain/cases configurations sequentially with blocking "
            "figure display for manual review."
        )
    )
    parser.add_argument(
        "--case",
        dest="case_names",
        action="append",
        default=None,
        help=(
            "Restrict the review to one named case. Repeat the option to keep "
            "multiple cases; execution order stays the built-in review order."
        ),
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help=(
            "Output directory for review figures (default: "
            "hydromodpy/spatial/domain/cases/outputs/review_cases)."
        ),
    )
    parser.add_argument(
        "--no-build-geology",
        action="store_true",
        help="Skip optional geology zone build even if declared in domain.zone_ids.",
    )
    parser.add_argument(
        "--no-show-plot",
        action="store_true",
        help="Do not display figures interactively (still saves PNG files).",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List the available review cases and exit.",
    )
    return parser.parse_args(argv)


def available_case_review_names() -> tuple[str, ...]:
    return tuple(spec.name for spec in CASE_REVIEW_SPECS)


def resolve_case_review_specs(
    case_names: Sequence[str] | None = None,
) -> tuple[CaseReviewSpec, ...]:
    if not case_names:
        return CASE_REVIEW_SPECS

    requested = {str(name).strip() for name in case_names if str(name).strip()}
    available = available_case_review_names()
    unknown = sorted(requested.difference(available))
    if unknown:
        raise ValueError(
            "Unknown domain/cases review case(s): "
            + ", ".join(repr(name) for name in unknown)
            + ". Available cases: "
            + ", ".join(available)
        )
    return tuple(spec for spec in CASE_REVIEW_SPECS if spec.name in requested)


def list_case_reviews(*, printer: Callable[[str], None] = print) -> None:
    if not CASE_REVIEW_SPECS:
        printer("No domain/cases configuration files found.")
        return
    for spec in CASE_REVIEW_SPECS:
        printer(f"{spec.name}: {spec.description}")


def run_case_reviews(
    case_names: Sequence[str] | None = None,
    *,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    build_geology: bool = True,
    show_plot: bool = True,
    printer: Callable[[str], None] = print,
) -> dict[str, dict[str, Any]]:
    selected_specs = resolve_case_review_specs(case_names)
    if not selected_specs:
        raise ValueError(
            "No domain/cases configuration files were discovered. "
            "Expected at least one '*config*.toml' in "
            f"{CASES_DIR}."
        )

    out_dir = Path(output_dir).expanduser()
    if not out_dir.is_absolute():
        out_dir = (CASES_DIR / out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    summaries_by_case: dict[str, dict[str, Any]] = {}
    total = len(selected_specs)
    for index, spec in enumerate(selected_specs, start=1):
        printer(f"[{index}/{total}] Running {spec.name}")
        printer(f"  {spec.description}")
        if show_plot:
            printer("  Close the figure window to continue to the next case.")

        workspace, geographic_context, domain, summary = run_domain_case_from_toml(
            spec.config_path,
            build_geology=build_geology,
        )
        fig_path = plot_domain_summary(
            domain,
            output_dir=out_dir,
            geographic=geographic_context,
            catchment_zone_codes_tif=summary.get("catchment_zone_codes_tif"),
            case_id=spec.name,
            show_plot=show_plot,
        )

        result = {
            "config": str(spec.config_path),
            "project_root": str(workspace.project_root),
            "watershed_shp": str(summary["watershed_shp"]),
            "catchment_area_km2": float(summary["catchment_area_km2"]),
            "surface_topo_shape": tuple(int(v) for v in summary["surface_topo_shape"]),
            "substratum_shape": tuple(int(v) for v in summary["substratum_shape"]),
            "depth_model_type": str(summary["depth_model_type"]),
            "geology_loaded": bool(summary["geology_loaded"]),
            "catchment_zone_loaded": bool(summary["catchment_zone_loaded"]),
            "figure": str(fig_path),
        }
        summaries_by_case[spec.name] = result
        printer(f"[{index}/{total}] figure={fig_path}")
        printer(f"[{index}/{total}] Completed {spec.name}")

    return summaries_by_case


def main(argv=None) -> int:
    args = _parse_args(argv)
    if args.list:
        list_case_reviews()
        return 0

    run_case_reviews(
        case_names=args.case_names,
        output_dir=args.output_dir,
        build_geology=(not bool(args.no_build_geology)),
        show_plot=(not bool(args.no_show_plot)),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
