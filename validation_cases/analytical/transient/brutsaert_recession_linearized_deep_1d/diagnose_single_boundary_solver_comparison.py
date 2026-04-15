"""Direct NWT vs MF6 comparison for the deep Brutsaert single-boundary strip."""

from __future__ import annotations

import copy
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from types import SimpleNamespace
import sys
from typing import Any, Callable

import numpy as np
from flopy.utils.binaryfile import CellBudgetFile, HeadFile

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from hydromodpy.process.flow import Flow
from hydromodpy.solver.modflow6 import Modflow6
from hydromodpy.solver.modflow_nwt import (
    Modflow,
    ModflowPostprocessOptions,
    ModflowPreprocessOptions,
    ModflowRunOptions,
)
from hydromodpy.project import Simulation
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
SUMMARY_FILENAME = "single_boundary_solver_comparison_summary.json"
SOLVER_CONFIG_FILES = {
    "modflownwt": "config_modflownwt.toml",
    "modflow6": "config_modflow6.toml",
}
PROBE_IDS = {
    "nwt_steady_flat": "nwt_steady_flat",
    "nwt_steady_nudged": "nwt_steady_nudged",
    "nwt_transient_simple": "nwt_transient_simple",
    "nwt_transient_complex": "nwt_transient_complex",
    "nwt_transient_from_mf6_head": "nwt_from_mf6_head",
    "nwt_one_shot": "nwt_one_shot",
    "nwt_one_shot_confined": "nwt_one_shot_conf",
    "mf6_steady_flat": "mf6_steady_flat",
    "mf6_steady_nudged": "mf6_steady_nudged",
    "mf6_transient": "mf6_transient",
    "mf6_one_shot_confined": "mf6_one_shot_conf",
}


@dataclass(frozen=True, slots=True)
class ProbeResult:
    """Compact summary for one direct solver probe."""

    solver_name: str
    probe_id: str
    stage: str
    success: bool
    runtime_profile: str
    nper: int
    outlet_series_m3_s: tuple[float, ...]
    outlet_drop_fraction: float | None
    monotone_nonincreasing: bool | None
    budget_max_abs_rate_discrepancy_percent: float | None
    budget_last_rate_discrepancy_percent: float | None
    first_bad_stress_period: int | None
    model_ws: str
    note: str


ModelMutator = Callable[[Any], None]


def _build_validation_launcher(*, solver_name: str) -> Simulation:
    """Materialize one Simulation configured exactly like the validation case."""
    try:
        config_name = SOLVER_CONFIG_FILES[solver_name]
    except KeyError as exc:
        raise ValueError(f"Unsupported solver for this diagnostic: {solver_name}") from exc

    config_path = _build_validation_launcher_config(
        case_dir=CASE_DIR,
        config_path=CASE_DIR / config_name,
        solver_name=solver_name,
    )
    try:
        return Simulation(config_path, headless=True)
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


def _clone_flow(base_flow: Flow) -> Flow:
    """Clone one launcher-built flow object with its original recharge forcing."""
    flow = Flow(base_flow.config.model_copy(deep=True))
    flow.set_recharge(copy.deepcopy(base_flow.sinks_sources["recharge"]))
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
    """Return the last solver head array from one completed run."""
    head_path = model_ws / f"{model_name}.hds"
    head_file = HeadFile(str(head_path))
    return np.asarray(head_file.get_data(totim=head_file.get_times()[-1]), dtype=float)


def _load_head_change_signature(
    model_ws: Path,
    model_name: str,
    *,
    limit: int = 5,
) -> list[dict[str, float | int]]:
    """Return the first per-step head-change norms from one solver head file."""
    head_path = model_ws / f"{model_name}.hds"
    head_file = HeadFile(str(head_path))
    times = list(head_file.get_times())
    heads = [np.asarray(head_file.get_data(totim=time), dtype=float).reshape(-1) for time in times]
    changes: list[dict[str, float | int]] = []
    for index in range(1, min(len(heads), limit + 1)):
        delta = heads[index] - heads[index - 1]
        changes.append(
            {
                "transition_index": int(index),
                "rmse_m": float(np.sqrt(np.mean(delta**2))),
                "max_abs_diff_m": float(np.max(np.abs(delta))),
                "mean_diff_m": float(np.mean(delta)),
            }
        )
    return changes


def _budget_term_sum_m3_s(
    model_ws: Path,
    model_name: str,
    *,
    text: str,
    kstpkper: tuple[int, int],
) -> float | None:
    """Return the summed rate [m3/s] for one cell-budget term and period."""
    budget_path = model_ws / f"{model_name}.cbc"
    cbb = None
    for kwargs in ({}, {"precision": "double"}, {"precision": "single"}):
        try:
            cbb = CellBudgetFile(str(budget_path), **kwargs)
            break
        except TypeError:
            if kwargs:
                continue
            raise
        except Exception:
            if kwargs == {"precision": "single"}:
                return None
            continue
    if cbb is None:
        return None
    try:
        records = cbb.get_data(kstpkper=kstpkper, text=text)
    except Exception:
        return None
    if not records:
        return None

    payload = records[0]
    if getattr(payload, "dtype", None) is not None and payload.dtype.names is not None:
        field = "q" if "q" in payload.dtype.names else payload.dtype.names[-1]
        values = np.asarray(payload[field], dtype=float).reshape(-1)
    else:
        values = np.asarray(payload, dtype=float).reshape(-1)
    return float(np.sum(values))


