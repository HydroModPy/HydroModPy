"""Nancon-specific entry point for the catchment report pipeline."""

# ruff: noqa: E402, I001

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hydromodpy.display.catchment_report.cli import (  # noqa: E402
    add_catchment_report_arguments,
    options_from_args,
    print_catchment_report_result,
)
from hydromodpy.display.catchment_report.pipeline import (  # noqa: E402
    CatchmentReportPipelineResult,
    run_catchment_report_pipeline,
)
from hydromodpy.display.catchment_report.presets import (  # noqa: E402
    CatchmentReportPreset,
    preset_from_name,
)


def default_report_config() -> Path:
    """Return the default Nancon catchment-report TOML."""

    return Path(__file__).with_name("catchment_report.toml")


def build_nancon_real_figures_report(
    *,
    report_config: Path | None = None,
    preset: CatchmentReportPreset | None = None,
    run_overview: bool | None = None,
    run_simulation: bool | None = None,
    build_context_artifacts: bool | None = None,
    build_report_html: bool | None = None,
    no_lock: bool | None = None,
    stream_run_logs: bool | None = None,
    strict_figure_postflight: bool | None = None,
) -> CatchmentReportPipelineResult:
    """Build the Nancon report by calling the report pipeline directly."""

    return run_catchment_report_pipeline(
        report_config or default_report_config(),
        preset=preset,
        run_overview=run_overview,
        run_simulation=run_simulation,
        build_context_artifacts=build_context_artifacts,
        build_report_html=build_report_html,
        no_lock=no_lock,
        stream_run_logs=stream_run_logs,
        strict_figure_postflight=strict_figure_postflight,
    )


def main(argv: list[str] | None = None) -> int:
    """Run the Nancon report CLI."""

    parser = argparse.ArgumentParser(description=__doc__)
    add_catchment_report_arguments(
        parser,
        report_config_option=True,
        default_report_config=default_report_config(),
    )
    args = parser.parse_args(argv)
    try:
        options = options_from_args(args)
        result = build_nancon_real_figures_report(
            report_config=options.report_config,
            preset=preset_from_name(options.preset_name) if options.preset_name else None,
            run_overview=options.run_overview,
            run_simulation=options.run_simulation,
            build_context_artifacts=options.build_context_artifacts,
            build_report_html=options.build_report_html,
            no_lock=options.no_lock,
            stream_run_logs=options.stream_run_logs,
            strict_figure_postflight=options.strict_figure_postflight,
        )
    except ValueError as exc:
        parser.error(str(exc))
    print_catchment_report_result(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
