"""Regression smoke test for the data-overview launcher workflow.

This test validates the data-only contract:
- setup/data artifacts are produced,
- no flow/transport solver outputs are created.
"""

from pathlib import Path

import pytest

from tests.regression.golden_utils import (
    REPO_ROOT,
    require_url_available,
    resolve_tiered_results_dir,
    run_example_script,
)

# NOTE: current example folder/module name is "overtiew" in repository.
LAUNCHER_DATA_OVERVIEW_SCRIPT = (
    REPO_ROOT
    / "examples"
    / "launcher_data_overtiew"
    / "launcher_data_overtiew.py"
)

SHOM_HEALTHCHECK_URL = "https://services.data.shom.fr"
HUBEAU_HEALTHCHECK_URL = (
    "https://hubeau.eaufrance.fr/api/v2/hydrometrie/referentiel/stations?size=1&format=json"
)


@pytest.mark.regression
@pytest.mark.extensive
@pytest.mark.slow
@pytest.mark.coverage
def test_launcher_data_overview_data_only_regression():
    """Run data-overview launcher and assert stable data-only side effects."""
    require_url_available(SHOM_HEALTHCHECK_URL)
    require_url_available(HUBEAU_HEALTHCHECK_URL)

    out_path = resolve_tiered_results_dir(
        test_file=__file__,
        run_name="launcher_data_overview_outputs",
    )
    run_example_script(
        script_path=LAUNCHER_DATA_OVERVIEW_SCRIPT,
        out_path=out_path,
        out_env_var="HYDROMODPY_OUT_PATH",
        extra_env={"HYDROMODPY_NO_DISPLAY": "1"},
        timeout=3600,
    )

    catch_root = out_path / "launcher_data_overtiew"
    stable_root = catch_root / "results_stable"

    required_files = [
        catch_root / "hydromodpy_debug.log",
        stable_root / "geographic" / "watershed.shp",
        stable_root / "geographic" / "watershed.tif",
        stable_root / "hydrography" / "streams.shp",
        stable_root / "intermittency" / "regional onde stations.shp",
        stable_root / "oceanic" / "sealevel_shom_152_20030101_20030130_H.csv",
    ]
    for path in required_files:
        assert path.exists(), f"Expected output is missing: {path}"
        assert path.stat().st_size > 0, f"Output exists but is empty: {path}"

    # Data-overview workflow must not trigger numerical solver runs.
    # ``results_simulations`` may be pre-created by workspace setup.
    results_simulations_dir = catch_root / "results_simulations"
    if results_simulations_dir.exists():
        simulation_files = [p for p in results_simulations_dir.rglob("*") if p.is_file()]
        assert not simulation_files, (
            "Unexpected files found in results_simulations for data-only workflow: "
            f"{simulation_files}"
        )
    forbidden_suffixes = {".nam", ".hds", ".cbc", ".oc", ".upw", ".nwt"}
    solver_outputs = [
        path
        for path in catch_root.rglob("*")
        if path.is_file() and path.suffix.lower() in forbidden_suffixes
    ]
    assert not solver_outputs, f"Unexpected solver outputs found: {solver_outputs}"
