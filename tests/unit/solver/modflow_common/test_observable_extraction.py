"""Observables read from a MODFLOW 6 run: release flux per cell and catchment discharge (m3/s).

The release flux unions every surface-release package, because the builder zeroes the DRN rows on
cells an SFR reach or a stream-role CHD owns. The tests write a real compact budget file (imeth 6
list records) and read it back through FloPy. Per-cell discharge is routed on the descent D of the
build, and the catchment discharge adds the drain budget only when the network does not route it.
"""

from __future__ import annotations

import struct
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.core.contracts.observables import ObservableRequest
from hydromodpy.core.exceptions import ObservableNotAvailableError
from hydromodpy.model.boundaries.boundary_condition_registry import BoundaryConditionBundle
from hydromodpy.solver.modflow_common import calibration_extractors as extractors
from hydromodpy.solver.modflow_common import observable_extraction as extraction
from hydromodpy.solver.modflow_common.boundary_roles import write_constant_head_roles
from hydromodpy.solver.modflow_common.flow_directions import build_solver_mesh_descent
from hydromodpy.solver.modflow_common.observable_extraction import (
    excluded_release_records_for_model,
    extract_common_modflow_observables,
    flat_cell_index,
    release_packages_for_model,
    routing_graph_for_model,
)
from tests._helpers.model_factory import make_model
from tests._helpers.solver_meshes import solver_mesh_from_structured_arrays

NCPL = 4


def _pad16(text: str) -> bytes:
    return f"{text:<16}".encode("ascii")[:16]


def _write_budget_record(
    fh,
    *,
    kper: int,
    text: str,
    ncpl: int,
    totim: float,
    rows: list[tuple[int, float]],
) -> None:
    """Append one MODFLOW 6 compact list record (imeth 6) to an open CBC."""
    fh.write(struct.pack("<ii", 1, kper + 1))
    fh.write(_pad16(f"{text:>16}"))
    fh.write(struct.pack("<iii", ncpl, 1, -1))
    fh.write(struct.pack("<iddd", 6, 1.0, 1.0, totim))
    for name in ("GWFMODEL", text.strip(), "GWFMODEL", text.strip()):
        fh.write(_pad16(name))
    fh.write(struct.pack("<i", 1))
    fh.write(struct.pack("<i", len(rows)))
    for node, q in rows:
        fh.write(struct.pack("<iid", int(node), 0, float(q)))


def write_cbc(
    output_dir: Path,
    model_name: str,
    steps: list[dict[str, list[tuple[int, float]]]],
    *,
    ncpl: int = NCPL,
) -> Path:
    """Write a CBC holding one record per package and per timestep.

    ``steps`` is one mapping per timestep, from budget record name to the
    ``(node, q)`` rows of that package. ``node`` is 1-based as MODFLOW writes
    it, and ``q`` is signed as seen by the groundwater model: negative means
    the aquifer loses water to the boundary.
    """
    path = output_dir / f"{model_name}.cbc"
    with path.open("wb") as fh:
        for kper, records in enumerate(steps):
            for text, rows in records.items():
                _write_budget_record(
                    fh,
                    kper=kper,
                    text=text,
                    ncpl=ncpl,
                    totim=float(kper + 1),
                    rows=rows,
                )
    return path


def fake_model(
    directory: Path,
    *,
    drn: bool = False,
    drn_mover: bool = False,
    sfr: bool = False,
    chd: bool = False,
    stream_cells: list[int] | None = None,
    n_cells: int = NCPL,
) -> SimpleNamespace:
    """A run model declaring the packages the builder actually attached.

    The stream role of a constant head is read back from the sidecar the build
    leaves in the solver directory, so a model carrying a CHD writes one the
    same way the MODFLOW 6 build does.
    """
    mask = np.zeros(n_cells, dtype=bool)
    if stream_cells:
        mask[np.asarray(stream_cells, dtype=int)] = True
    if chd:
        write_constant_head_roles(
            directory,
            "model",
            n_cells=n_cells,
            masks_by_role={"stream": mask},
        )
    # FloPy exposes an MF6 boolean option as an object answering get_data().
    drn_package = SimpleNamespace(mover=SimpleNamespace(get_data=lambda: drn_mover))
    return SimpleNamespace(
        drn=drn_package if drn else None,
        sfr=object() if sfr else None,
        chd=object() if chd else None,
        full_path=str(directory),
        model_output_name="model",
        solver_mesh=SimpleNamespace(n_cells=n_cells),
    )


