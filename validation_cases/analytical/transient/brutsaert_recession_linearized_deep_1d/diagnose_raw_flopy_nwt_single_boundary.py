"""Raw FloPy MODFLOW-NWT reproduction for the deep Brutsaert strip."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
import sys

import flopy
import numpy as np
from flopy.utils.binaryfile import CellBudgetFile, HeadFile

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from hydromodpy.solver.modflow_common import ensure_platform_executable
from validation_cases.analytical.transient.brutsaert_common import (
    _load_modflownwt_budget_diagnostics,
)
from validation_cases.shared.runtime import resolve_validation_results_dir


CASE_ID = "brutsaert_recession_linearized_deep_1d"
SUMMARY_FILENAME = "raw_flopy_nwt_single_boundary_summary.json"


@dataclass(frozen=True, slots=True)
class RawFloPySummary:
    """Compact summary for one raw FloPy MODFLOW-NWT run."""

    success: bool
    model_ws: str
    outlet_series_m3_s: tuple[float, ...]
    outlet_drop_fraction: float | None
    monotone_nonincreasing: bool | None
    budget_max_abs_rate_discrepancy_percent: float | None
    budget_last_rate_discrepancy_percent: float | None
    first_bad_stress_period: int | None
    head_change_signature: tuple[dict[str, float | int], ...]


def _exe_path() -> str:
    """Resolve the local MODFLOW-NWT executable."""
    repo_root = Path(__file__).resolve().parents[4]
    return str(ensure_platform_executable(repo_root / "bin" / "win" / "mfnwt.exe"))


def _build_model(model_ws: Path, *, model_name: str) -> flopy.modflow.Modflow:
    """Build one raw FloPy MODFLOW-NWT model matching the deep Brutsaert strip."""
    nlay, nrow, ncol = 1, 3, 40
    delr, delc = 10.0, 10.0
    top = np.full((nrow, ncol), 100.0, dtype=float)
    botm = np.full((nlay, nrow, ncol), 0.0, dtype=float)
    perlen = [864000.0] * 13
    nstp = [1] * 13
    steady = [True] + [False] * 12

    mf = flopy.modflow.Modflow(
        model_name,
        exe_name=_exe_path(),
        version="mfnwt",
        listunit=2,
        verbose=False,
        model_ws=str(model_ws),
    )
    flopy.modflow.ModflowNwt(
        mf,
        headtol=1e-6,
        fluxtol=1e-4,
        maxiterout=500,
        thickfact=1e-5,
        linmeth=1,
        iprnwt=0,
        ibotav=1,
        options="SIMPLE",
        Continue=False,
        backflag=0,
        stoptol=1e-10,
    )
    flopy.modflow.ModflowDis(
        mf,
        nlay=nlay,
        nrow=nrow,
        ncol=ncol,
        delr=delr,
        delc=delc,
        top=top,
        botm=botm,
        lenuni=2,
        itmuni=1,
        nper=len(perlen),
        perlen=perlen,
        nstp=nstp,
        steady=steady,
        start_datetime="2003-01-01 00:00:00",
    )

    ibound = np.ones((nlay, nrow, ncol), dtype=int)
    ibound[:, :, -1] = -1
    strt = np.full((nlay, nrow, ncol), 50.1, dtype=float)
    strt[:, :, -1] = 50.0
    flopy.modflow.ModflowBas(
        mf,
        ibound=ibound,
        strt=strt,
        hnoflo=-9999.0,
    )
    flopy.modflow.ModflowUpw(
        mf,
        laytyp=np.ones((nlay,), dtype=int),
        laywet=np.zeros((nlay,), dtype=int),
        hk=np.full((nlay, nrow, ncol), 1e-4, dtype=float),
        sy=np.full((nlay, nrow, ncol), 0.1, dtype=float),
        ss=np.full((nlay, nrow, ncol), 1e-10, dtype=float),
        vka=1.0,
        iphdry=1,
        hdry=-100.0,
        layvka=1,
        extension="upw",
        noparcheck=False,
    )

    recharge_m_per_s = 0.002 / 86400.0
    rch_data = {0: recharge_m_per_s}
    for kper in range(1, len(perlen)):
        rch_data[kper] = 0.0
    flopy.modflow.ModflowRch(mf, rech=rch_data)

    oc_spd = {(kper, 0): ["save head", "save budget"] for kper in range(len(perlen))}
    oc = flopy.modflow.ModflowOc(
        mf,
        stress_period_data=oc_spd,
        extension=["oc", "hds", "cbc"],
        compact=True,
    )
    oc.reset_budgetunit(fname=f"{model_name}.cbc")
    return mf


def _load_outlet_series(model_ws: Path, *, model_name: str, nrow: int, ncol: int) -> tuple[float, ...]:
    """Return east-side discharge time series from the raw NWT cell budget."""
    cbb = CellBudgetFile(str(model_ws / f"{model_name}.cbc"))
    east_nodes = {row * ncol + (ncol - 1) + 1 for row in range(nrow)}
    series: list[float] = []
    for kstpkper in cbb.get_kstpkper():
        rec = cbb.get_data(kstpkper=kstpkper, text="CONSTANT HEAD")
        if not rec:
            series.append(0.0)
            continue
        payload = rec[0]
        if getattr(payload, "dtype", None) is not None and payload.dtype.names is not None:
            node_field = "node" if "node" in payload.dtype.names else payload.dtype.names[0]
            q_field = "q" if "q" in payload.dtype.names else payload.dtype.names[-1]
            iterator = ((int(item[node_field]), float(item[q_field])) for item in payload)
        else:
            iterator = ((int(item[0]), float(item[-1])) for item in payload)
        discharge = 0.0
        for node, q in iterator:
            if node in east_nodes:
                discharge += max(-q, 0.0)
        series.append(float(discharge))
    return tuple(series)


def _head_change_signature(model_ws: Path, *, model_name: str, limit: int = 5) -> tuple[dict[str, float | int], ...]:
    """Return the first inter-period head changes from the raw head file."""
    head_file = HeadFile(str(model_ws / f"{model_name}.hds"))
    times = list(head_file.get_times())
    heads = [np.asarray(head_file.get_data(totim=time), dtype=float).reshape(-1) for time in times]
    result: list[dict[str, float | int]] = []
    for index in range(1, min(len(heads), limit + 1)):
        delta = heads[index] - heads[index - 1]
        result.append(
            {
                "transition_index": int(index),
                "rmse_m": float(np.sqrt(np.mean(delta**2))),
                "max_abs_diff_m": float(np.max(np.abs(delta))),
                "mean_diff_m": float(np.mean(delta)),
            }
        )
    return tuple(result)


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


def _series_drop_fraction(series: tuple[float, ...]) -> float | None:
    if len(series) < 3:
        return None
    recession = series[1:]
    first = float(recession[0])
    if abs(first) <= 1e-30:
        return None
    return float((first - float(recession[-1])) / first)


def _series_is_monotone_nonincreasing(series: tuple[float, ...]) -> bool | None:
    if len(series) < 3:
        return None
    recession = np.asarray(series[1:], dtype=float)
    tolerance = max(float(np.max(np.abs(recession))), 1.0) * 1e-12
    return bool(np.all(np.diff(recession) <= tolerance))


def main() -> None:
    """Run the raw FloPy NWT reproduction and persist one compact JSON summary."""
    out_path = resolve_validation_results_dir(
        test_file=__file__,
        run_name=f"{CASE_ID}_raw_flopy_nwt_single_boundary",
    )
    model_ws = out_path / "results_simulations" / "raw_flopy_nwt_single_boundary"
    model_ws.mkdir(parents=True, exist_ok=True)
    model_name = "raw_flopy_nwt_single_boundary"

    mf = _build_model(model_ws, model_name=model_name)
    mf.write_input()
    success, _ = mf.run_model(silent=True)

    outlet_series: tuple[float, ...] = ()
    head_signature: tuple[dict[str, float | int], ...] = ()
    budget_max_abs = None
    budget_last = None
    first_bad = None
    if success:
        outlet_series = _load_outlet_series(model_ws, model_name=model_name, nrow=3, ncol=40)
        head_signature = _head_change_signature(model_ws, model_name=model_name)
        budget_max_abs, budget_last, first_bad = _summarize_budget(model_ws)

    summary = RawFloPySummary(
        success=bool(success),
        model_ws=str(model_ws),
        outlet_series_m3_s=outlet_series,
        outlet_drop_fraction=_series_drop_fraction(outlet_series),
        monotone_nonincreasing=_series_is_monotone_nonincreasing(outlet_series),
        budget_max_abs_rate_discrepancy_percent=budget_max_abs,
        budget_last_rate_discrepancy_percent=budget_last,
        first_bad_stress_period=first_bad,
        head_change_signature=head_signature,
    )
    summary_path = out_path / SUMMARY_FILENAME
    summary_path.write_text(
        json.dumps(asdict(summary), indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )

    print("Raw FloPy MODFLOW-NWT single-boundary diagnostic")
    print(f"Results directory: {out_path}")
    print(f"Summary JSON: {summary_path}")
    print(f"Success: {summary.success}")
    if summary.outlet_series_m3_s:
        print(
            "Outlet first/last [m3/s]: "
            f"{summary.outlet_series_m3_s[0]:.6e} / {summary.outlet_series_m3_s[-1]:.6e}"
        )
    if summary.outlet_drop_fraction is not None:
        print(f"Recession drop fraction [-]: {summary.outlet_drop_fraction:.6f}")
    if summary.monotone_nonincreasing is not None:
        print(f"Monotone nonincreasing recession: {summary.monotone_nonincreasing}")
    if summary.budget_max_abs_rate_discrepancy_percent is not None:
        print(
            "MODFLOW-NWT budget max abs rate discrepancy [%]: "
            f"{summary.budget_max_abs_rate_discrepancy_percent:.2f}"
        )
    if summary.first_bad_stress_period is not None:
        print(f"First bad stress period: {summary.first_bad_stress_period}")


if __name__ == "__main__":
    main()
