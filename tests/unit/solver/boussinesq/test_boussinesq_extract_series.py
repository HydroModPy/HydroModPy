"""Cover ``BoussinesqFlowAdapter.observables``.

The Boussinesq adapter reads the simulated observables from the
``_boussinesq_state_history.npz`` file written by ``post_processing``. These
tests exercise the contract directly against a synthetic state-history file:
they fix the schema (shape, sign convention, station cell mapping, units)
without depending on a full Boussinesq solve.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import box

from hydromodpy.core.contracts.observables import ObservableRequest
from hydromodpy.core.exceptions import ObservableNotAvailableError, SolverError
from hydromodpy.model.domain.geometry import CatchmentGeometry
from hydromodpy.model.model import Geometry
from hydromodpy.results.derive.catchment_aggregation import catchment_support
from hydromodpy.solver.base.plan import SolverRun
from hydromodpy.solver.boussinesq.adapter import BoussinesqFlowAdapter, _published_support
from tests._helpers.model_factory import make_model

from ._solver_runs import solver_run_of


def _write_state_history(
    output_dir: Path,
    *,
    head_history: np.ndarray,
    drainage_history: np.ndarray | None = None,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload: dict[str, np.ndarray] = {
        "head_history_m": np.asarray(head_history, dtype=float),
    }
    if drainage_history is not None:
        payload["drainage_flux_history_m3_s"] = np.asarray(drainage_history, dtype=float)
    np.savez(output_dir / "_boussinesq_state_history.npz", **payload)


def _discharge_request() -> ObservableRequest:
    return ObservableRequest(id="q", name="discharge", support="domain")


def test_extract_discharge_returns_sum_per_timestep(tmp_path: Path) -> None:
    drainage = np.array(
        [
            [1.0, 2.0, 0.0],
            [0.5, 0.0, 1.5],
        ],
        dtype=float,
    )
    head = np.full((2, 3), 5.0, dtype=float)
    _write_state_history(tmp_path, head_history=head, drainage_history=drainage)
    run = solver_run_of(tmp_path)

    served = BoussinesqFlowAdapter().observables(run, [_discharge_request()])

    assert set(served) == {"q"}
    result = served["q"]
    assert result.request_id == "q"
    assert isinstance(result.values, np.ndarray)
    assert result.values.shape == (2,)
    np.testing.assert_array_equal(result.values, np.array([3.0, 2.0]))
    assert result.units == "m3 s-1"


def test_extract_discharge_ignores_negative_recharge_terms(tmp_path: Path) -> None:
    drainage = np.array([[1.0, -2.0, 3.0]], dtype=float)
    head = np.full((1, 3), 5.0, dtype=float)
    _write_state_history(tmp_path, head_history=head, drainage_history=drainage)
    run = solver_run_of(tmp_path)

    served = BoussinesqFlowAdapter().observables(run, [_discharge_request()])

    np.testing.assert_array_equal(served["q"].values, np.array([4.0]))


def test_extract_discharge_aligns_with_time_index(tmp_path: Path) -> None:
    drainage = np.array([[1.0], [2.0], [3.0]], dtype=float)
    head = np.full((3, 1), 5.0, dtype=float)
    _write_state_history(tmp_path, head_history=head, drainage_history=drainage)
    run = solver_run_of(tmp_path)

    time_index = pd.DatetimeIndex(["2020-01-01", "2020-01-02", "2020-01-03"])
    served = BoussinesqFlowAdapter().observables(run, [_discharge_request()], time_index=time_index)

    result = served["q"]
    assert isinstance(result.times, pd.DatetimeIndex)
    assert result.times.tolist() == time_index.tolist()
    assert result.values.size == len(time_index)


def test_extract_head_reads_history_at_cell(tmp_path: Path) -> None:
    head = np.array(
        [
            [10.0, 11.0, 12.0],
            [10.5, 11.5, 12.5],
        ],
        dtype=float,
    )
    _write_state_history(tmp_path, head_history=head)
    run = solver_run_of(tmp_path)

    request = ObservableRequest(id="P1", name="head", support="cell", cell=(0, 0, 1))
    served = BoussinesqFlowAdapter().observables(run, [request])

    result = served["P1"]
    assert result.request_id == "P1"
    np.testing.assert_array_equal(result.values, np.array([11.0, 11.5]))
    assert result.units == "m"


def test_head_request_on_cell_support_requires_a_cell() -> None:
    with pytest.raises(ValueError, match="needs a .* cell"):
        ObservableRequest(id="P1", name="head", support="cell")


def test_extract_head_rejects_non_zero_layer(tmp_path: Path) -> None:
    head = np.array([[1.0, 2.0]], dtype=float)
    _write_state_history(tmp_path, head_history=head)
    run = solver_run_of(tmp_path)

    request = ObservableRequest(id="P1", name="head", support="cell", cell=(1, 0, 0))
    with pytest.raises(ValueError, match="cell_id"):
        BoussinesqFlowAdapter().observables(run, [request])


def test_extract_head_serves_several_stations_in_one_call(tmp_path: Path) -> None:
    head = np.array(
        [
            [1.0, 2.0],
            [1.5, 2.5],
        ],
        dtype=float,
    )
    _write_state_history(tmp_path, head_history=head)
    run = solver_run_of(tmp_path)

    requests = [
        ObservableRequest(id="P1", name="head", support="cell", cell=(0, 0, 0)),
        ObservableRequest(id="P2", name="head", support="cell", cell=(0, 0, 1)),
    ]
    served = BoussinesqFlowAdapter().observables(run, requests)

    assert set(served) == {"P1", "P2"}
    assert served["P1"].request_id == "P1"
    assert served["P2"].request_id == "P2"
    np.testing.assert_array_equal(served["P1"].values, np.array([1.0, 1.5]))
    np.testing.assert_array_equal(served["P2"].values, np.array([2.0, 2.5]))
    assert served["P1"].units == "m"
    assert served["P2"].units == "m"


def test_extract_unknown_observable_raises_not_available(tmp_path: Path) -> None:
    head = np.array([[1.0, 2.0]], dtype=float)
    _write_state_history(tmp_path, head_history=head)
    run = solver_run_of(tmp_path)

    request = ObservableRequest(id="c", name="concentration", support="domain")
    with pytest.raises(ObservableNotAvailableError, match="concentration"):
        BoussinesqFlowAdapter().observables(run, [request])


def test_extract_raises_when_no_output_dir_recorded() -> None:
    with pytest.raises(SolverError, match="No solver output recorded"):
        BoussinesqFlowAdapter().observables(solver_run_of(None), [_discharge_request()])


def _half_of_a_square(tmp_path: Path) -> tuple[np.ndarray, np.ndarray, Path]:
    """Return a row of four cells and a watershed file that covers the first two."""
    vertices = np.array([[float(i), float(j)] for j in (0, 1) for i in range(5)])
    faces = np.array([[i, i + 1, i + 6, i + 5] for i in range(4)])
    watershed = tmp_path / "watershed.gpkg"
    gpd.GeoDataFrame(geometry=[box(-1.0, -1.0, 2.0, 2.0)], crs="EPSG:2154").to_file(watershed)
    return vertices, faces, watershed


def _run_on_a_watershed(
    output_dir: Path, vertices: np.ndarray, faces: np.ndarray, watershed: Path, *, crs: str | None
) -> SolverRun:
    cell_mesh = SimpleNamespace(
        mesh=SimpleNamespace(vertices=vertices),
        geometry=SimpleNamespace(padded_connectivity=faces),
    )
    return solver_run_of(
        output_dir,
        model=make_model(
            geometry=Geometry(
                cells=None,
                domain=None,
                catchment=CatchmentGeometry.from_geographic(
                    SimpleNamespace(watershed_shp=str(watershed)), crs=crs
                ),
            )
        ),
        solver_model=SimpleNamespace(mesh=SimpleNamespace(cell_mesh=cell_mesh)),
    )


def test_a_trial_serves_the_discharge_of_the_cells_the_run_publishes(tmp_path: Path) -> None:
    vertices, faces, watershed = _half_of_a_square(tmp_path)
    drainage = np.array([[1.0, 2.0, 4.0, 8.0]])
    _write_state_history(tmp_path, head_history=np.full((1, 4), 5.0), drainage_history=drainage)
    run = _run_on_a_watershed(tmp_path, vertices, faces, watershed, crs="EPSG:2154")

    served = BoussinesqFlowAdapter().observables(run, [_discharge_request()])

    np.testing.assert_array_equal(served["q"].values, [3.0])


def test_a_trial_and_its_run_read_one_mask(tmp_path: Path) -> None:
    vertices, faces, watershed = _half_of_a_square(tmp_path)
    run = _run_on_a_watershed(tmp_path, vertices, faces, watershed, crs="EPSG:2154")
    store = SimpleNamespace(
        read_geographic_feature=lambda sim_id, name: gpd.read_file(watershed),
    )
    group = {
        "mesh": {"vertices": vertices, "face_node_connectivity": faces},
        "crs": SimpleNamespace(attrs={"crs_wkt": "EPSG:2154"}),
    }
    published = catchment_support(store, "sim", group, np.ones(4, dtype=bool))

    np.testing.assert_array_equal(_published_support(run), published)


def test_a_run_without_a_declared_crs_stays_on_the_whole_domain(tmp_path: Path) -> None:
    vertices, faces, watershed = _half_of_a_square(tmp_path)
    run = _run_on_a_watershed(tmp_path, vertices, faces, watershed, crs=None)

    assert _published_support(run) is None


def test_the_adapter_declares_what_a_trial_can_read() -> None:
    declared = {
        support.name: support
        for support in BoussinesqFlowAdapter().declared_observables(frozenset({"drainage"}))
    }

    assert {name for name, support in declared.items() if support.is_servable_now} == {
        "head",
        "discharge",
    }
    assert {name for name, support in declared.items() if support.can_never_be_served} == {
        "release_flux",
        "stage",
        "routed_discharge",
    }


def test_the_answer_of_a_trial_never_depends_on_the_active_conditions() -> None:
    adapter = BoussinesqFlowAdapter()

    assert adapter.declared_observables(frozenset()) == adapter.declared_observables(
        frozenset({"stream", "ocean"})
    )


def test_the_adapter_locates_nothing_on_a_run_with_no_cell_mesh(tmp_path: Path) -> None:
    adapter = BoussinesqFlowAdapter()
    bundle_run = solver_run_of(tmp_path, solver_model=SimpleNamespace(mesh=SimpleNamespace()))

    assert adapter.locate_cell(bundle_run, 1.0, 1.0) is None
    assert adapter.locate_cell(solver_run_of(tmp_path), 1.0, 1.0) is None
    assert adapter.top_active_layer(bundle_run, 0, 3) == 0


def test_cleanup_removes_the_folder_of_the_run_and_forgives_a_run_with_none(
    tmp_path: Path,
) -> None:
    adapter = BoussinesqFlowAdapter()
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    (scratch / "_boussinesq_summary.json").write_text("{}", encoding="utf-8")

    adapter.cleanup(solver_run_of(scratch))
    adapter.cleanup(solver_run_of(None))

    assert not scratch.exists()
