"""Generic CLI entry-point for HydroModPy launcher families.

Usage::

    hmp simulation path/to/config.toml          # recommended
    python -m launchers simulation path/to/config.toml   # equivalent
    python -m launchers mesh-catchment run path/to/config.toml
    python -m launchers method-comparison run path/to/config.toml
    python -m launchers regional-lab run path/to/config.toml
    python -m launchers regional-lab bootstrap-catalog --help

Notes
-----
The canonical CLI is ``hmp simulation`` (defined in ``hydromodpy/__main__.py``).
``python -m launchers`` is kept as an equivalent alternative.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any


def _run_simulation_launcher(config_path: Path) -> None:
    """Execute the simulation launcher for one TOML configuration path."""
    from launchers import HydroModPyLauncher

    HydroModPyLauncher(config_path).run()


def _collect_mesh_catchment_figures(summary: Any) -> list[str]:
    """Extract created figure paths from one mesh-catchment launcher summary."""
    if not isinstance(summary, dict):
        return []

    def _extend_from_payload(payload: dict[str, Any], out: list[str]) -> None:
        for key in ("output_figure", "output_figure_regional"):
            figure_path = str(payload.get(key, "")).strip()
            if figure_path != "":
                out.append(figure_path)

    mode = str(summary.get("mode", "")).strip().lower()
    if mode == "batch":
        figures: list[str] = []
        for row in summary.get("results", ()):
            if not isinstance(row, dict):
                continue
            _extend_from_payload(row, figures)
        return figures

    figures: list[str] = []
    _extend_from_payload(summary, figures)
    return figures


def _print_mesh_catchment_figures(summary: Any) -> None:
    """Print created figure paths at the end of one mesh-catchment CLI run."""
    figures = _collect_mesh_catchment_figures(summary)
    if not figures:
        return
    print("Created figures:")
    for figure_path in figures:
        print(f"  {figure_path}")


def _run_mesh_catchment_launcher(config_path: Path) -> None:
    """Execute the mesh-catchment launcher for one TOML configuration path."""
    from launchers import MeshCatchmentLauncher

    summary = MeshCatchmentLauncher(config_path).run()
    _print_mesh_catchment_figures(summary)


def _render_mesh_catchment_template(
    *,
    batch: bool,
    profile: str,
    output_path: Path | None,
) -> None:
    """Render one canonical mesh-catchment TOML template."""
    from launchers.mesh_catchment.templates import (
        render_mesh_catchment_template,
        write_mesh_catchment_template,
    )

    if output_path is None:
        sys.stdout.write(
            render_mesh_catchment_template(batch=batch, profile=profile)
        )
        return

    write_mesh_catchment_template(
        output_path=output_path,
        batch=batch,
        profile=profile,
    )
    print(f"Wrote template: {output_path}")


def _run_data_overview_launcher(config_path: Path) -> None:
    """Execute the data-overview launcher for one TOML configuration path."""
    from launchers import DataOverviewLauncher

    summary = DataOverviewLauncher(config_path).run()
    report_paths = summary.get("report_paths", [])
    if report_paths:
        print("Generated overview panels:")
        for p in report_paths:
            print(f"  {p}")


def _run_model_calibration_launcher(config_path: Path) -> None:
    """Execute the model-calibration launcher for one TOML configuration path."""
    from launchers import ModelCalibrationLauncher

    summary = ModelCalibrationLauncher(config_path).calibrate()
    print("Completed model-calibration run:")
    print(f"  calibration_id: {summary['calibration_id']}")
    print(f"  simulation_config: {summary['simulation_config']}")
    print(f"  primary_solver: {summary['primary_solver']}")
    print(f"  calibration_root: {summary['calibration_root']}")
    print(f"  cost_best: {summary['cost_best']}")


def _run_method_comparison_launcher(config_path: Path) -> None:
    """Execute the method-comparison launcher for one TOML configuration path."""
    from launchers import MethodComparisonLauncher

    summary = MethodComparisonLauncher(config_path).run()
    print("Completed method-comparison run:")
    print(f"  comparison_id: {summary['comparison_id']}")
    print(f"  comparison_root: {summary['comparison_root']}")
    print(f"  observables_csv: {summary['observables_csv']}")
    print(f"  comparison_metrics_csv: {summary['comparison_metrics_csv']}")
    print(f"  comparison_report_md: {summary['comparison_report_md']}")
    print(f"  manifest_path: {summary['manifest_path']}")


def _run_regional_lab_launcher(config_path: Path) -> None:
    """Execute the regional-lab launcher for one TOML configuration path."""
    from launchers import RegionalLabLauncher

    summary = RegionalLabLauncher(config_path).run()
    print("Completed regional-lab run:")
    print(f"  lab_id: {summary['lab_id']}")
    print(f"  output_root: {summary['output_root']}")
    print(f"  selected_site_count: {summary['selected_site_count']}")
    print(f"  planned_case_count: {summary['planned_case_count']}")
    print(f"  skipped_case_count: {summary['skipped_case_count']}")
    print(f"  executed_case_count: {summary['executed_case_count']}")
    print(f"  reused_case_count: {summary['reused_case_count']}")
    print(f"  failed_case_count: {summary['failed_case_count']}")
    print(f"  plan_path: {summary['plan_path']}")
    print(f"  report_path: {summary['report_path']}")
    print(f"  site_inventory_csv: {summary['site_inventory_csv']}")
    print(f"  recipe_summary_csv: {summary['recipe_summary_csv']}")
    print(f"  cluster_summary_csv: {summary['cluster_summary_csv']}")
    print(f"  summary_markdown: {summary['summary_markdown']}")
    if int(summary["failed_case_count"]) > 0:
        raise RuntimeError("regional-lab run completed with failed child cases")


def _bootstrap_regional_lab_catalog(
    *,
    outlets_table: Path,
    output: Path,
    cluster_id: str,
    region_id: str,
    source_selection_id: str,
    cluster_label: str | None,
    cluster_family: str | None,
    cluster_scale: str | None,
    manifest_csv: Path | None,
    site_id_template: str,
    outlet_id_column: str,
    x_column: str,
    y_column: str,
    area_column: str,
    tags: list[str],
) -> None:
    """Build one canonical regional-lab site catalog from one outlets table."""
    from launchers.regional_lab.bootstrap import build_site_catalog_from_outlet_table

    summary = build_site_catalog_from_outlet_table(
        outlets_table_path=outlets_table,
        output_path=output,
        cluster_id=cluster_id,
        region_id=region_id,
        source_selection_id=source_selection_id,
        cluster_label=cluster_label,
        cluster_family=cluster_family,
        cluster_scale=cluster_scale,
        manifest_csv=manifest_csv,
        site_id_template=site_id_template,
        outlet_id_column=outlet_id_column,
        x_column=x_column,
        y_column=y_column,
        area_column=area_column,
        default_tags=tuple(tags),
    )
    print("Bootstrapped regional-lab site catalog:")
    print(f"  output_path: {summary['output_path']}")
    print(f"  site_count: {summary['site_count']}")
    print(f"  cluster_id: {summary['cluster_id']}")
    print(f"  region_id: {summary['region_id']}")
    print(f"  source_selection_id: {summary['source_selection_id']}")
    print(f"  manifest_merged: {summary['manifest_merged']}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m launchers",
        description="HydroModPy launchers CLI.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    sim_parser = subparsers.add_parser(
        "simulation",
        help="Run a simulation from a TOML configuration file.",
    )
    sim_parser.add_argument(
        "config",
        type=Path,
        help="Path to the simulation TOML file.",
    )

    mesh_parser = subparsers.add_parser(
        "mesh-catchment",
        help="Mesh-catchment launcher family.",
    )
    mesh_commands = mesh_parser.add_subparsers(dest="mesh_command", required=True)
    mesh_run = mesh_commands.add_parser(
        "run",
        help="Run one mesh-catchment launcher TOML.",
    )
    mesh_run.add_argument(
        "config",
        type=Path,
        help="Path to launcher TOML file.",
    )
    mesh_run.set_defaults(_handler="mesh_catchment_run")
    mesh_template = mesh_commands.add_parser(
        "template",
        help="Render a canonical TOML template derived from Pydantic schemas.",
    )
    mesh_template.add_argument(
        "--batch",
        action="store_true",
        help="Include the optional [mesh_catchment_batch] section.",
    )
    mesh_template.add_argument(
        "--profile",
        choices=("user", "dev", "expert"),
        default="user",
        help="Visibility profile forwarded to the generic TOML generator.",
    )
    mesh_template.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional output path. When omitted, print the template to stdout.",
    )
    mesh_template.set_defaults(_handler="mesh_catchment_template")

    # -- data-overview family ------------------------------------------------
    overview_parser = subparsers.add_parser(
        "data-overview",
        help="Data-overview launcher family (watershed identity card).",
    )
    overview_commands = overview_parser.add_subparsers(
        dest="overview_command", required=True,
    )
    overview_run = overview_commands.add_parser(
        "run",
        help="Run a data-overview launcher TOML.",
    )
    overview_run.add_argument(
        "config",
        type=Path,
        help="Path to launcher TOML file.",
    )
    overview_run.set_defaults(_handler="data_overview_run")

    overview_template = overview_commands.add_parser(
        "template",
        help="Print a canonical TOML template for data-overview.",
    )
    overview_template.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional output path. When omitted, print the template to stdout.",
    )
    overview_template.set_defaults(_handler="data_overview_template")

    calibration_parser = subparsers.add_parser(
        "model-calibration",
        help="Model-calibration launcher family.",
    )
    calibration_commands = calibration_parser.add_subparsers(
        dest="calibration_command",
        required=True,
    )
    calibration_run = calibration_commands.add_parser(
        "run",
        help="Run a model-calibration launcher TOML.",
    )
    calibration_run.add_argument(
        "config",
        type=Path,
        help="Path to launcher TOML file.",
    )
    calibration_run.set_defaults(_handler="model_calibration_run")

    calibration_template = calibration_commands.add_parser(
        "template",
        help="Print a canonical TOML template for model-calibration.",
    )
    calibration_template.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional output path. When omitted, print the template to stdout.",
    )
    calibration_template.set_defaults(_handler="model_calibration_template")

    comparison_parser = subparsers.add_parser(
        "method-comparison",
        help="Method-comparison launcher family.",
    )
    comparison_commands = comparison_parser.add_subparsers(
        dest="comparison_command",
        required=True,
    )
    comparison_run = comparison_commands.add_parser(
        "run",
        help="Run a method-comparison launcher TOML.",
    )
    comparison_run.add_argument(
        "config",
        type=Path,
        help="Path to launcher TOML file.",
    )
    comparison_run.set_defaults(_handler="method_comparison_run")

    comparison_template = comparison_commands.add_parser(
        "template",
        help="Print a canonical TOML template for method-comparison.",
    )
    comparison_template.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional output path. When omitted, print the template to stdout.",
    )
    comparison_template.set_defaults(_handler="method_comparison_template")

    regional_lab_parser = subparsers.add_parser(
        "regional-lab",
        help="Regional-lab launcher family.",
    )
    regional_lab_commands = regional_lab_parser.add_subparsers(
        dest="regional_lab_command",
        required=True,
    )
    regional_lab_run = regional_lab_commands.add_parser(
        "run",
        help="Run a regional-lab launcher TOML.",
    )
    regional_lab_run.add_argument(
        "config",
        type=Path,
        help="Path to launcher TOML file.",
    )
    regional_lab_run.set_defaults(_handler="regional_lab_run")

    regional_lab_template = regional_lab_commands.add_parser(
        "template",
        help="Print a canonical TOML template for regional-lab.",
    )
    regional_lab_template.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional output path. When omitted, print the template to stdout.",
    )
    regional_lab_template.set_defaults(_handler="regional_lab_template")
    regional_lab_bootstrap = regional_lab_commands.add_parser(
        "bootstrap-catalog",
        help="Build a canonical regional-lab site catalog from an outlets table.",
    )
    regional_lab_bootstrap.add_argument(
        "--outlets-table",
        type=Path,
        required=True,
        help="Path to the source outlets CSV table.",
    )
    regional_lab_bootstrap.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Destination CSV path for the generated site catalog.",
    )
    regional_lab_bootstrap.add_argument(
        "--cluster-id",
        required=True,
        help="Cluster identifier assigned to generated sites.",
    )
    regional_lab_bootstrap.add_argument(
        "--region-id",
        required=True,
        help="Region identifier assigned to generated sites.",
    )
    regional_lab_bootstrap.add_argument(
        "--source-selection-id",
        required=True,
        help="Source selection identifier kept in the generated catalog.",
    )
    regional_lab_bootstrap.add_argument(
        "--cluster-label",
        default=None,
        help="Optional human-readable cluster label.",
    )
    regional_lab_bootstrap.add_argument(
        "--cluster-family",
        default=None,
        help="Optional cluster family.",
    )
    regional_lab_bootstrap.add_argument(
        "--cluster-scale",
        default=None,
        help="Optional cluster scale.",
    )
    regional_lab_bootstrap.add_argument(
        "--manifest-csv",
        type=Path,
        default=None,
        help="Optional mesh batch manifest CSV merged into the generated catalog.",
    )
    regional_lab_bootstrap.add_argument(
        "--site-id-template",
        default="{cluster_id}_outlet_{outlet_id}",
        help="Template used to derive site_id from cluster_id and outlet_id.",
    )
    regional_lab_bootstrap.add_argument(
        "--outlet-id-column",
        default="outlet_id",
        help="Outlet identifier column in the source outlets table.",
    )
    regional_lab_bootstrap.add_argument(
        "--x-column",
        default="x_outlet",
        help="X coordinate column in the source outlets table.",
    )
    regional_lab_bootstrap.add_argument(
        "--y-column",
        default="y_outlet",
        help="Y coordinate column in the source outlets table.",
    )
    regional_lab_bootstrap.add_argument(
        "--area-column",
        default="area_km2",
        help="Optional area column in the source outlets table.",
    )
    regional_lab_bootstrap.add_argument(
        "--tag",
        action="append",
        default=[],
        help="Extra tag appended to every generated site row. Repeatable.",
    )
    regional_lab_bootstrap.set_defaults(_handler="regional_lab_bootstrap_catalog")

    return parser


def main(argv: list[str] | None = None) -> int:
    args_raw = list(sys.argv[1:] if argv is None else argv)
    parser = _build_parser()

    try:
        parsed = parser.parse_args(args_raw)
    except SystemExit as exc:
        return int(exc.code)

    if parsed.command == "simulation":
        _run_simulation_launcher(parsed.config.expanduser().resolve())
        return 0

    handler = getattr(parsed, "_handler", None)
    if handler == "mesh_catchment_run":
        _run_mesh_catchment_launcher(parsed.config.expanduser().resolve())
        return 0
    if handler == "mesh_catchment_template":
        output_path = None
        if parsed.output is not None:
            output_path = parsed.output.expanduser().resolve()
        _render_mesh_catchment_template(
            batch=bool(parsed.batch),
            profile=str(parsed.profile),
            output_path=output_path,
        )
        return 0
    if handler == "data_overview_run":
        _run_data_overview_launcher(parsed.config.expanduser().resolve())
        return 0
    if handler == "data_overview_template":
        from launchers.data_overview.templates import (
            render_overview_template,
            write_overview_template,
        )

        if parsed.output is None:
            sys.stdout.write(render_overview_template())
        else:
            output_path = parsed.output.expanduser().resolve()
            write_overview_template(output_path)
            print(f"Wrote template: {output_path}")
        return 0
    if handler == "model_calibration_run":
        _run_model_calibration_launcher(parsed.config.expanduser().resolve())
        return 0
    if handler == "model_calibration_template":
        from launchers.model_calibration.templates import (
            render_model_calibration_template,
            write_model_calibration_template,
        )

        if parsed.output is None:
            sys.stdout.write(render_model_calibration_template())
        else:
            output_path = parsed.output.expanduser().resolve()
            write_model_calibration_template(output_path)
            print(f"Wrote template: {output_path}")
        return 0
    if handler == "method_comparison_run":
        _run_method_comparison_launcher(parsed.config.expanduser().resolve())
        return 0
    if handler == "method_comparison_template":
        from launchers.method_comparison.templates import (
            render_method_comparison_template,
            write_method_comparison_template,
        )

        if parsed.output is None:
            sys.stdout.write(render_method_comparison_template())
        else:
            output_path = parsed.output.expanduser().resolve()
            write_method_comparison_template(output_path)
            print(f"Wrote template: {output_path}")
        return 0
    if handler == "regional_lab_run":
        _run_regional_lab_launcher(parsed.config.expanduser().resolve())
        return 0
    if handler == "regional_lab_template":
        from launchers.regional_lab.templates import (
            render_regional_lab_template,
            write_regional_lab_template,
        )

        if parsed.output is None:
            sys.stdout.write(render_regional_lab_template())
        else:
            output_path = parsed.output.expanduser().resolve()
            write_regional_lab_template(output_path)
            print(f"Wrote template: {output_path}")
        return 0
    if handler == "regional_lab_bootstrap_catalog":
        manifest_csv = None
        if parsed.manifest_csv is not None:
            manifest_csv = parsed.manifest_csv.expanduser().resolve()
        _bootstrap_regional_lab_catalog(
            outlets_table=parsed.outlets_table.expanduser().resolve(),
            output=parsed.output.expanduser().resolve(),
            cluster_id=str(parsed.cluster_id),
            region_id=str(parsed.region_id),
            source_selection_id=str(parsed.source_selection_id),
            cluster_label=None if parsed.cluster_label is None else str(parsed.cluster_label),
            cluster_family=None if parsed.cluster_family is None else str(parsed.cluster_family),
            cluster_scale=None if parsed.cluster_scale is None else str(parsed.cluster_scale),
            manifest_csv=manifest_csv,
            site_id_template=str(parsed.site_id_template),
            outlet_id_column=str(parsed.outlet_id_column),
            x_column=str(parsed.x_column),
            y_column=str(parsed.y_column),
            area_column=str(parsed.area_column),
            tags=[str(item) for item in parsed.tag],
        )
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
