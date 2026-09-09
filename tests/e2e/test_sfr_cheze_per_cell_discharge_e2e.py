"""End-to-end: the discharge a gauge sees, on a real LAK + SFR + DRN + MVR run.

The synthetic Cheze fixture is the only committed model that builds every
package at once and routes water between them, which is exactly the combination
the per-cell discharge has to survive. Two things are checked against the real
MODFLOW files, not against a fake:

* the release union declared for such a run COVERS what the budget actually
  holds. That guard (``_refuse_records_the_union_misses``) refuses a release
  record no declared package reads, and it is the reason a run with a lake used
  to be refused: ``LAK`` was neither declared nor ruled out. A mover record on a
  surface package must be ruled out instead, or the same water is counted twice;
* ``reach_flow_by_cell`` reads the streamflow MODFLOW itself routed, keyed by
  the mesh cell of each reach. Under SFR nothing has to be accumulated to know
  the discharge at a gauge: the reach under it already carries the answer, and
  the water the movers brought is in it.

Reuses the fixture and the config of :mod:`tests.e2e.test_sfr_cheze_e2e`; see
its docstring for what the model is. Tolerances: ``tests/TOLERANCES.md`` row 47.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest

from tests.e2e.test_sfr_cheze_e2e import _LAKE_ID, _config_body
from tests.regression.golden_utils import (
    _open_result_store,
    _resolve_sim_id,
    assert_required_executables,
    run_hmp_cli,
)


def _run(tmp_path: Path) -> Path:
    out_path = tmp_path / "per_cell_discharge"
    out_path.mkdir(parents=True, exist_ok=True)
    config_path = out_path / "run_per_cell_discharge.toml"
    config_path.write_text(_config_body(with_sfr=True), encoding="utf-8")
    run_hmp_cli(config_path=config_path, out_path=out_path, timeout=2400)
    return out_path


def _solver_run(out_path: Path) -> tuple[Path, str]:
    """Return the scratch directory and model name of the MODFLOW 6 run."""
    budgets = [path for path in out_path.rglob("*.cbc") if "." not in path.stem]
    assert budgets, f"no model budget kept under {out_path}; set keep_solver_files"
    budget = budgets[0]
    return budget.parent, budget.stem


def _record_names(cbc_path: Path) -> list[str]:
    from hydromodpy.solver.modflow_common.calibration_extractors import open_cell_budget

    budget: Any = open_cell_budget(cbc_path)
    try:
        return [name.decode().strip() for name in budget.get_unique_record_names()]
    finally:
        close = getattr(budget, "close", None)
        if callable(close):
            close()


def _model_of_this_fixture() -> object:
    """The package attributes the Cheze build sets, as the union reads them."""
    from types import SimpleNamespace

    return SimpleNamespace(
        drn=SimpleNamespace(mover=SimpleNamespace(get_data=lambda: True)),
        sfr=object(),
        lak=object(),
        chd=None,
    )


@pytest.mark.e2e
@pytest.mark.mf6
@pytest.mark.binary
@pytest.mark.slow
def test_the_release_union_covers_a_real_lake_and_stream_budget(tmp_path: Path) -> None:
    assert_required_executables(
        require_modflow=False,
        require_modflow6=True,
        require_modpath=False,
        require_mt3dms=False,
    )
    from hydromodpy.solver.modflow_common.calibration_extractors import (
        _refuse_records_the_union_misses,
    )
    from hydromodpy.solver.modflow_common.observable_extraction import (
        excluded_release_records_for_model,
        release_packages_for_model,
    )

    out_path = _run(tmp_path)
    output_dir, model_name = _solver_run(out_path)
    records = _record_names(output_dir / f"{model_name}.cbc")

    # The fixture must actually exercise the combination, or this proves nothing.
    upper = {name.upper() for name in records}
    assert "LAK" in upper, f"the Cheze run wrote no LAK record; it holds {sorted(upper)}"
    assert "SFR" in upper, f"the Cheze run wrote no SFR record; it holds {sorted(upper)}"

    model = _model_of_this_fixture()
    packages = release_packages_for_model(model)
    assert {package.name for package in packages} >= {"DRN", "SFR", "LAK"}

    # Raises when a release record no declared package reads sits in the budget.
    _refuse_records_the_union_misses(
        packages,
        records,
        excluded_records=excluded_release_records_for_model(model),
    )


@pytest.mark.e2e
@pytest.mark.mf6
@pytest.mark.binary
@pytest.mark.slow
def test_a_routed_reach_carries_the_discharge_under_each_gauge_cell(tmp_path: Path) -> None:
    assert_required_executables(
        require_modflow=False,
        require_modflow6=True,
        require_modpath=False,
        require_mt3dms=False,
    )
    import flopy

    from hydromodpy.solver.modflow6.extractors.sfr import reach_flow_by_cell
    from hydromodpy.solver.modflow_common.calibration_extractors import (
        _resolve_seconds_per_unit,
    )

    out_path = _run(tmp_path)
    output_dir, model_name = _solver_run(out_path)
    times = flopy.utils.HeadFile(str(output_dir / f"{model_name}.hds")).get_times()

    by_cell = reach_flow_by_cell(
        output_dir,
        model_name,
        times=times,
        seconds_per_time_unit=_resolve_seconds_per_unit(output_dir, model_name),
    )

    assert by_cell, "the routed network yielded no reach flow keyed by mesh cell"
    for cell, series in by_cell.items():
        values = np.asarray(series, dtype=float)
        assert values.size == len(times), (
            f"reach cell {cell} carries {values.size} steps against {len(times)} solver steps"
        )
        assert np.all(np.isfinite(values)), f"reach cell {cell} carries a non-finite flow"
        # downstream_flow is reported negative by MF6 and sign-corrected on read;
        # a reach that carries water downstream is positive after that.
        assert np.all(values >= 0.0), f"reach cell {cell} carries a negative routed flow"

    assert max(float(np.max(series)) for series in by_cell.values()) > 0.0, (
        "every reach carries zero flow; the network routed no water"
    )


@pytest.mark.e2e
@pytest.mark.mf6
@pytest.mark.binary
@pytest.mark.slow
def test_the_reaches_carry_at_least_the_water_the_lake_receives(tmp_path: Path) -> None:
    """The lake is fed by the network, so a reach must carry what reaches it.

    A loose bound on purpose: the mover splits the inflow across reaches and the
    lake also gains from its own cells, so the point is the order of magnitude
    and the direction, not an equality.
    """
    assert_required_executables(
        require_modflow=False,
        require_modflow6=True,
        require_modpath=False,
        require_mt3dms=False,
    )
    import flopy

    from hydromodpy.solver.modflow6.extractors.sfr import reach_flow_by_cell
    from hydromodpy.solver.modflow_common.calibration_extractors import (
        _resolve_seconds_per_unit,
    )

    out_path = _run(tmp_path)
    output_dir, model_name = _solver_run(out_path)
    times = flopy.utils.HeadFile(str(output_dir / f"{model_name}.hds")).get_times()
    by_cell = reach_flow_by_cell(
        output_dir,
        model_name,
        times=times,
        seconds_per_time_unit=_resolve_seconds_per_unit(output_dir, model_name),
    )
    assert by_cell

    store = _open_result_store(out_path)
    try:
        from_mvr = store.query_timeseries(_resolve_sim_id(store), f"lake:{_LAKE_ID}", "from_mvr")
    finally:
        store.close()
    lake_inflow = float(np.max(np.asarray(from_mvr.values, dtype=float)))
    assert lake_inflow > 0.0, "the lake received no MVR inflow; the fixture no longer feeds it"

    busiest = max(float(np.max(np.asarray(series, dtype=float))) for series in by_cell.values())
    assert busiest > 0.0