def release_frame(output_dir: Path, model: SimpleNamespace, **kwargs) -> pd.DataFrame:
    return extractors.extract_release_flux_by_cell_from_cbc(
        output_dir,
        "model",
        packages=release_packages_for_model(model),
        n_cells=NCPL,
        **kwargs,
    )


# One row per budget file: the records of the single step as (1-based node, q in m3/s), the
# packages the model declares, and the release per cell (positive, m3/s) on the four cells. A
# gaining reach (q < 0) releases and a losing reach (q > 0) releases nothing.
RELEASES = [
    pytest.param({"DRN": [(1, -2.0), (3, -0.5)]}, {"drn": True}, [2.0, 0.0, 0.5, 0.0], id="drn"),
    pytest.param(
        {"SFR": [(2, -3.0), (3, 5.0)]}, {"sfr": True}, [0.0, 3.0, 0.0, 0.0], id="sfr, losing reach"
    ),
    pytest.param(
        {"DRN": [(1, -2.0), (2, -1.0)], "SFR": [(2, -3.0)]},
        {"drn": True, "sfr": True},
        [2.0, 4.0, 0.0, 0.0],
        id="a cell in two packages is summed",
    ),
    # MF6 subtracts the moved flux from the DRN term, so a hillslope cell routed to a reach reads
    # zero in DRN and carries its whole release in DRN-TO-MVR.
    pytest.param(
        {"DRN": [(1, -0.5)], "DRN-TO-MVR": [(1, -1.5), (2, -4.0)]},
        {"drn": True, "drn_mover": True},
        [2.0, 4.0, 0.0, 0.0],
        id="drain routed to the mover",
    ),
    # FloPy matches a record by substring, so DRN also matches DRN-TO-MVR and the first in file
    # order wins. Written in this order, a stripped lookup reads the mover twice.
    pytest.param(
        {"DRN-TO-MVR": [(1, -1.5), (2, -4.0)], "DRN": [(1, -0.5)]},
        {"drn": True, "drn_mover": True},
        [2.0, 4.0, 0.0, 0.0],
        id="mover written before DRN",
    ),
    pytest.param(
        {"DRN": [(1, -2.0)]}, {"drn": True}, [2.0, 0.0, 0.0, 0.0], id="no mover and no record"
    ),
    # Cell 0 is the ocean boundary and cell 2 the stream boundary, both CHD rows of one package.
    # Only the stream one is a release to the surface.
    pytest.param(
        {"CHD": [(1, -7.0), (3, -1.5)]},
        {"chd": True, "stream_cells": [2]},
        [0.0, 0.0, 1.5, 0.0],
        id="only the stream role of a CHD",
    ),
]


@pytest.mark.parametrize(("records", "packages", "expected"), RELEASES)
def test_release_flux(tmp_path: Path, records, packages, expected) -> None:
    write_cbc(tmp_path, "model", [records])

    frame = release_frame(tmp_path, fake_model(tmp_path, **packages))

    np.testing.assert_allclose(frame.to_numpy(), [expected])


def test_release_flux_columns(tmp_path: Path) -> None:
    write_cbc(tmp_path, "model", [{"DRN": [(1, -2.0)], "SFR": [(2, -3.0)]}])

    frame = release_frame(tmp_path, fake_model(tmp_path, drn=True, sfr=True))

    assert list(frame.columns) == [0, 1, 2, 3]


