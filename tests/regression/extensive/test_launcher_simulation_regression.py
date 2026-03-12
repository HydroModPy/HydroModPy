"""End-to-end regression test for examples/launcher_simulation/launcher_simulation.py."""

from pathlib import Path

import pytest
from tests.regression.golden_utils import (
    REPO_ROOT,
    assert_required_executables,
    collect_modflow_signatures,
    collect_modpath_signatures,
    require_url_available,
    resolve_tiered_golden_file,
    resolve_tiered_results_dir,
    resolve_model_workspace,
    run_example_script,
    update_or_assert_goldens,
)

LAUNCHER_SIMULATION_SCRIPT = (
    REPO_ROOT
    / "examples"
    / "launcher_simulation"
    / "launcher_simulation.py"
)
LAUNCHER_SIMULATION_DEFAULT_CONFIG = (
    REPO_ROOT
    / "examples"
    / "launcher_simulation"
    / "config_extensive.toml"
)

GOLDEN_REFERENCE_FILE = (
    resolve_tiered_golden_file(
        test_file=__file__,
        filename="launcher_simulation_npy_signatures.json",
    )
)

MODFLOW_OUTPUT_NAMES = [
    "watertable_elevation",
    "watertable_depth",
    "seepage_areas",
    "outflow_drain",
    "accumulation_flux",
]

MODPATH_SNAPSHOT_FILES = [
    "starting.dbf",
    "ending.dbf",
]

MT3DMS_OUTPUT_NAMES = [
    "concentration_seepage",
    "mass_seepage",
]

SHOM_HEALTHCHECK_URL = "https://services.data.shom.fr"
HUBEAU_HEALTHCHECK_URL = "https://hubeau.eaufrance.fr/api/v2/hydrometrie/referentiel/stations?size=1&format=json"
SHOM_TIDE_GAUGE_ID = "152"
SHOM_START_DATE = "2003-01-01"
SHOM_END_DATE = "2003-01-30"
OCEANIC_LOCAL_CSV = (
    REPO_ROOT
    / "examples"
    / "launcher_simulation"
    / "data"
    / "oceanic"
    / "sealevel_shom_152_20030101_20030130_H.csv"
)


def _ensure_local_oceanic_seed_csv(csv_path: Path) -> None:
    """Ensure local SHOM seed exists for launcher_simulation oceanic MSL."""
    if csv_path.exists() and csv_path.stat().st_size > 0:
        return

    require_url_available(SHOM_HEALTHCHECK_URL)

    import pandas as pd
    import requests

    info_url = (
        "https://services.data.shom.fr/maregraphie/service/completetidegauge/"
        f"{SHOM_TIDE_GAUGE_ID}"
    )
    info_resp = requests.get(info_url, timeout=60)
    info_resp.raise_for_status()
    info_payload = info_resp.json()
    zh_ref = float(info_payload["verticalRef"]["zh_ref"])

    dt_start = f"{SHOM_START_DATE}T00%3A00%3A00Z"
    dt_end = f"{SHOM_END_DATE}T00%3A00%3A00Z"
    data_url = (
        "https://services.data.shom.fr/maregraphie/observation/json/"
        f"{SHOM_TIDE_GAUGE_ID}?sources=3&dtStart={dt_start}&dtEnd={dt_end}&interval=60"
    )
    data_resp = requests.get(data_url, timeout=120)
    data_resp.raise_for_status()
    payload = data_resp.json()
    rows = payload.get("data", [])
    if not rows:
        raise AssertionError("SHOM returned no rows for local oceanic seed generation.")

    df = pd.DataFrame(rows)[["timestamp", "value"]].copy()
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df["value"] = df["value"] + zh_ref
    df = df.dropna(subset=["timestamp", "value"]).reset_index(drop=True)
    if df.empty:
        raise AssertionError("Generated SHOM seed CSV is empty after cleaning.")

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(csv_path, index=False)


@pytest.mark.regression
@pytest.mark.extensive
@pytest.mark.slow
@pytest.mark.coverage
@pytest.mark.parametrize(
    "config_path",
    [
        pytest.param(
            LAUNCHER_SIMULATION_DEFAULT_CONFIG,
            id="config_extensive",
        ),
    ],
)
def test_launcher_simulation_regression_on_npy_outputs(update_goldens, config_path):
    """Run launcher_simulation, then compare or refresh its own golden signatures."""
    assert_required_executables(require_mt3dms=True)
    _ensure_local_oceanic_seed_csv(OCEANIC_LOCAL_CSV)
    require_url_available(HUBEAU_HEALTHCHECK_URL)

    out_path = resolve_tiered_results_dir(
        test_file=__file__,
        run_name="launcher_simulation_outputs",
    )
    run_example_script(
        script_path=LAUNCHER_SIMULATION_SCRIPT,
        out_path=out_path,
        out_env_var="HYDROMODPY_OUT_PATH",
        extra_env={"HYDROMODPY_NO_DISPLAY": "1"},
        script_args=[str(config_path)],
        timeout=7200,
    )

    _, postprocess_dir, particles_dir = resolve_model_workspace(
        out_path,
        watershed_name="example12",
        results_folder_name="results_simulations",
    )

    actual = {
        "modflow_expected": collect_modflow_signatures(postprocess_dir, MODFLOW_OUTPUT_NAMES),
        "modpath_expected": collect_modpath_signatures(particles_dir, MODPATH_SNAPSHOT_FILES),
        "mt3dms_expected": collect_modflow_signatures(postprocess_dir, MT3DMS_OUTPUT_NAMES),
    }
    update_or_assert_goldens(
        actual=actual,
        golden_reference_file=GOLDEN_REFERENCE_FILE,
        update_goldens=update_goldens,
    )
