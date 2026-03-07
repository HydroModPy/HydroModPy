"""End-to-end regression test for examples/launcher_simulation/launcher_simulation.py."""

import pytest
from tests.regression.golden_utils import (
    REPO_ROOT,
    assert_required_executables,
    collect_modflow_signatures,
    collect_modpath_signatures,
    require_url_available,
    resolve_tiered_golden_file,
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
    / "config_normal.toml"
)

GOLDEN_REFERENCE_FILE = (
    resolve_tiered_golden_file(
        test_file=__file__,
        filename="launcher_simulation_normal_npy_signatures.json",
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


@pytest.mark.regression
@pytest.mark.normal
@pytest.mark.fast
@pytest.mark.parametrize(
    "config_path",
    [
        pytest.param(
            LAUNCHER_SIMULATION_DEFAULT_CONFIG,
            id="config_normal",
        ),
    ],
)
def test_launcher_simulation_regression_on_npy_outputs(tmp_path, update_goldens, config_path):
    """Run launcher_simulation, then compare or refresh its own golden signatures."""
    assert_required_executables(require_mt3dms=True)
    require_url_available(SHOM_HEALTHCHECK_URL)
    require_url_available(HUBEAU_HEALTHCHECK_URL)

    out_path = tmp_path / "launcher_simulation_outputs"
    run_example_script(
        script_path=LAUNCHER_SIMULATION_SCRIPT,
        out_path=out_path,
        out_env_var="HYDROMODPY_OUT_PATH",
        extra_env={"HYDROMODPY_NO_DISPLAY": "1"},
        script_args=[str(config_path)],
        timeout=3600,
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
