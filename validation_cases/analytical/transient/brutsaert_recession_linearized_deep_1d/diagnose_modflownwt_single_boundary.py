"""Minimal MODFLOW-NWT reproduction for the deep Brutsaert single-boundary issue."""

from __future__ import annotations

import copy
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from types import SimpleNamespace
import sys

import numpy as np
from flopy.utils.binaryfile import HeadFile

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from hydromodpy.process.flow import Flow
from hydromodpy.solver.modflow_nwt import (
    Modflow,
    ModflowPostprocessOptions,
    ModflowPreprocessOptions,
    ModflowRunOptions,
)
from hydromodpy.workflow.pipelines.process_simulation import HydroModPyLauncher
from validation_cases.analytical.transient.brutsaert_common import (
    _load_modflownwt_budget_diagnostics,
)
from validation_cases.shared.runtime import (
    _build_validation_launcher_config,
    remove_file_with_retry,
    resolve_validation_results_dir,
)


CASE_DIR = Path(__file__).resolve().parent
CASE_ID = "brutsaert_recession_linearized_deep_1d"
OUTLET_OBSERVABLE = "outlet_discharge_east_side_m3_s"
SUMMARY_FILENAME = "modflownwt_single_boundary_diagnostic_summary.json"


@dataclass(frozen=True, slots=True)
class ProbeResult:
    """Compact summary for one direct MODFLOW-NWT probe run."""

    probe_id: str
    stage: str
    success: bool
    nwt_options: str
    nper: int
    outlet_series_m3_s: tuple[float, ...]
    budget_max_abs_rate_discrepancy_percent: float | None
    budget_last_rate_discrepancy_percent: float | None
    first_bad_stress_period: int | None
    model_ws: str
    note: str


def _build_validation_launcher() -> HydroModPyLauncher:
    """Materialize one launcher configured exactly like the validation case."""
    config_path = _build_validation_launcher_config(
        case_dir=CASE_DIR,
        config_path=CASE_DIR / "config_modflownwt.toml",
        solver_name="modflownwt",
    )
    try:
        launcher = HydroModPyLauncher(config_path)
        launcher._run_setup()
        launcher._run_data()
        return launcher
    finally:
        if config_path.exists():
            remove_file_with_retry(config_path)


def _single_period_time_grid(base_time_grid) -> SimpleNamespace:
    """Return a one-period time grid aligned with the first validation step."""
    dt_seconds = float(tuple(base_time_grid.period_lengths_seconds)[0])
    return SimpleNamespace(
        period_lengths_seconds=(dt_seconds,),
        window=SimpleNamespace(start=getattr(base_time_grid.window, "start", None)),
    )


def _transient_time_grid(base_time_grid) -> SimpleNamespace:
    """Return the recession-only time grid (all periods after the warm-up step)."""
    periods = tuple(float(value) for value in tuple(base_time_grid.period_lengths_seconds)[1:])
    if not periods:
        raise ValueError("The Brutsaert diagnostic requires at least one transient period.")
    return SimpleNamespace(
        period_lengths_seconds=periods,
        window=SimpleNamespace(start=getattr(base_time_grid.window, "start", None)),
    )


def _build_steady_flow(base_flow: Flow, *, ic_value_m: float, recharge_value_m_s: float) -> Flow:
    """Clone the case flow config and force one steady warm-up run."""
    flow_cfg = base_flow.config.model_copy(deep=True, update={"flow_regime": "steady"})
    flow_cfg.ic = flow_cfg.ic.model_copy(
        update={"h": flow_cfg.ic.h.model_copy(update={"value": float(ic_value_m)})}
    )
    flow = Flow(flow_cfg)
    flow.set_recharge(
        copy.deepcopy(base_flow.sinks_sources["recharge"]).model_copy(
            update={"values": float(recharge_value_m_s)}
        )
    )
    return flow


def _build_transient_flow(base_flow: Flow, *, recharge_value_m_s: float = 0.0) -> Flow:
    """Clone the case flow config and force a pure recession transient run."""
    flow_cfg = base_flow.config.model_copy(deep=True, update={"flow_regime": "transient"})
    flow = Flow(flow_cfg)
    flow.set_recharge(
        copy.deepcopy(base_flow.sinks_sources["recharge"]).model_copy(
            update={"values": float(recharge_value_m_s)}
        )
    )
    return flow