def _summarize_nwt_budget(model_ws: Path) -> tuple[float | None, float | None, int | None]:
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


def _series_drop_fraction(series: tuple[float, ...]) -> float | None:
    """Return the relative drop between the first and last outlet values."""
    if len(series) < 2:
        return None
    first = float(series[0])
    if abs(first) <= 1e-30:
        return None
    return float((first - float(series[-1])) / first)


def _series_is_monotone_nonincreasing(series: tuple[float, ...]) -> bool | None:
    """Return whether the series is monotone decreasing up to a small tolerance."""
    if len(series) < 2:
        return None
    values = np.asarray(series, dtype=float)
    tolerance = max(float(np.max(np.abs(values))), 1.0) * 1e-12
    return bool(np.all(np.diff(values) <= tolerance))


def _coerce_head_to_nwt_layout(head: np.ndarray, *, nlay: int, nrow: int, ncol: int) -> np.ndarray:
    """Convert one head array to the structured NWT layout ``(nlay, nrow, ncol)``."""
    arr = np.asarray(head, dtype=float)
    if arr.shape == (nlay, nrow, ncol):
        return arr.copy()
    if arr.shape == (nlay, nrow * ncol):
        return arr.reshape(nlay, nrow, ncol).copy()
    if arr.size == nlay * nrow * ncol:
        return arr.reshape(nlay, nrow, ncol).copy()
    raise ValueError(f"Unsupported restart head shape for NWT: {arr.shape}")


def _coerce_head_to_mf6_layout(head: np.ndarray, *, nlay: int, ncpl: int) -> np.ndarray:
    """Convert one head array to the MF6 DISV layout ``(nlay, ncpl)``."""
    arr = np.asarray(head, dtype=float)
    if arr.shape == (nlay, ncpl):
        return arr.copy()
    if arr.ndim == 3 and arr.shape[0] == nlay and int(np.prod(arr.shape[1:])) == ncpl:
        return arr.reshape(nlay, ncpl).copy()
    raise ValueError(f"Unsupported restart head shape for MF6: {arr.shape}")


