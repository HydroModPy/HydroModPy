"""Default paths for the current Nancon reference catchment report."""

from __future__ import annotations

from pathlib import Path

from hydromodpy.display.catchment_report.inputs import CatchmentReportInputs

REPO_ROOT = Path(__file__).resolve().parents[3]

NANCON_REPORT_EXAMPLE_DIR = (
    REPO_ROOT / "examples" / "projects" / "16_nancon_natural_calibration"
)
NANCON_REPORT_CONFIG = NANCON_REPORT_EXAMPLE_DIR / "catchment_report.toml"
DEFAULT_OUTPUT_DIR = NANCON_REPORT_EXAMPLE_DIR / "outputs" / "nancon_real_figures"

CONTEXT_ROOT = REPO_ROOT / "examples" / "projects" / "15_nancon_gauged_context" / "outputs"

NANCON_PROJECT = REPO_ROOT / "examples" / "projects" / "02_nancon_watershed"
GEOLOGY_DATA_ROOT = REPO_ROOT / "examples" / "data" / "geology"
DATA_OVERVIEW_PROJECT = REPO_ROOT / "examples" / "projects" / "05_nancon_data_overview"

GALLERY_GEO = REPO_ROOT / "docs" / "source" / "_static" / "capability_gallery" / "geographic"
GALLERY_SIM = REPO_ROOT / "docs" / "source" / "_static" / "capability_gallery" / "simulation"

NANCON_REPORT_INPUTS = CatchmentReportInputs.from_toml(NANCON_REPORT_CONFIG)

CONTEXT_SUMMARY = NANCON_REPORT_INPUTS.context_summary
CONTEXT_ASSETS = NANCON_REPORT_INPUTS.context_assets
NANCON_GEOGRAPHIC_SCRATCH = NANCON_REPORT_INPUTS.geographic_scratch
OVERVIEW_FIGURES = NANCON_REPORT_INPUTS.overview_figures
DATA_OVERVIEW_FIGURES = NANCON_REPORT_INPUTS.data_overview_figures
SIMULATION_FIGURES = NANCON_REPORT_INPUTS.simulation_figures
DEFAULT_GENERATED_NETWORK_ROOT = NANCON_REPORT_INPUTS.generated_network_root
DEFAULT_CONTEXT_HTML = NANCON_REPORT_INPUTS.context_html
DEFAULT_OVERVIEW_STANDARD_HTML = NANCON_REPORT_INPUTS.overview_standard_html
DEFAULT_TRANSIENT_CONFIG = NANCON_REPORT_INPUTS.transient_config
DEFAULT_OVERVIEW_CONFIG = NANCON_REPORT_INPUTS.overview_config