def _load_outlet_series(model_ws: Path) -> tuple[float, ...]:
    """Return the saved east-side outlet discharge series as plain scalars."""
    payload = np.load(
        model_ws / "_postprocess" / f"{OUTLET_OBSERVABLE}.npy",
        allow_pickle=True,
    ).item()
    ordered = sorted((int(key), np.asarray(value, dtype=float)) for key, value in payload.items())
    return tuple(float(np.asarray(value, dtype=float).reshape(-1)[0]) for _, value in ordered)


def _load_restart_head(model_ws: Path, model_name: str) -> np.ndarray:
    """Return the last MODFLOW head array from one completed run."""
    head_path = model_ws / f"{model_name}.hds"
    head_file = HeadFile(str(head_path))
    return np.asarray(head_file.get_data(totim=head_file.get_times()[-1]), dtype=float)


def _summarize_budget(model_ws: Path) -> tuple[float | None, float | None, int | None]:
    """Extract the main MODFLOW-NWT rate budget diagnostics from the list file."""
    diagnostics = _load_modflownwt_budget_diagnostics(model_ws)
    if diagnostics is None:
        return None, None, None

    signed_percent = np.asarray(diagnostics["rate_percent_discrepancies"], dtype=float)
    stress_periods = np.asarray(diagnostics["stress_periods"], dtype=int)
    if signed_percent.size == 0:
        return None, None, None

    abs_percent = np.abs(signed_percent)
    bad_indices = np.flatnonzero(abs_percent > 5.0)
    first_bad = None if bad_indices.size == 0 else int(stress_periods[int(bad_indices[0])])
    return float(np.max(abs_percent)), float(signed_percent[-1]), first_bad


def _run_probe(
    *,
    probe_id: str,
    stage: str,
    flow: Flow,
    domain,
    geographic,
    model_folder: Path,
    bin_path: str,
    modflow_config,
    time_grid,
    restart_head: np.ndarray | None = None,
    note: str,
) -> tuple[ProbeResult, np.ndarray | None]:
    """Run one direct MODFLOW-NWT probe and return its summary plus final head."""
    preprocess_options = ModflowPreprocessOptions(time_grid=time_grid)
    model = Modflow(
        geographic,
        model_folder=str(model_folder),
        model_name=probe_id,
        bin_path=bin_path,
        modflow_config=modflow_config,
        preprocess_options=preprocess_options,
    )
    model.pre_processing(
        flow=flow,
        domain=domain,
        options=preprocess_options,
    )
    if restart_head is not None:
        model.bas.strt = np.asarray(restart_head, dtype=float).copy()

    success = bool(
        model.processing(
            options=ModflowRunOptions(
                write_model=True,
                run_model=True,
                link_mt3dms=False,
                verbose=False,
            )
        )
    )

    outlet_series: tuple[float, ...] = ()
    final_head: np.ndarray | None = None
    if success:
        model.post_processing(
            options=ModflowPostprocessOptions(
                watertable_elevation=False,
                watertable_depth=False,
                seepage_areas=False,
                outflow_drain=False,
                outlet_discharge_east_side_m3_s=True,
                groundwater_flux=False,
                groundwater_storage=False,
                accumulation_flux=False,
            )
        )
        model_ws = Path(model.full_path)
        outlet_series = _load_outlet_series(model_ws)
        final_head = _load_restart_head(model_ws, model.model_name)
    else:
        model_ws = Path(model.full_path)

    budget_max_abs, budget_last, first_bad = _summarize_budget(model_ws)
    result = ProbeResult(
        probe_id=probe_id,
        stage=stage,
        success=success,
        nwt_options=str(modflow_config.runtime.nwt_options),
        nper=int(len(tuple(time_grid.period_lengths_seconds))),
        outlet_series_m3_s=outlet_series,
        budget_max_abs_rate_discrepancy_percent=budget_max_abs,
        budget_last_rate_discrepancy_percent=budget_last,
        first_bad_stress_period=first_bad,
        model_ws=str(model_ws),
        note=note,
    )
    return result, final_head


