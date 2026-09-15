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

from hydromodpy.solver.modflow_common.catchment_support import catchment_cell_mask
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
    from hydromodpy.solver.modflow_common.time_units import seconds_per_solver_time_unit

    out_path = _run(tmp_path)
    output_dir, model_name = _solver_run(out_path)
    times = flopy.utils.HeadFile(str(output_dir / f"{model_name}.hds")).get_times()

    by_cell = reach_flow_by_cell(
        output_dir,
        model_name,
        times=times,
        seconds_per_time_unit=seconds_per_solver_time_unit(output_dir, model_name),
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
    from hydromodpy.solver.modflow_common.time_units import seconds_per_solver_time_unit

    out_path = _run(tmp_path)
    output_dir, model_name = _solver_run(out_path)
    times = flopy.utils.HeadFile(str(output_dir / f"{model_name}.hds")).get_times()
    by_cell = reach_flow_by_cell(
        output_dir,
        model_name,
        times=times,
        seconds_per_time_unit=seconds_per_solver_time_unit(output_dir, model_name),
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


@pytest.mark.e2e
@pytest.mark.mf6
@pytest.mark.binary
@pytest.mark.slow
def test_the_routed_outlet_carries_the_whole_catchment_release(tmp_path: Path) -> None:
    """The identity the per-cell discharge rests on, on a real MODFLOW run.

    Routing accumulates the release downstream, so what leaves through the
    terminal cells of the graph is everything the catchment released. Stated on
    the SINKS and not on the single busiest cell: this fixture is a symmetric V
    valley whose graph terminates in two cells, each carrying about half, and a
    catchment with one outlet is a special case of this, not the rule.

    Run in process rather than through the CLI on purpose: the pipeline then
    hands over the real model, with the mesh the solver meshed and the catchment
    it delineated, instead of a mesh a test rebuilt from the grid file and could
    get subtly wrong.

    Checked on the no-SFR control, where accumulation is the path a gauge takes;
    with SFR the reach flow is read and nothing is accumulated.

    Note this is NOT ``discharge`` on ``support="domain"``: that observable sums
    the DRAIN record alone, while the release union sums every package crossing
    the aquifer face. The two coincide only when the union is DRN alone, which
    this fixture is not, it holds a lake.
    """
    assert_required_executables(
        require_modflow=False,
        require_modflow6=True,
        require_modpath=False,
        require_mt3dms=False,
    )
    import hydromodpy as hmp
    from hydromodpy.solver.modflow_common.calibration_extractors import (
        extract_release_flux_by_cell_from_cbc,
    )
    from hydromodpy.solver.modflow_common.discharge_routing import (
        route_release_to_discharge,
        routing_graph_for_model,
    )
    from hydromodpy.solver.modflow_common.observable_extraction import (
        excluded_release_records_for_model,
        release_packages_for_model,
    )

    out_path = tmp_path / "no_sfr_identity"
    out_path.mkdir(parents=True, exist_ok=True)
    config_path = out_path / "run_no_sfr.toml"
    config_path.write_text(_config_body(with_sfr=False), encoding="utf-8")

    project = hmp.Project(config_path, headless=True, no_display=True)
    try:
        # Stop before 'derive': that step clears the model registry to free
        # memory, and the model is what carries the mesh this test routes on.
        project.simulate(until_step="extract")
        execution = project.workflow_context.execution
        run_ids = list(execution.models_by_run_id)
        assert run_ids, "the pipeline kept no model for the run"
        run_id = run_ids[0]
        model = execution.models_by_run_id[run_id]
        output_dir = Path(execution.output_dirs_by_run_id[run_id])
        model_name = str(model.model_output_name)

        frame = extract_release_flux_by_cell_from_cbc(
            output_dir,
            model_name,
            packages=release_packages_for_model(model),
            excluded_records=excluded_release_records_for_model(model),
            n_cells=model.solver_mesh.n_cells,
        )
        release = frame.to_numpy()
        assert release.size, "the run released nothing to the surface"

        mask = catchment_cell_mask(model)
        graph = routing_graph_for_model(model)
        routed = route_release_to_discharge(release, graph, catchment_mask=mask)

        inside = np.where(mask[None, :], np.nan_to_num(release, nan=0.0), 0.0)
        expected = inside.sum(axis=1)
        assert float(expected.max()) > 0.0, "no release inside the delineated catchment"

        sinks = np.flatnonzero(np.asarray(graph.downstream) < 0)
        assert sinks.size, "the routing graph terminates nowhere"
        assert routed[:, sinks].sum(axis=1) == pytest.approx(expected, rel=1e-9, abs=1e-12)

        # A gauge on a sink sees at most everything, and strictly less elsewhere.
        assert np.all(routed.max(axis=1) <= expected + 1e-12)
    finally:
        project.close()