def test_release_needs_declared_record(tmp_path: Path) -> None:
    write_cbc(tmp_path, "model", [{"DRN": [(1, -2.0)]}])

    with pytest.raises(ObservableNotAvailableError, match="SFR"):
        release_frame(tmp_path, fake_model(tmp_path, drn=True, sfr=True))


def test_model_without_release_package(tmp_path: Path) -> None:
    with pytest.raises(ObservableNotAvailableError, match="release"):
        release_packages_for_model(fake_model(tmp_path, chd=True))


def test_release_flux_keeps_the_time_index(tmp_path: Path) -> None:
    write_cbc(
        tmp_path,
        "model",
        [{"DRN": [(1, -1.0)], "SFR": [(2, -2.0)]}, {"DRN": [(1, -3.0)], "SFR": [(2, -4.0)]}],
    )
    index = pd.DatetimeIndex(["2020-01-01", "2020-01-02"])

    frame = release_frame(tmp_path, fake_model(tmp_path, drn=True, sfr=True), time_index=index)

    assert list(frame.index) == list(index)
    np.testing.assert_allclose(frame.to_numpy(), [[1.0, 2.0, 0.0, 0.0], [3.0, 4.0, 0.0, 0.0]])


def test_release_observable_unions_sfr_drn(tmp_path: Path) -> None:
    """The defect, end to end: DRN is zeroed on the reach cells by the builder.

    The seepage the criterion scores lives in the SFR record; a DRN-only
    reading returns dry land on the very cells the calibration aims at.
    """
    write_cbc(
        tmp_path,
        "model",
        [{"DRN": [(1, -2.0)], "SFR": [(2, -3.0), (3, -1.0)]}],
    )
    model = fake_model(tmp_path, drn=True, sfr=True)
    request = ObservableRequest(id="net", name="release_flux", support="cells")

    served, unserved = extract_common_modflow_observables(tmp_path, "model", model, [request])

    assert unserved == []
    np.testing.assert_allclose(served["net"].values, [[2.0, 3.0, 1.0, 0.0]])


def test_chd_without_role_excluded() -> None:
    excluded = excluded_release_records_for_model(SimpleNamespace(chd=object(), drn=object()))

    assert {"CHD", "CONSTANT HEAD"} <= set(excluded)
    assert "stream role" in excluded["CHD"]


def test_chd_with_role_kept(tmp_path: Path) -> None:
    write_constant_head_roles(
        tmp_path, "model", n_cells=3, masks_by_role={"stream": np.array([False, True, False])}
    )
    model = SimpleNamespace(
        chd=object(), drn=object(), full_path=str(tmp_path), model_output_name="model"
    )

    excluded = excluded_release_records_for_model(model)

    assert "CHD" not in excluded and "CONSTANT HEAD" not in excluded


def test_drain_mover_is_never_ruled_out() -> None:
    # DRN-TO-MVR takes water out of the aquifer, so it belongs to the union.
    assert "DRN-TO-MVR" not in excluded_release_records_for_model(SimpleNamespace(drn=object()))


def _descent_model(top: np.ndarray) -> SimpleNamespace:
    """A structured model whose top D is built on, as the build does."""
    nrow, ncol = top.shape
    mesh = solver_mesh_from_structured_arrays(
        nrow=nrow, ncol=ncol, top=top, botm=np.full((1, nrow, ncol), -10.0)
    )
    descent = build_solver_mesh_descent(mesh, lake_cells_by_lake={}, base_level_mask=None)
    return SimpleNamespace(solver_mesh=mesh, descent=descent)


def test_cell_outside_mesh_refused() -> None:
    model = _descent_model(np.arange(9, dtype=float).reshape(3, 3))

    with pytest.raises(ValueError, match="outside"):
        flat_cell_index(model, (0, 9, 9))


def test_model_without_descent_refused() -> None:
    with pytest.raises(ValueError, match="carries none"):
        routing_graph_for_model(SimpleNamespace(solver_mesh=None))