def _build_summary(results: list[ProbeResult]) -> dict[str, object]:
    """Assemble one JSON-serializable summary payload."""
    flat_steady = next(result for result in results if result.probe_id.endswith("steady_flat_ic"))
    nudged_steady = next(result for result in results if result.probe_id.endswith("steady_nudged_ic"))
    transient_simple = next(
        result for result in results if result.probe_id.endswith("transient_restart_simple")
    )
    transient_complex = next(
        result for result in results if result.probe_id.endswith("transient_restart_complex")
    )

    diagnosis = (
        "MODFLOW-NWT reproduces two distinct failure modes on the single-east-boundary "
        "Brutsaert strip: flat initial heads can falsely converge during the steady "
        "warm-up, and the restarted recession run keeps a severe transient rate-budget "
        "imbalance even after nudging the warm-up IC and switching SIMPLE/COMPLEX profiles."
    )
    return {
        "case_id": CASE_ID,
        "diagnosis": diagnosis,
        "key_findings": {
            "steady_flat_ic_false_convergence": {
                "budget_max_abs_rate_discrepancy_percent": (
                    flat_steady.budget_max_abs_rate_discrepancy_percent
                ),
                "outlet_discharge_m3_s": (
                    None if not flat_steady.outlet_series_m3_s else flat_steady.outlet_series_m3_s[-1]
                ),
            },
            "steady_nudged_ic_recovers_budget": {
                "budget_max_abs_rate_discrepancy_percent": (
                    nudged_steady.budget_max_abs_rate_discrepancy_percent
                ),
                "outlet_discharge_m3_s": (
                    None if not nudged_steady.outlet_series_m3_s else nudged_steady.outlet_series_m3_s[-1]
                ),
            },
            "transient_restart_simple_still_breaks": {
                "budget_max_abs_rate_discrepancy_percent": (
                    transient_simple.budget_max_abs_rate_discrepancy_percent
                ),
                "first_bad_stress_period": transient_simple.first_bad_stress_period,
            },
            "transient_restart_complex_still_breaks": {
                "budget_max_abs_rate_discrepancy_percent": (
                    transient_complex.budget_max_abs_rate_discrepancy_percent
                ),
                "first_bad_stress_period": transient_complex.first_bad_stress_period,
            },
        },
        "probes": [asdict(result) for result in results],
    }


def _print_probe(result: ProbeResult) -> None:
    """Print one concise terminal summary for the executed probe."""
    print(f"- {result.probe_id}")
    print(f"  stage: {result.stage}")
    print(f"  success: {result.success}")
    print(f"  nwt_options: {result.nwt_options}")
    if result.outlet_series_m3_s:
        print(f"  outlet first/last [m3/s]: {result.outlet_series_m3_s[0]:.6e} / {result.outlet_series_m3_s[-1]:.6e}")
    if result.budget_max_abs_rate_discrepancy_percent is not None:
        print(
            "  budget max abs rate discrepancy [%]: "
            f"{result.budget_max_abs_rate_discrepancy_percent:.2f}"
        )
    if result.first_bad_stress_period is not None:
        print(f"  first bad stress period: {result.first_bad_stress_period}")
    print(f"  note: {result.note}")
    print(f"  workspace: {result.model_ws}")


