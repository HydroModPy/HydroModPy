"""Compatibility implementation for the Nancon reference catchment report.

This module is intentionally a near-mechanical move of the former example
script. It keeps the current Nancon HTML and figures stable while the generic
catchment-report package is introduced.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path

from hydromodpy.display.catchment_report.builder import (
    CatchmentReportConfig,
    build_catchment_report,
)
from hydromodpy.display.catchment_report.inputs import CatchmentReportInputs
from hydromodpy.display.catchment_report.paths import (
    NANCON_REPORT_CONFIG,
    NANCON_REPORT_INPUTS,
)
from hydromodpy.display.catchment_report.presets import NANCON_REPORT_PRESET

DEFAULT_OUTPUT_DIR = NANCON_REPORT_INPUTS.output_dir
CONTEXT_SUMMARY = NANCON_REPORT_INPUTS.context_summary
DEFAULT_REPORT_CONFIG = NANCON_REPORT_CONFIG


def main(argv: list[str] | None = None) -> int:
    config_path = _report_config_arg(argv)
    parser = argparse.ArgumentParser(description=__doc__)
    defaults = CatchmentReportInputs.from_toml(config_path)
    default_allow_gallery_fallbacks = (
        defaults.allow_gallery_fallbacks
        if defaults.allow_gallery_fallbacks is not None
        else NANCON_REPORT_PRESET.allow_gallery_fallbacks
    )
    parser.add_argument("--report-config", type=Path, default=config_path)
    parser.add_argument("--output-dir", type=Path, default=defaults.output_dir)
    parser.add_argument("--site-label", default=defaults.site_label)
    parser.add_argument("--station-label", default=defaults.station_label)
    parser.add_argument("--title", default=defaults.title)
    parser.add_argument("--context-summary", type=Path, default=defaults.context_summary)
    parser.add_argument("--context-assets", type=Path, default=defaults.context_assets)
    parser.add_argument("--overview-figures", type=Path, default=defaults.overview_figures)
    parser.add_argument("--data-overview-figures", type=Path, default=defaults.data_overview_figures)
    parser.add_argument("--simulation-figures", type=Path, default=defaults.simulation_figures)
    parser.add_argument("--geographic-scratch", type=Path, default=defaults.geographic_scratch)
    parser.add_argument("--generated-network-root", type=Path, default=defaults.generated_network_root)
    parser.add_argument("--context-html", type=Path, default=defaults.context_html)
    parser.add_argument("--overview-standard-html", type=Path, default=defaults.overview_standard_html)
    parser.add_argument("--transient-config", type=Path, default=defaults.transient_config)
    parser.add_argument("--overview-config", type=Path, default=defaults.overview_config)
    parser.add_argument(
        "--allow-gallery-fallbacks",
        action=argparse.BooleanOptionalAction,
        default=default_allow_gallery_fallbacks,
        help="Allow Nancon documentation gallery fallbacks when a requested figure is absent.",
    )
    args = parser.parse_args(argv)

    inputs = replace(
        defaults,
        output_dir=args.output_dir,
        site_label=args.site_label,
        station_label=args.station_label,
        title=args.title,
        context_summary=args.context_summary,
        context_assets=args.context_assets,
        overview_figures=args.overview_figures,
        data_overview_figures=args.data_overview_figures,
        simulation_figures=args.simulation_figures,
        geographic_scratch=args.geographic_scratch,
        generated_network_root=args.generated_network_root,
        context_html=args.context_html,
        overview_standard_html=args.overview_standard_html,
        transient_config=args.transient_config,
        overview_config=args.overview_config,
        allow_gallery_fallbacks=args.allow_gallery_fallbacks,
    )
    html_path = build_catchment_report(
        CatchmentReportConfig.from_inputs(
            inputs,
            allow_gallery_fallbacks=args.allow_gallery_fallbacks,
            preset=NANCON_REPORT_PRESET,
        )
    )
    print(html_path)
    return 0


def _report_config_arg(argv: list[str] | None) -> Path:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--report-config", type=Path, default=DEFAULT_REPORT_CONFIG)
    args, _ = parser.parse_known_args(argv)
    return args.report_config


if __name__ == "__main__":
    raise SystemExit(main())