# The routed discharge takes the drain budget only when the network does not route the drainage.
# With ``route_drainage`` the hillslope drainage reaches the network, so the routed series is the
# catchment discharge and already holds the runoff. Without it the drainage stays in DRAIN, the
# routed series leaves it out, and the discharge is the routed series plus the drain budget.

_INDEX = pd.date_range("2000-01-01", periods=3, freq="D")
_ROUTED = pd.Series([1.0, 1.0, 1.0], index=_INDEX)  # m3/s
_DRAIN = pd.Series([0.25, 0.25, 0.25], index=_INDEX)  # m3/s


def _network_model(*, route_drainage: bool | None) -> SimpleNamespace:
    payload = {} if route_drainage is None else {"route_drainage": route_drainage}
    inputs = make_model(
        boundaries=BoundaryConditionBundle(conditions={}, active_ids=("sfr",)),
        sfr={"net": payload},
    )
    return SimpleNamespace(inputs=inputs)


def _serve(model: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> tuple[object, list[str]]:
    calls: list[str] = []

    def routed_reader(output_dir, model_name, time_index):
        calls.append("routed")
        return _ROUTED

    def drain_sum(output_dir, model_name, time_index, *, catchment_mask):
        calls.append("drain")
        return _DRAIN

    monkeypatch.setattr(extraction, "extract_discharge_from_cbc", drain_sum)
    monkeypatch.setattr(extraction, "catchment_cell_mask", lambda model: np.ones(4, dtype=bool))
    request = ObservableRequest(id="catchment", name="discharge", support="domain")
    served, unserved = extraction.extract_common_modflow_observables(
        Path("."),
        "m",
        model,
        [request],
        time_index=_INDEX,
        routed_discharge_reader=routed_reader,
    )
    assert unserved == []
    return served["catchment"], calls


def test_routed_drainage_series(monkeypatch) -> None:
    result, calls = _serve(_network_model(route_drainage=True), monkeypatch)

    assert calls == ["routed"]
    assert result.includes_runoff is True
    np.testing.assert_allclose(result.values, _ROUTED.to_numpy())


def test_unspecified_routing_default(monkeypatch) -> None:
    result, calls = _serve(_network_model(route_drainage=None), monkeypatch)

    assert calls == ["routed"]
    assert result.includes_runoff is True


def test_unrouted_drainage_adds_budget(monkeypatch) -> None:
    result, calls = _serve(_network_model(route_drainage=False), monkeypatch)

    assert calls == ["routed", "drain"]
    assert result.includes_runoff is True
    np.testing.assert_allclose(result.values, (_ROUTED + _DRAIN).to_numpy())


@pytest.mark.parametrize(
    "inputs",
    [
        make_model(boundaries=BoundaryConditionBundle(conditions={}, active_ids=("lake",))),
        make_model(
            boundaries=BoundaryConditionBundle(conditions={}, active_ids=("lake",)),
            sfr={"net": {}},
        ),
    ],
    ids=["no_network", "a_network_not_active"],
)
def test_lake_adds_drain_budget(monkeypatch, inputs) -> None:
    result, calls = _serve(SimpleNamespace(inputs=inputs), monkeypatch)

    assert calls == ["routed", "drain"]
    assert result.includes_runoff is True
    np.testing.assert_allclose(result.values, (_ROUTED + _DRAIN).to_numpy())


def test_unreadable_drain_budget(monkeypatch) -> None:
    def refuse(*args, **kwargs):
        raise NotImplementedError("a mover record is in the budget")

    monkeypatch.setattr(extraction, "extract_discharge_from_cbc", refuse)
    monkeypatch.setattr(extraction, "catchment_cell_mask", lambda model: np.ones(4, dtype=bool))
    request = ObservableRequest(id="catchment", name="discharge", support="domain")
    served, _ = extraction.extract_common_modflow_observables(
        Path("."),
        "m",
        _network_model(route_drainage=False),
        [request],
        time_index=_INDEX,
        routed_discharge_reader=lambda *args: _ROUTED,
    )

    np.testing.assert_allclose(served["catchment"].values, _ROUTED.to_numpy())