def main() -> None:
    """Run the direct NWT probes and persist one compact summary JSON."""
    launcher = _build_validation_launcher()
    setup = launcher.run_state.setup
    base_flow = setup.flow
    base_recharge = copy.deepcopy(base_flow.sinks_sources["recharge"])
    steady_recharge_m_s = float(base_recharge.values.iloc[0])

    out_path = resolve_validation_results_dir(
        test_file=__file__,
        run_name=f"{CASE_ID}_modflownwt_single_boundary_diagnostic",
    )
    model_folder = out_path / "results_simulations"
    model_folder.mkdir(parents=True, exist_ok=True)

    steady_time_grid = _single_period_time_grid(setup.time_grid)
    transient_time_grid = _transient_time_grid(setup.time_grid)
    base_modflow_cfg = launcher.cfg.modflownwt.model_copy(deep=True)

    results: list[ProbeResult] = []

    steady_flat_cfg = base_modflow_cfg.model_copy(deep=True)
    steady_flat_cfg.tgrid = steady_flat_cfg.tgrid.model_copy(update={"firstpersteady": False})
    steady_flat_result, _ = _run_probe(
        probe_id=f"{CASE_ID}_steady_flat_ic",
        stage="steady",
        flow=_build_steady_flow(
            base_flow,
            ic_value_m=50.0,
            recharge_value_m_s=steady_recharge_m_s,
        ),
        domain=setup.domain,
        geographic=setup.geographic,
        model_folder=model_folder,
        bin_path=setup.workspace.bin_path,
        modflow_config=steady_flat_cfg,
        time_grid=steady_time_grid,
        note="Flat IC equal to the east Dirichlet head: expected false steady convergence.",
    )
    results.append(steady_flat_result)

    steady_nudged_cfg = base_modflow_cfg.model_copy(deep=True)
    steady_nudged_cfg.tgrid = steady_nudged_cfg.tgrid.model_copy(update={"firstpersteady": False})
    steady_nudged_result, steady_restart_head = _run_probe(
        probe_id=f"{CASE_ID}_steady_nudged_ic",
        stage="steady",
        flow=_build_steady_flow(
            base_flow,
            ic_value_m=50.1,
            recharge_value_m_s=steady_recharge_m_s,
        ),
        domain=setup.domain,
        geographic=setup.geographic,
        model_folder=model_folder,
        bin_path=setup.workspace.bin_path,
        modflow_config=steady_nudged_cfg,
        time_grid=steady_time_grid,
        note="Small positive IC offset: expected to recover the steady recharge balance.",
    )
    results.append(steady_nudged_result)
    if steady_restart_head is None:
        raise RuntimeError("The nudged steady probe did not produce a restart head field.")

    transient_simple_cfg = base_modflow_cfg.model_copy(deep=True)
    transient_simple_cfg.tgrid = transient_simple_cfg.tgrid.model_copy(
        update={"firstpersteady": False}
    )
    transient_simple_result, _ = _run_probe(
        probe_id=f"{CASE_ID}_transient_restart_simple",
        stage="transient",
        flow=_build_transient_flow(base_flow, recharge_value_m_s=0.0),
        domain=setup.domain,
        geographic=setup.geographic,
        model_folder=model_folder,
        bin_path=setup.workspace.bin_path,
        modflow_config=transient_simple_cfg,
        time_grid=transient_time_grid,
        restart_head=steady_restart_head,
        note="Restarted recession with the default SIMPLE NWT profile.",
    )
    results.append(transient_simple_result)

    transient_complex_cfg = base_modflow_cfg.model_copy(deep=True)
    transient_complex_cfg.tgrid = transient_complex_cfg.tgrid.model_copy(
        update={"firstpersteady": False}
    )
    transient_complex_cfg.runtime = transient_complex_cfg.runtime.model_copy(
        update={"nwt_options": "COMPLEX", "nwt_maxiterout": 2000}
    )
    transient_complex_result, _ = _run_probe(
        probe_id=f"{CASE_ID}_transient_restart_complex",
        stage="transient",
        flow=_build_transient_flow(base_flow, recharge_value_m_s=0.0),
        domain=setup.domain,
        geographic=setup.geographic,
        model_folder=model_folder,
        bin_path=setup.workspace.bin_path,
        modflow_config=transient_complex_cfg,
        time_grid=transient_time_grid,
        restart_head=steady_restart_head,
        note="Same restarted recession after switching the NWT profile to COMPLEX.",
    )
    results.append(transient_complex_result)

    summary = _build_summary(results)
    summary_path = out_path / SUMMARY_FILENAME
    summary_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )

    print("MODFLOW-NWT single-boundary diagnostic")
    print(f"Results directory: {out_path}")
    print(f"Summary JSON: {summary_path}")
    for result in results:
        _print_probe(result)
    print("Diagnosis:")
    print(summary["diagnosis"])


if __name__ == "__main__":
    main()
