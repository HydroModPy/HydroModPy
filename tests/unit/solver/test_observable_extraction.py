"""The ``release_flux`` observable must read every surface-release package.

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
from hydromodpy.solver.modflow_common import calibration_extractors as extractors
from hydromodpy.solver.modflow_common.observable_extraction import (
    extract_common_modflow_observables,
    release_packages_for_model,
)

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
    *,
    drn: bool = False,
    drn_mover: bool = False,
    sfr: bool = False,
    chd: bool = False,
    stream_cells: list[int] | None = None,
    n_cells: int = NCPL,
) -> SimpleNamespace:
    """A run model declaring the packages the builder actually attached."""
    mask = np.zeros(n_cells, dtype=bool)
    if stream_cells:
        mask[np.asarray(stream_cells, dtype=int)] = True
    # FloPy exposes an MF6 boolean option as an object answering get_data().
    drn_package = SimpleNamespace(mover=SimpleNamespace(get_data=lambda: drn_mover))
    return SimpleNamespace(
        drn=drn_package if drn else None,
        sfr=object() if sfr else None,
        chd=object() if chd else None,
        _stream_support_mask=mask,
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

    frame = release_frame(tmp_path, fake_model(drn=True))

    np.testing.assert_allclose(frame.to_numpy(), [[2.0, 0.0, 0.5, 0.0]])


def test_release_flux_reads_sfr_alone(tmp_path: Path) -> None:
    # Reach on cell 2 gains from the aquifer, reach on cell 3 loses to it: a
    # losing reach releases nothing and must not turn into a negative seepage.
    write_cbc(tmp_path, "model", [{"SFR": [(2, -3.0), (3, 5.0)]}])

    frame = release_frame(tmp_path, fake_model(sfr=True))

    np.testing.assert_allclose(frame.to_numpy(), [[0.0, 3.0, 0.0, 0.0]])


def test_release_flux_sums_an_overlapping_cell_once(tmp_path: Path) -> None:
    write_cbc(
        tmp_path,
        "model",
        [{"DRN": [(1, -2.0), (2, -1.0)], "SFR": [(2, -3.0)]}],
    )

    frame = release_frame(tmp_path, fake_model(drn=True, sfr=True))

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

    frame = release_frame(tmp_path, fake_model(drn=True, drn_mover=True))

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

    frame = release_frame(tmp_path, fake_model(drn=True, drn_mover=True))

    np.testing.assert_allclose(frame.to_numpy(), [[2.0, 4.0, 0.0, 0.0]])


def test_release_flux_ignores_the_mover_record_without_a_mover(tmp_path: Path) -> None:
    """A DRN built without a mover writes no DRN-TO-MVR, and must not demand one."""
    write_cbc(tmp_path, "model", [{"DRN": [(1, -2.0)]}])

    frame = release_frame(tmp_path, fake_model(drn=True))

    np.testing.assert_allclose(frame.to_numpy(), [[2.0, 0.0, 0.0, 0.0]])


def test_release_flux_counts_only_the_stream_role_chd(tmp_path: Path) -> None:
    # Cell 0 is the ocean boundary, cell 2 is the stream boundary. Both are CHD
    # rows in the same package; only the stream one is a release to the surface.
    write_cbc(tmp_path, "model", [{"CHD": [(1, -7.0), (3, -1.5)]}])

    frame = release_frame(tmp_path, fake_model(chd=True, stream_cells=[2]))

    np.testing.assert_allclose(frame.to_numpy(), [[0.0, 0.0, 1.5, 0.0]])


def test_release_flux_refuses_a_declared_package_with_no_budget_record(tmp_path: Path) -> None:
    write_cbc(tmp_path, "model", [{"DRN": [(1, -2.0)]}])

    with pytest.raises(KeyError, match="SFR"):
        release_frame(tmp_path, fake_model(drn=True, sfr=True))


def test_release_packages_refuses_a_model_with_no_release_package() -> None:
    with pytest.raises(RuntimeError, match="release"):
        release_packages_for_model(fake_model(chd=True))


def test_release_flux_keeps_the_time_index(tmp_path: Path) -> None:
    write_cbc(
        tmp_path,
        "model",
        [{"DRN": [(1, -1.0)], "SFR": [(2, -2.0)]}, {"DRN": [(1, -3.0)], "SFR": [(2, -4.0)]}],
    )
    index = pd.DatetimeIndex(["2020-01-01", "2020-01-02"])

    frame = release_frame(tmp_path, fake_model(drn=True, sfr=True), time_index=index)

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
    model = fake_model(drn=True, sfr=True)
    request = ObservableRequest(id="net", name="release_flux", support="cells")

    served, unserved = extract_common_modflow_observables(tmp_path, "model", model, [request])

    assert unserved == []
    np.testing.assert_allclose(served["net"].values, [[2.0, 3.0, 1.0, 0.0]])