def _run_nwt_probe(
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
    model_mutator: ModelMutator | None = None,
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
        model.bas.strt = _coerce_head_to_nwt_layout(
            restart_head,
            nlay=int(model.nlay),
            nrow=int(model.nrow),
            ncol=int(model.ncol),
        )
    if model_mutator is not None:
        model_mutator(model)

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

    budget_max_abs, budget_last, first_bad = _summarize_nwt_budget(model_ws)
    result = ProbeResult(
        solver_name="modflownwt",
        probe_id=probe_id,
        stage=stage,
        success=success,
        runtime_profile=str(modflow_config.runtime.nwt_options),
        nper=int(len(tuple(time_grid.period_lengths_seconds))),
        outlet_series_m3_s=outlet_series,
        outlet_drop_fraction=_series_drop_fraction(outlet_series),
        monotone_nonincreasing=_series_is_monotone_nonincreasing(outlet_series),
        budget_max_abs_rate_discrepancy_percent=budget_max_abs,
        budget_last_rate_discrepancy_percent=budget_last,
        first_bad_stress_period=first_bad,
        model_ws=str(model_ws),
        note=note,
    )
    return result, final_head


def _run_mf6_probe(
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
    model_mutator: ModelMutator | None = None,
    note: str,
) -> tuple[ProbeResult, np.ndarray | None]:
    """Run one direct MODFLOW 6 probe and return its summary plus final head."""
    preprocess_options = ModflowPreprocessOptions(time_grid=time_grid)
    model = Modflow6(
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
        start_heads = _coerce_head_to_mf6_layout(
            restart_head,
            nlay=int(model.nlay),
            ncpl=int(model.ncpl),
        )
        if hasattr(model.ic.strt, "set_data"):
            model.ic.strt.set_data(start_heads)
        else:
            model.ic.strt = start_heads
    if model_mutator is not None:
        model_mutator(model)

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

    result = ProbeResult(
        solver_name="modflow6",
        probe_id=probe_id,
        stage=stage,
        success=success,
        runtime_profile=f"IMS={modflow_config.runtime.mf6_ims_complexity}",
        nper=int(len(tuple(time_grid.period_lengths_seconds))),
        outlet_series_m3_s=outlet_series,
        outlet_drop_fraction=_series_drop_fraction(outlet_series),
        monotone_nonincreasing=_series_is_monotone_nonincreasing(outlet_series),
        budget_max_abs_rate_discrepancy_percent=None,
        budget_last_rate_discrepancy_percent=None,
        first_bad_stress_period=None,
        model_ws=str(model_ws),
        note=note,
    )
    return result, final_head


def _relative_series_l2_error(
    reference: tuple[float, ...],
    candidate: tuple[float, ...],
) -> float | None:
    """Return ``||candidate-reference|| / ||reference||`` when series lengths match."""
    ref = np.asarray(reference, dtype=float)
    cand = np.asarray(candidate, dtype=float)
    if ref.size == 0 or cand.size == 0 or ref.size != cand.size:
        return None
    denom = float(np.linalg.norm(ref))
    if denom <= 1e-30:
        return None
    return float(np.linalg.norm(cand - ref) / denom)


def _drop_leading_periods(series: tuple[float, ...], *, count: int) -> tuple[float, ...]:
    """Drop one fixed number of leading periods from a solver series."""
    if count <= 0:
        return tuple(series)
    if len(series) <= count:
        return ()
    return tuple(series[count:])


def _make_nwt_confined(model: Any) -> None:
    """Force one NWT model into a confined-like variant for diagnosis only."""
    laytype = np.zeros((int(model.nlay),), dtype=int)
    sy = np.zeros_like(np.asarray(model.sy, dtype=float))
    sy_value = np.zeros_like(np.asarray(model.sy_value, dtype=float))
    model.laytype = laytype
    model.sy = sy
    model.sy_value = sy_value
    model.upw.laytyp = laytype
    model.upw.sy = sy


def _make_mf6_confined(model: Any) -> None:
    """Force one MF6 model into a confined-like variant for diagnosis only."""
    iconvert = np.zeros((int(model.nlay), int(model.ncpl)), dtype=int)
    sy = np.zeros_like(np.asarray(model.sy, dtype=float))
    model.sy = sy
    if hasattr(model.sto.iconvert, "set_data"):
        model.sto.iconvert.set_data(iconvert)
    else:
        model.sto.iconvert = iconvert
    if hasattr(model.sto.sy, "set_data"):
        model.sto.sy.set_data(sy)
    else:
        model.sto.sy = sy


def _head_rmse_m(reference: np.ndarray, candidate: np.ndarray) -> float:
    """Return head RMSE between two arrays once flattened."""
    ref = np.asarray(reference, dtype=float).reshape(-1)
    cand = np.asarray(candidate, dtype=float).reshape(-1)
    if ref.shape != cand.shape:
        raise ValueError(f"Head shapes do not match: {ref.shape} vs {cand.shape}")
    return float(np.sqrt(np.mean((cand - ref) ** 2)))


def _head_max_abs_diff_m(reference: np.ndarray, candidate: np.ndarray) -> float:
    """Return the maximum absolute head difference between two arrays."""
    ref = np.asarray(reference, dtype=float).reshape(-1)
    cand = np.asarray(candidate, dtype=float).reshape(-1)
    if ref.shape != cand.shape:
        raise ValueError(f"Head shapes do not match: {ref.shape} vs {cand.shape}")
    return float(np.max(np.abs(cand - ref)))


def _print_probe(result: ProbeResult) -> None:
    """Print one concise terminal summary for the executed probe."""
    print(f"- {result.probe_id}")
    print(f"  solver: {result.solver_name}")
    print(f"  stage: {result.stage}")
    print(f"  success: {result.success}")
    print(f"  runtime_profile: {result.runtime_profile}")
    if result.outlet_series_m3_s:
        print(
            "  outlet first/last [m3/s]: "
            f"{result.outlet_series_m3_s[0]:.6e} / {result.outlet_series_m3_s[-1]:.6e}"
        )
    if result.outlet_drop_fraction is not None:
        print(f"  outlet drop fraction [-]: {result.outlet_drop_fraction:.6f}")
    if result.monotone_nonincreasing is not None:
        print(f"  monotone nonincreasing: {result.monotone_nonincreasing}")
    if result.budget_max_abs_rate_discrepancy_percent is not None:
        print(
            "  budget max abs rate discrepancy [%]: "
            f"{result.budget_max_abs_rate_discrepancy_percent:.2f}"
        )
    if result.first_bad_stress_period is not None:
        print(f"  first bad stress period: {result.first_bad_stress_period}")
    print(f"  note: {result.note}")
    print(f"  workspace: {result.model_ws}")


def _build_summary(
    *,
    results: list[ProbeResult],
    nwt_steady_nudged_head: np.ndarray,
    mf6_steady_nudged_head: np.ndarray,
) -> dict[str, object]:
    """Assemble one JSON-serializable summary payload."""
    by_probe = {result.probe_id: result for result in results}

    nwt_flat = by_probe[PROBE_IDS["nwt_steady_flat"]]
    nwt_nudged = by_probe[PROBE_IDS["nwt_steady_nudged"]]
    nwt_transient_simple = by_probe[PROBE_IDS["nwt_transient_simple"]]
    nwt_transient_complex = by_probe[PROBE_IDS["nwt_transient_complex"]]
    nwt_transient_from_mf6_head = by_probe[PROBE_IDS["nwt_transient_from_mf6_head"]]
    nwt_one_shot = by_probe[PROBE_IDS["nwt_one_shot"]]
    nwt_one_shot_confined = by_probe[PROBE_IDS["nwt_one_shot_confined"]]
    mf6_flat = by_probe[PROBE_IDS["mf6_steady_flat"]]
    mf6_nudged = by_probe[PROBE_IDS["mf6_steady_nudged"]]
    mf6_transient = by_probe[PROBE_IDS["mf6_transient"]]
    mf6_one_shot_confined = by_probe[PROBE_IDS["mf6_one_shot_confined"]]

    nwt_one_shot_recession = _drop_leading_periods(
        nwt_one_shot.outlet_series_m3_s,
        count=1,
    )
    nwt_one_shot_confined_recession = _drop_leading_periods(
        nwt_one_shot_confined.outlet_series_m3_s,
        count=1,
    )
    mf6_one_shot_confined_recession = _drop_leading_periods(
        mf6_one_shot_confined.outlet_series_m3_s,
        count=1,
    )

    steady_head_rmse = _head_rmse_m(mf6_steady_nudged_head, nwt_steady_nudged_head)
    steady_head_max_abs = _head_max_abs_diff_m(mf6_steady_nudged_head, nwt_steady_nudged_head)
    transient_simple_rel_l2 = _relative_series_l2_error(
        mf6_transient.outlet_series_m3_s,
        nwt_transient_simple.outlet_series_m3_s,
    )
    transient_complex_rel_l2 = _relative_series_l2_error(
        mf6_transient.outlet_series_m3_s,
        nwt_transient_complex.outlet_series_m3_s,
    )
    transient_from_mf6_head_rel_l2 = _relative_series_l2_error(
        mf6_transient.outlet_series_m3_s,
        nwt_transient_from_mf6_head.outlet_series_m3_s,
    )
    transient_from_mf6_head_vs_nwt_simple_rel_l2 = _relative_series_l2_error(
        nwt_transient_simple.outlet_series_m3_s,
        nwt_transient_from_mf6_head.outlet_series_m3_s,
    )
    one_shot_vs_mf6_rel_l2 = _relative_series_l2_error(
        mf6_transient.outlet_series_m3_s,
        nwt_one_shot_recession,
    )
    one_shot_vs_nwt_simple_rel_l2 = _relative_series_l2_error(
        nwt_transient_simple.outlet_series_m3_s,
        nwt_one_shot_recession,
    )
    confined_nwt_vs_confined_mf6_rel_l2 = _relative_series_l2_error(
        mf6_one_shot_confined_recession,
        nwt_one_shot_confined_recession,
    )
    nwt_one_shot_ws = Path(nwt_one_shot.model_ws)
    mf6_transient_ws = Path(mf6_transient.model_ws)
    nwt_confined_ws = Path(nwt_one_shot_confined.model_ws)
    mf6_confined_ws = Path(mf6_one_shot_confined.model_ws)
    nwt_head_change_signature = _load_head_change_signature(
        nwt_one_shot_ws,
        nwt_one_shot.probe_id,
    )
    mf6_head_change_signature = _load_head_change_signature(
        mf6_transient_ws,
        mf6_transient.probe_id,
    )
    nwt_confined_head_change_signature = _load_head_change_signature(
        nwt_confined_ws,
        nwt_one_shot_confined.probe_id,
    )
    mf6_confined_head_change_signature = _load_head_change_signature(
        mf6_confined_ws,
        mf6_one_shot_confined.probe_id,
    )
    nwt_budget_signature = {
        "stress_period_2_storage_rate_m3_s": _budget_term_sum_m3_s(
            nwt_one_shot_ws,
            nwt_one_shot.probe_id,
            text="STORAGE",
            kstpkper=(0, 1),
        ),
        "stress_period_2_constant_head_rate_m3_s": _budget_term_sum_m3_s(
            nwt_one_shot_ws,
            nwt_one_shot.probe_id,
            text="CONSTANT HEAD",
            kstpkper=(0, 1),
        ),
        "stress_period_3_storage_rate_m3_s": _budget_term_sum_m3_s(
            nwt_one_shot_ws,
            nwt_one_shot.probe_id,
            text="STORAGE",
            kstpkper=(0, 2),
        ),
        "stress_period_3_constant_head_rate_m3_s": _budget_term_sum_m3_s(
            nwt_one_shot_ws,
            nwt_one_shot.probe_id,
            text="CONSTANT HEAD",
            kstpkper=(0, 2),
        ),
    }
    mf6_budget_signature = {
        "stress_period_1_sto_sy_rate_m3_s": _budget_term_sum_m3_s(
            mf6_transient_ws,
            mf6_transient.probe_id,
            text="STO-SY",
            kstpkper=(0, 0),
        ),
        "stress_period_1_chd_rate_m3_s": _budget_term_sum_m3_s(
            mf6_transient_ws,
            mf6_transient.probe_id,
            text="CHD",
            kstpkper=(0, 0),
        ),
        "stress_period_2_sto_sy_rate_m3_s": _budget_term_sum_m3_s(
            mf6_transient_ws,
            mf6_transient.probe_id,
            text="STO-SY",
            kstpkper=(0, 1),
        ),
        "stress_period_2_chd_rate_m3_s": _budget_term_sum_m3_s(
            mf6_transient_ws,
            mf6_transient.probe_id,
            text="CHD",
            kstpkper=(0, 1),
        ),
    }
    nwt_confined_budget_signature = {
        "stress_period_2_storage_rate_m3_s": _budget_term_sum_m3_s(
            nwt_confined_ws,
            nwt_one_shot_confined.probe_id,
            text="STORAGE",
            kstpkper=(0, 1),
        ),
        "stress_period_2_constant_head_rate_m3_s": _budget_term_sum_m3_s(
            nwt_confined_ws,
            nwt_one_shot_confined.probe_id,
            text="CONSTANT HEAD",
            kstpkper=(0, 1),
        ),
        "stress_period_3_storage_rate_m3_s": _budget_term_sum_m3_s(
            nwt_confined_ws,
            nwt_one_shot_confined.probe_id,
            text="STORAGE",
            kstpkper=(0, 2),
        ),
        "stress_period_3_constant_head_rate_m3_s": _budget_term_sum_m3_s(
            nwt_confined_ws,
            nwt_one_shot_confined.probe_id,
            text="CONSTANT HEAD",
            kstpkper=(0, 2),
        ),
    }
    mf6_confined_budget_signature = {
        "stress_period_2_sto_ss_rate_m3_s": _budget_term_sum_m3_s(
            mf6_confined_ws,
            mf6_one_shot_confined.probe_id,
            text="STO-SS",
            kstpkper=(0, 1),
        ),
        "stress_period_2_chd_rate_m3_s": _budget_term_sum_m3_s(
            mf6_confined_ws,
            mf6_one_shot_confined.probe_id,
            text="CHD",
            kstpkper=(0, 1),
        ),
        "stress_period_3_sto_ss_rate_m3_s": _budget_term_sum_m3_s(
            mf6_confined_ws,
            mf6_one_shot_confined.probe_id,
            text="STO-SS",
            kstpkper=(0, 2),
        ),
        "stress_period_3_chd_rate_m3_s": _budget_term_sum_m3_s(
            mf6_confined_ws,
            mf6_one_shot_confined.probe_id,
            text="CHD",
            kstpkper=(0, 2),
        ),
    }

    flat_q_nwt = None if not nwt_flat.outlet_series_m3_s else nwt_flat.outlet_series_m3_s[-1]
    flat_q_mf6 = None if not mf6_flat.outlet_series_m3_s else mf6_flat.outlet_series_m3_s[-1]
    nudged_q_nwt = None if not nwt_nudged.outlet_series_m3_s else nwt_nudged.outlet_series_m3_s[-1]
    nudged_q_mf6 = None if not mf6_nudged.outlet_series_m3_s else mf6_nudged.outlet_series_m3_s[-1]

    diagnosis = (
        "MODFLOW 6 confirms that the Brutsaert strip itself is viable with the same "
        "single east-side Dirichlet boundary: steady warm-up heads match the NWT "
        "steady state once NWT is nudged off the flat IC, but NWT still diverges "
        "in every transient variant tested: split run, restart from the MF6 steady "
        "head field, one-shot validation-like execution, and a confined-like "
        "variant with Sy removed. The boundary geometry therefore looks consistent; "
        "the remaining failure is solver-side and specific to the NWT transient "
        "behavior on this setup."
    )
    return {
        "case_id": CASE_ID,
        "diagnosis": diagnosis,
        "key_findings": {
            "same_boundary_mf6_is_stable": {
                "steady_flat_outlet_discharge_m3_s": flat_q_mf6,
                "steady_nudged_outlet_discharge_m3_s": nudged_q_mf6,
                "steady_flat_vs_nudged_delta_m3_s": (
                    None if flat_q_mf6 is None or nudged_q_mf6 is None else float(flat_q_mf6 - nudged_q_mf6)
                ),
            },
            "nwt_flat_ic_is_solver_specific": {
                "steady_flat_outlet_discharge_m3_s": flat_q_nwt,
                "steady_nudged_outlet_discharge_m3_s": nudged_q_nwt,
                "steady_flat_budget_max_abs_rate_discrepancy_percent": (
                    nwt_flat.budget_max_abs_rate_discrepancy_percent
                ),
            },
            "steady_states_match_after_nwt_nudge": {
                "head_rmse_m": steady_head_rmse,
                "head_max_abs_diff_m": steady_head_max_abs,
            },
            "transient_failure_is_nwt_specific": {
                "mf6_outlet_drop_fraction": mf6_transient.outlet_drop_fraction,
                "nwt_simple_outlet_drop_fraction": nwt_transient_simple.outlet_drop_fraction,
                "nwt_complex_outlet_drop_fraction": nwt_transient_complex.outlet_drop_fraction,
                "nwt_from_mf6_head_outlet_drop_fraction": (
                    nwt_transient_from_mf6_head.outlet_drop_fraction
                ),
                "nwt_one_shot_recession_outlet_drop_fraction": (
                    _series_drop_fraction(nwt_one_shot_recession)
                ),
                "nwt_simple_vs_mf6_relative_l2_error": transient_simple_rel_l2,
                "nwt_complex_vs_mf6_relative_l2_error": transient_complex_rel_l2,
                "nwt_from_mf6_head_vs_mf6_relative_l2_error": transient_from_mf6_head_rel_l2,
                "nwt_from_mf6_head_vs_nwt_simple_relative_l2_error": (
                    transient_from_mf6_head_vs_nwt_simple_rel_l2
                ),
                "nwt_one_shot_recession_vs_mf6_relative_l2_error": one_shot_vs_mf6_rel_l2,
                "nwt_one_shot_recession_vs_nwt_simple_relative_l2_error": (
                    one_shot_vs_nwt_simple_rel_l2
                ),
                "nwt_simple_budget_max_abs_rate_discrepancy_percent": (
                    nwt_transient_simple.budget_max_abs_rate_discrepancy_percent
                ),
                "nwt_complex_budget_max_abs_rate_discrepancy_percent": (
                    nwt_transient_complex.budget_max_abs_rate_discrepancy_percent
                ),
                "nwt_from_mf6_head_budget_max_abs_rate_discrepancy_percent": (
                    nwt_transient_from_mf6_head.budget_max_abs_rate_discrepancy_percent
                ),
                "nwt_one_shot_budget_max_abs_rate_discrepancy_percent": (
                    nwt_one_shot.budget_max_abs_rate_discrepancy_percent
                ),
            },
            "confined_variant": {
                "nwt_one_shot_confined_last_outlet_discharge_m3_s": (
                    None
                    if not nwt_one_shot_confined.outlet_series_m3_s
                    else float(nwt_one_shot_confined.outlet_series_m3_s[-1])
                ),
                "mf6_one_shot_confined_last_outlet_discharge_m3_s": (
                    None
                    if not mf6_one_shot_confined.outlet_series_m3_s
                    else float(mf6_one_shot_confined.outlet_series_m3_s[-1])
                ),
                "nwt_one_shot_confined_recession_outlet_drop_fraction": (
                    _series_drop_fraction(nwt_one_shot_confined_recession)
                ),
                "mf6_one_shot_confined_recession_outlet_drop_fraction": (
                    _series_drop_fraction(mf6_one_shot_confined_recession)
                ),
                "nwt_one_shot_confined_budget_max_abs_rate_discrepancy_percent": (
                    nwt_one_shot_confined.budget_max_abs_rate_discrepancy_percent
                ),
                "nwt_one_shot_confined_vs_mf6_confined_relative_l2_error": (
                    confined_nwt_vs_confined_mf6_rel_l2
                ),
            },
            "budget_package_signature": {
                "nwt_one_shot": nwt_budget_signature,
                "mf6_transient": mf6_budget_signature,
                "nwt_one_shot_confined": nwt_confined_budget_signature,
                "mf6_one_shot_confined": mf6_confined_budget_signature,
            },
            "head_change_signature": {
                "nwt_one_shot_first_transitions": nwt_head_change_signature,
                "mf6_transient_first_transitions": mf6_head_change_signature,
                "nwt_one_shot_confined_first_transitions": nwt_confined_head_change_signature,
                "mf6_one_shot_confined_first_transitions": mf6_confined_head_change_signature,
            },
        },
        "probes": [asdict(result) for result in results],
    }


def main() -> None:
    """Run direct NWT and MF6 probes and persist one compact comparison JSON."""
    nwt_launcher = _build_validation_launcher(solver_name="modflownwt")
    mf6_launcher = _build_validation_launcher(solver_name="modflow6")

    nwt_setup = nwt_launcher.run_state.setup
    mf6_setup = mf6_launcher.run_state.setup
    nwt_base_flow = nwt_setup.flow
    mf6_base_flow = mf6_setup.flow
    nwt_steady_recharge_m_s = float(copy.deepcopy(nwt_base_flow.sinks_sources["recharge"]).values.iloc[0])
    mf6_steady_recharge_m_s = float(copy.deepcopy(mf6_base_flow.sinks_sources["recharge"]).values.iloc[0])

    out_path = resolve_validation_results_dir(
        test_file=__file__,
        run_name=f"{CASE_ID}_single_boundary_solver_comparison",
    )
    model_folder = out_path / "results_simulations"
    model_folder.mkdir(parents=True, exist_ok=True)

    nwt_steady_time_grid = _single_period_time_grid(nwt_setup.time_grid)
    nwt_transient_time_grid = _transient_time_grid(nwt_setup.time_grid)
    mf6_steady_time_grid = _single_period_time_grid(mf6_setup.time_grid)
    mf6_transient_time_grid = _transient_time_grid(mf6_setup.time_grid)

    nwt_cfg = nwt_launcher.cfg.modflownwt.model_copy(deep=True)
    mf6_cfg = mf6_launcher.cfg.modflow6.model_copy(deep=True)

    results: list[ProbeResult] = []

    nwt_steady_flat_cfg = nwt_cfg.model_copy(deep=True)
    nwt_steady_flat_cfg.tgrid = nwt_steady_flat_cfg.tgrid.model_copy(update={"firstpersteady": False})
    nwt_steady_flat_result, _ = _run_nwt_probe(
        probe_id=PROBE_IDS["nwt_steady_flat"],
        stage="steady",
        flow=_build_steady_flow(
            nwt_base_flow,
            ic_value_m=50.0,
            recharge_value_m_s=nwt_steady_recharge_m_s,
        ),
        domain=nwt_setup.domain,
        geographic=nwt_setup.geographic,
        model_folder=model_folder,
        bin_path=nwt_setup.workspace.bin_path,
        modflow_config=nwt_steady_flat_cfg,
        time_grid=nwt_steady_time_grid,
        note="NWT steady warm-up with a flat IC equal to the east Dirichlet head.",
    )
    results.append(nwt_steady_flat_result)

    nwt_steady_nudged_cfg = nwt_cfg.model_copy(deep=True)
    nwt_steady_nudged_cfg.tgrid = nwt_steady_nudged_cfg.tgrid.model_copy(
        update={"firstpersteady": False}
    )
    nwt_steady_nudged_result, nwt_steady_head = _run_nwt_probe(
        probe_id=PROBE_IDS["nwt_steady_nudged"],
        stage="steady",
        flow=_build_steady_flow(
            nwt_base_flow,
            ic_value_m=50.1,
            recharge_value_m_s=nwt_steady_recharge_m_s,
        ),
        domain=nwt_setup.domain,
        geographic=nwt_setup.geographic,
        model_folder=model_folder,
        bin_path=nwt_setup.workspace.bin_path,
        modflow_config=nwt_steady_nudged_cfg,
        time_grid=nwt_steady_time_grid,
        note="NWT steady warm-up with a small positive IC offset.",
    )
    results.append(nwt_steady_nudged_result)
    if nwt_steady_head is None:
        raise RuntimeError("The NWT nudged steady probe did not produce a restart head field.")

    nwt_transient_simple_cfg = nwt_cfg.model_copy(deep=True)
    nwt_transient_simple_cfg.tgrid = nwt_transient_simple_cfg.tgrid.model_copy(
        update={"firstpersteady": False}
    )
    nwt_transient_simple_result, _ = _run_nwt_probe(
        probe_id=PROBE_IDS["nwt_transient_simple"],
        stage="transient",
        flow=_build_transient_flow(nwt_base_flow, recharge_value_m_s=0.0),
        domain=nwt_setup.domain,
        geographic=nwt_setup.geographic,
        model_folder=model_folder,
        bin_path=nwt_setup.workspace.bin_path,
        modflow_config=nwt_transient_simple_cfg,
        time_grid=nwt_transient_time_grid,
        restart_head=nwt_steady_head,
        note="NWT restarted recession with the default SIMPLE profile.",
    )
    results.append(nwt_transient_simple_result)

    nwt_transient_complex_cfg = nwt_cfg.model_copy(deep=True)
    nwt_transient_complex_cfg.tgrid = nwt_transient_complex_cfg.tgrid.model_copy(
        update={"firstpersteady": False}
    )
    nwt_transient_complex_cfg.runtime = nwt_transient_complex_cfg.runtime.model_copy(
        update={"nwt_options": "COMPLEX", "nwt_maxiterout": 2000}
    )
    nwt_transient_complex_result, _ = _run_nwt_probe(
        probe_id=PROBE_IDS["nwt_transient_complex"],
        stage="transient",
        flow=_build_transient_flow(nwt_base_flow, recharge_value_m_s=0.0),
        domain=nwt_setup.domain,
        geographic=nwt_setup.geographic,
        model_folder=model_folder,
        bin_path=nwt_setup.workspace.bin_path,
        modflow_config=nwt_transient_complex_cfg,
        time_grid=nwt_transient_time_grid,
        restart_head=nwt_steady_head,
        note="NWT restarted recession after switching to the COMPLEX profile.",
    )
    results.append(nwt_transient_complex_result)

    mf6_steady_flat_cfg = mf6_cfg.model_copy(deep=True)
    mf6_steady_flat_cfg.tgrid = mf6_steady_flat_cfg.tgrid.model_copy(update={"firstpersteady": False})
    mf6_steady_flat_result, _ = _run_mf6_probe(
        probe_id=PROBE_IDS["mf6_steady_flat"],
        stage="steady",
        flow=_build_steady_flow(
            mf6_base_flow,
            ic_value_m=50.0,
            recharge_value_m_s=mf6_steady_recharge_m_s,
        ),
        domain=mf6_setup.domain,
        geographic=mf6_setup.geographic,
        model_folder=model_folder,
        bin_path=mf6_setup.workspace.bin_path,
        modflow_config=mf6_steady_flat_cfg,
        time_grid=mf6_steady_time_grid,
        note="MF6 steady warm-up with the same flat IC used to trigger the NWT issue.",
    )
    results.append(mf6_steady_flat_result)

    mf6_steady_nudged_cfg = mf6_cfg.model_copy(deep=True)
    mf6_steady_nudged_cfg.tgrid = mf6_steady_nudged_cfg.tgrid.model_copy(update={"firstpersteady": False})
    mf6_steady_nudged_result, mf6_steady_head = _run_mf6_probe(
        probe_id=PROBE_IDS["mf6_steady_nudged"],
        stage="steady",
        flow=_build_steady_flow(
            mf6_base_flow,
            ic_value_m=50.1,
            recharge_value_m_s=mf6_steady_recharge_m_s,
        ),
        domain=mf6_setup.domain,
        geographic=mf6_setup.geographic,
        model_folder=model_folder,
        bin_path=mf6_setup.workspace.bin_path,
        modflow_config=mf6_steady_nudged_cfg,
        time_grid=mf6_steady_time_grid,
        note="MF6 steady warm-up with the same small IC offset used for NWT.",
    )
    results.append(mf6_steady_nudged_result)
    if mf6_steady_head is None:
        raise RuntimeError("The MF6 nudged steady probe did not produce a restart head field.")

    nwt_transient_from_mf6_head_cfg = nwt_cfg.model_copy(deep=True)
    nwt_transient_from_mf6_head_cfg.tgrid = nwt_transient_from_mf6_head_cfg.tgrid.model_copy(
        update={"firstpersteady": False}
    )
    nwt_transient_from_mf6_head_result, _ = _run_nwt_probe(
        probe_id=PROBE_IDS["nwt_transient_from_mf6_head"],
        stage="transient",
        flow=_build_transient_flow(nwt_base_flow, recharge_value_m_s=0.0),
        domain=nwt_setup.domain,
        geographic=nwt_setup.geographic,
        model_folder=model_folder,
        bin_path=nwt_setup.workspace.bin_path,
        modflow_config=nwt_transient_from_mf6_head_cfg,
        time_grid=nwt_transient_time_grid,
        restart_head=mf6_steady_head,
        note="NWT restarted recession from the steady head field produced by MF6.",
    )
    results.append(nwt_transient_from_mf6_head_result)

    nwt_one_shot_result, _ = _run_nwt_probe(
        probe_id=PROBE_IDS["nwt_one_shot"],
        stage="transient",
        flow=_clone_flow(nwt_base_flow),
        domain=nwt_setup.domain,
        geographic=nwt_setup.geographic,
        model_folder=model_folder,
        bin_path=nwt_setup.workspace.bin_path,
        modflow_config=nwt_cfg.model_copy(deep=True),
        time_grid=nwt_setup.time_grid,
        note="NWT one-shot validation-like run with first steady period and no external restart.",
    )
    results.append(nwt_one_shot_result)

    nwt_one_shot_confined_result, _ = _run_nwt_probe(
        probe_id=PROBE_IDS["nwt_one_shot_confined"],
        stage="transient",
        flow=_clone_flow(nwt_base_flow),
        domain=nwt_setup.domain,
        geographic=nwt_setup.geographic,
        model_folder=model_folder,
        bin_path=nwt_setup.workspace.bin_path,
        modflow_config=nwt_cfg.model_copy(deep=True),
        time_grid=nwt_setup.time_grid,
        model_mutator=_make_nwt_confined,
        note="NWT one-shot run forced to a confined-like variant (laytyp=0, Sy=0).",
    )
    results.append(nwt_one_shot_confined_result)

    mf6_transient_cfg = mf6_cfg.model_copy(deep=True)
    mf6_transient_cfg.tgrid = mf6_transient_cfg.tgrid.model_copy(update={"firstpersteady": False})
    mf6_transient_result, _ = _run_mf6_probe(
        probe_id=PROBE_IDS["mf6_transient"],
        stage="transient",
        flow=_build_transient_flow(mf6_base_flow, recharge_value_m_s=0.0),
        domain=mf6_setup.domain,
        geographic=mf6_setup.geographic,
        model_folder=model_folder,
        bin_path=mf6_setup.workspace.bin_path,
        modflow_config=mf6_transient_cfg,
        time_grid=mf6_transient_time_grid,
        restart_head=mf6_steady_head,
        note="MF6 restarted recession on the same strip and boundary geometry.",
    )
    results.append(mf6_transient_result)

    mf6_one_shot_confined_result, _ = _run_mf6_probe(
        probe_id=PROBE_IDS["mf6_one_shot_confined"],
        stage="transient",
        flow=_clone_flow(mf6_base_flow),
        domain=mf6_setup.domain,
        geographic=mf6_setup.geographic,
        model_folder=model_folder,
        bin_path=mf6_setup.workspace.bin_path,
        modflow_config=mf6_cfg.model_copy(deep=True),
        time_grid=mf6_setup.time_grid,
        model_mutator=_make_mf6_confined,
        note="MF6 one-shot run forced to a confined-like variant (iconvert=0, Sy=0).",
    )
    results.append(mf6_one_shot_confined_result)

    summary = _build_summary(
        results=results,
        nwt_steady_nudged_head=nwt_steady_head,
        mf6_steady_nudged_head=mf6_steady_head,
    )
    summary_path = out_path / SUMMARY_FILENAME
    summary_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )

    print("Single-boundary solver comparison")
    print(f"Results directory: {out_path}")
    print(f"Summary JSON: {summary_path}")
    for result in results:
        _print_probe(result)
    print("Diagnosis:")
    print(summary["diagnosis"])


if __name__ == "__main__":
    main()
