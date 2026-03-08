"""End-to-end regression test for examples_legacy/example12/example12.py."""

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

EXAMPLE12_SCRIPT = (
    REPO_ROOT
    / "examples_legacy"
    / "example12"
    / "example12.py"
)

GOLDEN_REFERENCE_FILE = (
    resolve_tiered_golden_file(
        test_file=__file__,
        filename="example12_npy_signatures.json",
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
@pytest.mark.extensive
@pytest.mark.slow
@pytest.mark.coverage
def test_example12_regression_on_npy_outputs(update_goldens):
    """Run example12, then compare (or refresh) its golden signatures."""
    assert_required_executables()
    require_url_available(SHOM_HEALTHCHECK_URL)
    require_url_available(HUBEAU_HEALTHCHECK_URL)

    out_path = resolve_tiered_results_dir(
        test_file=__file__,
        run_name="example12_outputs",
    )
    run_example_script(
        script_path=EXAMPLE12_SCRIPT,
        out_path=out_path,
        out_env_var="HYDROMODPY_OUT_PATH",
        extra_env={"HYDROMODPY_NO_DISPLAY": "1"},
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


