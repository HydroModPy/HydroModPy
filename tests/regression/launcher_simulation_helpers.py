"""Shared helpers for launcher_simulation regression tests."""

from __future__ import annotations

from pathlib import Path

from tests.regression.golden_utils import (
    REPO_ROOT,
    assert_required_executables,
    collect_modflow_signatures,
    collect_modpath_signatures,
    require_url_available,
    resolve_model_workspace,
    resolve_tiered_golden_file,
    resolve_tiered_results_dir,
    run_example_script,
    update_or_assert_goldens,
)


LAUNCHER_SIMULATION_SCRIPT = (
    REPO_ROOT
    / "examples"
    / "launcher_simulation"
    / "launcher_simulation.py"
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

TRANSPORT_OUTPUT_NAMES = [
    "concentration_seepage",
    "mass_seepage",
]

SHOM_HEALTHCHECK_URL = "https://services.data.shom.fr"
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


def run_launcher_simulation_regression(
    *,
    test_file: str | Path,
    config_name: str,
    golden_filename: str,
    run_name: str,
    require_modflow: bool = True,
    require_modflow6: bool = False,
    require_modpath: bool = True,
    require_mt3dms: bool = False,
    transport_solver: str,
    update_goldens: bool,
    timeout: int = 3600,
    extra_env: dict[str, str] | None = None,
) -> None:
    """Run one launcher_simulation regression case and compare its signatures."""
    assert_required_executables(
        require_modflow=require_modflow,
        require_modflow6=require_modflow6,
        require_modpath=require_modpath,
        require_mt3dms=require_mt3dms,
    )
    _ensure_local_oceanic_seed_csv(OCEANIC_LOCAL_CSV)

    out_path = resolve_tiered_results_dir(
        test_file=test_file,
        run_name=run_name,
    )
    env = {"HYDROMODPY_NO_DISPLAY": "1"}
    if transport_solver == "mf6":
        env["HYDROMODPY_NO_SAVE"] = "1"
    if extra_env:
        env.update(extra_env)

    run_example_script(
        script_path=LAUNCHER_SIMULATION_SCRIPT,
        out_path=out_path,
        out_env_var="HYDROMODPY_OUT_PATH",
        extra_env=env,
        script_args=[
            str(
                REPO_ROOT
                / "examples"
                / "launcher_simulation"
                / config_name
            )
        ],
        timeout=timeout,
    )

    _, postprocess_dir, particles_dir = resolve_model_workspace(
        out_path,
        watershed_name="example12",
        results_folder_name="results_simulations",
    )

    actual = {
        "modflow_expected": collect_modflow_signatures(postprocess_dir, MODFLOW_OUTPUT_NAMES),
    }
    if transport_solver == "mf6":
        actual["transport_expected"] = collect_modflow_signatures(
            postprocess_dir,
            TRANSPORT_OUTPUT_NAMES,
        )
    elif transport_solver == "mt3dms":
        actual["modpath_expected"] = collect_modpath_signatures(
            particles_dir,
            MODPATH_SNAPSHOT_FILES,
        )
        actual["mt3dms_expected"] = collect_modflow_signatures(
            postprocess_dir,
            TRANSPORT_OUTPUT_NAMES,
        )
    else:
        raise ValueError(f"Unsupported transport_solver: {transport_solver}")

    update_or_assert_goldens(
        actual=actual,
        golden_reference_file=resolve_tiered_golden_file(
            test_file=test_file,
            filename=golden_filename,
        ),
        update_goldens=update_goldens,
    )
