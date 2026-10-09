"""The stored ``release_flux`` field and the calibration criterion sum the same paths.

Before, a lake entered the criterion and the field alike, but a constant head
with the stream role entered the criterion only: the persisted ``constant_head``
budget carries no role, so the field could not tell a stream from a model edge.
The extractor now writes the stream-role share as its own budget term, and the
field reads it.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from hydromodpy.core.field_routing import (
    RELEASE_BUDGET_KEYS,
    STREAM_CONSTANT_HEAD_BUDGET,
    release_flux_stack,
)
from hydromodpy.solver.modflow6.extractors.cbc_reader import CbcRecord
from hydromodpy.solver.modflow6.extractors.flow import (
    Modflow6OutputAdapter,
    _stream_constant_head_mask,
)
from hydromodpy.solver.modflow_common.boundary_roles import write_constant_head_roles
from hydromodpy.solver.modflow_common.budget_components import canonical_budget_component
from hydromodpy.solver.modflow_common.observable_extraction import release_packages_for_model

N_CELLS = 4
STREAM = np.array([False, False, True, False])
OCEAN = np.array([True, False, False, False])


def _write_roles(directory: Path) -> None:
    write_constant_head_roles(
        directory, "nancon", n_cells=N_CELLS, masks_by_role={"ocean": OCEAN, "stream": STREAM}
    )


def _budget_key(package) -> str:
    """The persisted budget term that carries one criterion package."""
    if package.cell_mask is not None:
        return STREAM_CONSTANT_HEAD_BUDGET
    return canonical_budget_component(package.record_aliases[0])


def test_every_criterion_package_has_its_term_in_the_field(tmp_path: Path) -> None:
    _write_roles(tmp_path)
    mover = SimpleNamespace(get_data=lambda: True)
    model = SimpleNamespace(
        drn=SimpleNamespace(mover=mover),
        sfr=object(),
        lak=object(),
        chd=object(),
        full_path=str(tmp_path),
        model_output_name="nancon",
    )

    criterion = {_budget_key(package) for package in release_packages_for_model(model)}

    assert criterion == {
        "drain",
        "drain_to_mover",
        "stream",
        "lake",
        STREAM_CONSTANT_HEAD_BUDGET,
    }
    # The field reads the same terms, plus the Boussinesq surface excess, the
    # only path out of a solver the criterion extractor never reads.
    assert set(RELEASE_BUDGET_KEYS) == criterion | {"surface_excess"}


def test_the_field_counts_the_stream_constant_head_and_not_the_ocean() -> None:
    leaving = -1.0
    budget = {
        "drain": np.array([[[leaving * 1.0, 0.0, 0.0, 0.0]]]),
        "constant_head": np.array([[[leaving * 7.0, 0.0, leaving * 3.0, 0.0]]]),
        STREAM_CONSTANT_HEAD_BUDGET: np.array([[[0.0, 0.0, leaving * 3.0, 0.0]]]),
    }

    out = release_flux_stack(budget, n_cells=N_CELLS, start=0, stop=1)

    np.testing.assert_allclose(out[0], [1.0, 0.0, 3.0, 0.0])


def test_the_mask_is_read_from_the_run_directory(tmp_path: Path) -> None:
    _write_roles(tmp_path)

    np.testing.assert_array_equal(
        _stream_constant_head_mask(tmp_path, "nancon", n_cells=N_CELLS), STREAM
    )
    assert _stream_constant_head_mask(tmp_path, "other", n_cells=N_CELLS) is None
    assert _stream_constant_head_mask(tmp_path, "nancon", n_cells=9) is None


class _FakeCbb:
    def __init__(self, records: list[tuple[int, int, str, Any]]):
        self.records = tuple(
            CbcRecord(
                kstp=kstp,
                kper=kper,
                text=text,
                imeth=1,
                ndim1=N_CELLS,
                ndim2=1,
                ndim3=-1,
                nlist=0,
                aux_names=(),
                data_pos=0,
            )
            for kstp, kper, text, _ in records
        )
        self._payloads = [payload for *_, payload in records]

    def unique_record_names(self) -> list[str]:
        return list(dict.fromkeys(record.text for record in self.records))

    def read_record(self, idx: int) -> Any:
        return self._payloads[idx]

    def close(self) -> None:
        pass


class _FakeStore:
    def __init__(self) -> None:
        self.budgets: list[dict] = []
        self.stacks: dict[str, np.ndarray] = {}

    def write_budgets(self, sim_id: str, records: list[dict]) -> None:
        self.budgets = records

    def write_field_stack(self, sim_id: str, name: str, stack: np.ndarray, **_: Any) -> None:
        self.stacks[name] = stack


def test_the_extractor_writes_the_stream_share_and_no_table_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from hydromodpy.solver.modflow6.extractors import cbc_reader

    chd = np.array([[[-7.0, 0.0, -3.0, 0.0]]])
    fake = _FakeCbb([(1, 1, "CHD", chd)])
    monkeypatch.setattr(cbc_reader, "Mf6CellBudgetReader", lambda *args, **kwargs: fake)
    store = _FakeStore()

    Modflow6OutputAdapter()._extract_budget(
        "sim",
        store,
        Path("unused.cbc"),
        times=[1.0],
        kstpkpers=[(0, 0)],
        spatial_fields=True,
        nlay=1,
        n_cells=N_CELLS,
        seconds_per_time_unit=1.0,
        stream_constant_head_mask=STREAM,
    )

    np.testing.assert_allclose(store.stacks["constant_head"][0, 0], [-7.0, 0.0, -3.0, 0.0])
    np.testing.assert_allclose(
        store.stacks[STREAM_CONSTANT_HEAD_BUDGET][0, 0], [0.0, 0.0, -3.0, 0.0]
    )
    assert {row["component"] for row in store.budgets} == {"constant_head"}
