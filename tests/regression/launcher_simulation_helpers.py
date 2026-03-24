"""Shared helpers for launcher_simulation regression tests."""

from __future__ import annotations

from pathlib import Path

from validation_cases.analytical.steady.boussinesq_piecewise import mm_day_to_m_s
from validation_cases.shared.boussinesq_piecewise_strip import (
    aggregate_piecewise_strip_postprocess,
    write_piecewise_strip_bundle,
    write_piecewise_strip_launcher_config,
)
from tests.regression.golden_utils import (
    REPO_ROOT,
    assert_required_executables,
    collect_json_signatures,
    collect_modflow_signatures,
    collect_modpath_signatures,
    collect_npz_signatures,
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
    / "projects"
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

BOUSSINESQ_OUTPUT_NAMES = [
    "watertable_elevation",
    "watertable_depth",
]

BOUSSINESQ_SUMMARY_KEYS = [
    "active_drainage",
    "active_imposed_head_bc",
    "active_ocean",
    "active_recharge",
    "active_wells",
    "converged_by_period",
    "has_numerical_solution",
    "model_name",
    "n_cells",
    "n_edges",
    "n_nodes",
    "nonlinear_iterations",
    "period_lengths_seconds",
    "runtime_backend",
    "runtime_convergence_policy",
    "runtime_iteration_counter",
    "runtime_linear_system_layout",
    "runtime_solver_kind",
    "runtime_tol_residual_inf",
    "runtime_tol_state_update_inf",
    "solve_stage",
    "steady_mode",
    "steady_nonlinear_iterations",
    "steady_residual_norm_inf",
    "steady_termination_reason",
]

SHOM_HEALTHCHECK_URL = "https://services.data.shom.fr"
SHOM_TIDE_GAUGE_ID = "152"
SHOM_START_DATE = "2003-01-01"
SHOM_END_DATE = "2003-01-30"
OCEANIC_DATA_DIR = (
    REPO_ROOT
    / "examples"
    / "data"
    / "oceanic"
)
OCEANIC_LOCAL_CSV = OCEANIC_DATA_DIR / "sealevel_shom_152_20030101_20030130_H.csv"


def _ensure_local_oceanic_seed_csv(csv_path: Path) -> None:
    """Ensure local SHOM seed and custom-format files exist for oceanic."""
    oceanic_dir = csv_path.parent

    if csv_path.exists() and csv_path.stat().st_size > 0:
        _ensure_custom_format_files(oceanic_dir, csv_path)
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

    _ensure_custom_format_files(oceanic_dir, csv_path)


def _ensure_custom_format_files(oceanic_dir: Path, source_csv: Path) -> None:
    """Create oceanic_custom_LOC.csv and chronicle file from the SHOM seed."""
    import shutil

    loc_path = oceanic_dir / "oceanic_custom_LOC.csv"
    if not loc_path.exists():
        loc_path.write_text(
            "id,x,y,crs,unit\n"
            f"{SHOM_TIDE_GAUGE_ID},-4.4953,48.3816,EPSG:4326,m\n"
        )

    chronicle_path = oceanic_dir / f"oceanic_custom_{SHOM_TIDE_GAUGE_ID}_20030101_20030130_H.csv"
    if not chronicle_path.exists():
        shutil.copy2(source_csv, chronicle_path)


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
                / "projects"
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


def run_launcher_simulation_boussinesq_regression(
    *,
    test_file: str | Path,
    golden_filename: str,
    run_name: str,
    update_goldens: bool,
    timeout: int = 1800,
    config_stem: str = "run_fast_boussinesq",
    launcher_run_id: str = "launcher_simulation_fast_boussinesq",
    process_id: str = "flow_main",
    simulation_name: str = "Launcher fast Boussinesq regression",
    simulation_description: str = "Fast steady Boussinesq regression on a precomputed strip bundle",
    initial_head_m: float = 6.0,
    west_head_m: float | None = 5.0,
    east_head_m: float | None = 5.0,
    recharge_mm_day: float | None = 3.0,
) -> None:
    """Run one self-contained fast launcher regression for flow/boussinesq."""
    out_path = resolve_tiered_results_dir(
        test_file=test_file,
        run_name=run_name,
    )
    bundle_dir = write_piecewise_strip_bundle(out_path / "mesh_bundle")
    config_path = write_piecewise_strip_launcher_config(
        out_path / f"{config_stem}.toml",
        run_id=launcher_run_id,
        process_id=process_id,
        simulation_name=simulation_name,
        simulation_description=simulation_description,
        bundle_dir=bundle_dir,
        initial_head_m=initial_head_m,
        west_head_m=west_head_m,
        east_head_m=east_head_m,
        recharge_rate_m_s=(
            None if recharge_mm_day is None else mm_day_to_m_s(recharge_mm_day)
        ),
        runtime_backend="scipy_sparse",
    )

    run_example_script(
        script_path=LAUNCHER_SIMULATION_SCRIPT,
        out_path=out_path,
        out_env_var="HYDROMODPY_OUT_PATH",
        extra_env={"HYDROMODPY_NO_DISPLAY": "1"},
        script_args=[str(config_path)],
        timeout=timeout,
    )

    model_ws, postprocess_dir, _ = resolve_model_workspace(
        out_path,
        results_folder_name="results_simulations",
        model_name=f"{process_id}__boussinesq",
    )
    aggregate_piecewise_strip_postprocess(
        postprocess_dir,
        bundle_dir=bundle_dir,
    )

    actual = {
        "modflow_expected": collect_modflow_signatures(
            postprocess_dir,
            BOUSSINESQ_OUTPUT_NAMES,
        ),
        "boussinesq_summary_expected": collect_json_signatures(
            model_ws / "_boussinesq_summary.json",
            keys=BOUSSINESQ_SUMMARY_KEYS,
        ),
        "boussinesq_state_history_expected": collect_npz_signatures(
            model_ws / "_boussinesq_state_history.npz",
        ),
    }
    update_or_assert_goldens(
        actual=actual,
        golden_reference_file=resolve_tiered_golden_file(
            test_file=test_file,
            filename=golden_filename,
        ),
        update_goldens=update_goldens,
    )
