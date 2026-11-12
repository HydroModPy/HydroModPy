"""The ``release_flux`` observable must read every surface-release package.

The per-cell discharge is routed on the descent D of the build
(``routing_graph_for_model``), at the flat index of a cell (``flat_cell_index``),
and the discharge of the catchment takes the drain budget only when the network
does not route the drainage.

The MF6 builder zeroes the DRN rows on the cells an SFR reach or a stream-role
CHD already owns, so a DRN-only reading is empty exactly where a stream-network
calibration aims. These tests write a real MODFLOW 6 compact budget file (imeth
6 list records) and read it back through FloPy, so the record lookup, the
node-to-cell mapping and the sign convention are all exercised for real.
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


def test_release_flux_reads_drn_alone(tmp_path: Path) -> None:
    write_cbc(tmp_path, "model", [{"DRN": [(1, -2.0), (3, -0.5)]}])

    frame = release_frame(tmp_path, fake_model(tmp_path, drn=True))

    np.testing.assert_allclose(frame.to_numpy(), [[2.0, 0.0, 0.5, 0.0]])


def test_release_flux_reads_sfr_alone(tmp_path: Path) -> None:
    # Reach on cell 2 gains from the aquifer, reach on cell 3 loses to it: a
    # losing reach releases nothing and must not turn into a negative seepage.
    write_cbc(tmp_path, "model", [{"SFR": [(2, -3.0), (3, 5.0)]}])

    frame = release_frame(tmp_path, fake_model(tmp_path, sfr=True))

    np.testing.assert_allclose(frame.to_numpy(), [[0.0, 3.0, 0.0, 0.0]])


def test_release_flux_sums_an_overlapping_cell_once(tmp_path: Path) -> None:
    write_cbc(
        tmp_path,
        "model",
        [{"DRN": [(1, -2.0), (2, -1.0)], "SFR": [(2, -3.0)]}],
    )

    frame = release_frame(tmp_path, fake_model(tmp_path, drn=True, sfr=True))

    assert list(frame.columns) == [0, 1, 2, 3]
    np.testing.assert_allclose(frame.to_numpy(), [[2.0, 4.0, 0.0, 0.0]])


def test_release_flux_adds_the_drain_routed_to_the_mover(tmp_path: Path) -> None:
    """route_drainage: DRN and DRN-TO-MVR are disjoint halves of one seepage.

    MF6 subtracts the moved flux from the DRN term of the model budget, so a
    hillslope cell whose drainage is routed to a reach reads zero in DRN and
    carries its whole release in DRN-TO-MVR. On the Chèze reference run, 11709
    of the 14818 releasing cells are in that case.
    """
    write_cbc(
        tmp_path,
        "model",
        [{"DRN": [(1, -0.5)], "DRN-TO-MVR": [(1, -1.5), (2, -4.0)]}],
    )

    frame = release_frame(tmp_path, fake_model(tmp_path, drn=True, drn_mover=True))

    np.testing.assert_allclose(frame.to_numpy(), [[2.0, 4.0, 0.0, 0.0]])


def test_release_flux_keeps_drn_apart_from_drn_to_mvr(tmp_path: Path) -> None:
    """FloPy resolves a budget record by substring, so ``DRN`` also matches
    ``DRN-TO-MVR`` and the first of the two in file order wins. Written in that
    order, a stripped lookup reads the mover array twice and doubles the release.
    """
    write_cbc(
        tmp_path,
        "model",
        [{"DRN-TO-MVR": [(1, -1.5), (2, -4.0)], "DRN": [(1, -0.5)]}],
    )

    frame = release_frame(tmp_path, fake_model(tmp_path, drn=True, drn_mover=True))

    np.testing.assert_allclose(frame.to_numpy(), [[2.0, 4.0, 0.0, 0.0]])


def test_release_flux_ignores_the_mover_record_without_a_mover(tmp_path: Path) -> None:
    """A DRN built without a mover writes no DRN-TO-MVR, and must not demand one."""
    write_cbc(tmp_path, "model", [{"DRN": [(1, -2.0)]}])

    frame = release_frame(tmp_path, fake_model(tmp_path, drn=True))

    np.testing.assert_allclose(frame.to_numpy(), [[2.0, 0.0, 0.0, 0.0]])


def test_release_flux_counts_only_the_stream_role_chd(tmp_path: Path) -> None:
    # Cell 0 is the ocean boundary, cell 2 is the stream boundary. Both are CHD
    # rows in the same package; only the stream one is a release to the surface.
    write_cbc(tmp_path, "model", [{"CHD": [(1, -7.0), (3, -1.5)]}])

    frame = release_frame(tmp_path, fake_model(tmp_path, chd=True, stream_cells=[2]))

    np.testing.assert_allclose(frame.to_numpy(), [[0.0, 0.0, 1.5, 0.0]])


def test_release_flux_refuses_a_declared_package_with_no_budget_record(tmp_path: Path) -> None:
    write_cbc(tmp_path, "model", [{"DRN": [(1, -2.0)]}])

    with pytest.raises(ObservableNotAvailableError, match="SFR"):
        release_frame(tmp_path, fake_model(tmp_path, drn=True, sfr=True))


def test_release_packages_refuses_a_model_with_no_release_package(tmp_path: Path) -> None:
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


def test_release_flux_observable_unions_sfr_with_drn(tmp_path: Path) -> None:
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


# -- The graph and the cell a per-cell discharge is read on ----------------------
#
# The graph was once the steepest descent of the unfilled top, rebuilt per
# extraction with a per-output neighborhood. It is now the receivers of D, so a
# diagonal talweg is followed on a quad mesh.


def _descent_model(top: np.ndarray) -> SimpleNamespace:
    """A structured model whose top D is built on, as the build does."""
    nrow, ncol = top.shape
    mesh = solver_mesh_from_structured_arrays(
        nrow=nrow, ncol=ncol, top=top, botm=np.full((1, nrow, ncol), -10.0)
    )
    descent = build_solver_mesh_descent(mesh, lake_cells_by_lake={}, base_level_mask=None)
    return SimpleNamespace(solver_mesh=mesh, descent=descent)


def _receiver_pairs(graph) -> set[tuple[int, int]]:
    return {
        tuple(sorted((cell, int(receiver))))
        for cell, receiver in enumerate(graph.downstream)
        if receiver >= 0
    }


def test_a_cell_outside_the_mesh_is_refused() -> None:
    model = _descent_model(np.arange(9, dtype=float).reshape(3, 3))

    with pytest.raises(ValueError, match="outside"):
        flat_cell_index(model, (0, 9, 9))


def test_a_model_without_a_descent_says_so() -> None:
    with pytest.raises(ValueError, match="carries none"):
        routing_graph_for_model(SimpleNamespace(solver_mesh=None))


# The routed discharge takes the drain budget only when the network does not route the drainage.
#
# With ``route_drainage`` the hillslope drainage reaches the network, so the routed
# series is the catchment discharge and already holds the runoff. Without it the
# drainage stays in DRAIN, the routed series would leave it out, and the discharge
# is the routed series plus the drain budget of the catchment.

_INDEX = pd.date_range("2000-01-01", periods=3, freq="D")


_ROUTED = pd.Series([1.0, 1.0, 1.0], index=_INDEX)


_DRAIN = pd.Series([0.25, 0.25, 0.25], index=_INDEX)


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


def test_a_network_that_routes_the_drainage_serves_the_routed_series(monkeypatch) -> None:
    result, calls = _serve(_network_model(route_drainage=True), monkeypatch)

    assert calls == ["routed"]
    assert result.includes_runoff is True
    np.testing.assert_allclose(result.values, _ROUTED.to_numpy())


def test_a_network_that_does_not_say_routes_the_drainage(monkeypatch) -> None:
    result, calls = _serve(_network_model(route_drainage=None), monkeypatch)

    assert calls == ["routed"]
    assert result.includes_runoff is True


def test_a_network_that_keeps_the_drainage_out_adds_the_drain_budget(monkeypatch) -> None:
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
def test_a_lake_without_a_network_adds_the_drain_budget(monkeypatch, inputs) -> None:
    result, calls = _serve(SimpleNamespace(inputs=inputs), monkeypatch)

    assert calls == ["routed", "drain"]
    assert result.includes_runoff is True
    np.testing.assert_allclose(result.values, (_ROUTED + _DRAIN).to_numpy())


def test_a_drain_budget_that_cannot_be_read_leaves_the_routed_series(monkeypatch) -> None:
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
