"""End-to-end regression test for examples/05.../example_05.py."""

from pathlib import Path

import pytest

from tests.regression.golden_utils import (
    REPO_ROOT,
    assert_required_executables,
    collect_modflow_signatures,
    require_url_available,
    resolve_model_workspace,
    run_legacy_example_script,
    update_or_assert_goldens,
)


EXAMPLE_05_SCRIPT = (
    REPO_ROOT
    / "examples_legacy"
    / "05_piezometry_in_a_heterogeneous_coastal_aquifer"
    / "example_05.py"
)

GOLDEN_REFERENCE_FILE = (
    Path(__file__).resolve().parent
    / "reference"
    / "golden_references"
    / "example_05_npy_signatures.json"
)

MODFLOW_OUTPUT_NAMES = [
    "watertable_elevation",
    "outflow_drain",
    "groundwater_flux",
    "groundwater_storage",
]

HUBEAU_HEALTHCHECK_URL = (
    "https://hubeau.eaufrance.fr/api/v1/niveaux_nappes/stations?size=1"
)


@pytest.mark.regression
@pytest.mark.slow
def test_example_05_regression_on_npy_outputs(tmp_path, update_goldens):
    """Run example_05, then compare (or refresh) its golden signatures."""
    assert_required_executables()
    require_url_available(HUBEAU_HEALTHCHECK_URL)

    out_path = tmp_path / "example_05_outputs"
    try:
        run_legacy_example_script(
            script_path=EXAMPLE_05_SCRIPT,
            out_path=out_path,
            stop_method="postprocessing_modflow",
            expected_stop_calls=1,
            timeout=5400,
        )
    except AssertionError as exc:
        # Example 05 downloads piezometry inputs from online services.
        # Skip on transient HTTP/network failures, but keep all other failures.
        message = str(exc)
        network_markers = (
            "requests.exceptions.ConnectionError",
            "requests.exceptions.Timeout",
            "requests.exceptions.ReadTimeout",
            "urllib3.exceptions",
            "ConnectionAbortedError",
        )
        if any(marker in message for marker in network_markers):
            pytest.skip("Example 05 requires online piezometry APIs; network was unavailable.")
        raise

    _, postprocess_dir, _ = resolve_model_workspace(
        out_path,
        watershed_name="Example_05_Gouville",
        model_name="default",
    )

    actual = {
        "modflow_expected": collect_modflow_signatures(postprocess_dir, MODFLOW_OUTPUT_NAMES),
    }
    update_or_assert_goldens(
        actual=actual,
        golden_reference_file=GOLDEN_REFERENCE_FILE,
        update_goldens=update_goldens,
    )

