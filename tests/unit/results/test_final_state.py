"""The final state of a run goes to disk and back without losing a bit.

A restart must not change the state it starts from, so ``final_state/`` holds
the last head, the lake stages and the reach stages in float64. The tests
write and read it, check the NaN of inactive cells, the order of the lakes,
the folder it leaves, and that its digest is the one of the restart that reads
it.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import zarr

from hydromodpy.model.initial.state import PriorState
from hydromodpy.results.record.request_identity import prior_state_digest
from hydromodpy.results.storage.contract import (
    ALLOWED_RUN_ENTRIES,
    FINAL_STATE_DIRNAME,
    UNSEALED_RUN_ENTRIES,
)
from hydromodpy.results.storage.final_state import (
    FINAL_STATE_SCHEMA,
    FinalState,
    final_state_dir,
    read_final_state,
    write_final_state,
)
from hydromodpy.results.storage.prior_state import prior_state_at

HEAD = np.array(
    [
        [100.0 + 1e-13, np.pi * 30.0, np.nan],
        [-0.0, 1e-300, 99.99999999999997],
    ]
)


STATES = (
    ("head only", FinalState(head=HEAD)),
    (
        "lakes and reaches",
        FinalState(
            head=HEAD,
            lake_stages={"sill": 74.2, "forebay": 13.95991694769827},
            sfr_stages={4: 12.000000000000002, 0: 11.5},
            at=pd.Timestamp("2020-07-01"),
        ),
    ),
)


@pytest.mark.parametrize("state", [one for _, one in STATES], ids=[name for name, _ in STATES])
def test_a_final_state_comes_back_equal_to_the_bit(tmp_path: Path, state: FinalState) -> None:
    folder = write_final_state(tmp_path, state)

    back = read_final_state(tmp_path)

    assert folder == final_state_dir(tmp_path) == tmp_path / FINAL_STATE_DIRNAME
    assert back.head.dtype == np.float64
    assert back.head.tobytes() == state.head.tobytes()
    assert list(back.lake_stages.items()) == list(state.lake_stages.items())
    assert dict(back.sfr_stages) == dict(state.sfr_stages)
    assert back.at == state.at


def test_the_nan_and_the_zero_of_a_final_state_are_canonical() -> None:
    state = FinalState(head=np.array([[-np.nan, -0.0, 1.0]]))

    assert np.isnan(state.head[0, 0])
    assert not np.signbit(state.head[0, 0])
    assert not np.signbit(state.head[0, 1])
    assert not state.head.flags.writeable


def test_the_group_is_zarr_3_in_float64_with_its_ids(tmp_path: Path) -> None:
    write_final_state(tmp_path, STATES[1][1])

    root = zarr.open_group(str(final_state_dir(tmp_path)), mode="r")

    assert root.metadata.zarr_format == 3
    assert root.attrs["schema"] == FINAL_STATE_SCHEMA
    assert root.attrs["at"] == "2020-07-01T00:00:00"
    assert {name: root[name].dtype for name in ("head", "lake_stage", "sfr_stage")} == {
        "head": np.float64,
        "lake_stage": np.float64,
        "sfr_stage": np.float64,
    }
    assert root["lake_stage"].attrs["lake_ids"] == ["sill", "forebay"]
    assert root["sfr_stage"].attrs["reaches"] == [0, 4]


def test_a_second_write_replaces_the_first_and_leaves_no_scratch(tmp_path: Path) -> None:
    write_final_state(tmp_path, STATES[1][1])
    write_final_state(tmp_path, STATES[0][1])

    back = read_final_state(tmp_path)

    assert dict(back.lake_stages) == {} and dict(back.sfr_stages) == {}
    assert sorted(path.name for path in (tmp_path / ".hmp").iterdir()) == []


def test_a_run_without_a_final_state_reads_none(tmp_path: Path) -> None:
    assert read_final_state(tmp_path) is None


def test_another_schema_is_refused(tmp_path: Path) -> None:
    write_final_state(tmp_path, STATES[0][1])
    root = zarr.open_group(str(final_state_dir(tmp_path)), mode="r+")
    root.attrs["schema"] = "hydromodpy.final_state.v9"

    with pytest.raises(ValueError, match="hydromodpy.final_state.v9"):
        read_final_state(tmp_path)


def test_a_head_that_is_not_layers_by_cells_is_refused() -> None:
    with pytest.raises(ValueError, match=r"\(nlay, ncpl\)"):
        FinalState(head=np.zeros(3))


def test_the_digest_of_the_state_read_is_the_digest_of_the_arrays_written(
    tmp_path: Path,
) -> None:
    state = STATES[1][1]
    write_final_state(tmp_path, state)

    read = prior_state_at(str(tmp_path))
    given = PriorState(
        head=HEAD,
        lake_stages=dict(state.lake_stages),
        path="anywhere",
        sim_id="other",
        sfr_stages=dict(state.sfr_stages),
    )

    assert prior_state_digest(read) == prior_state_digest(given)


def test_the_final_state_is_sealed_with_the_run() -> None:
    assert FINAL_STATE_DIRNAME in ALLOWED_RUN_ENTRIES
    assert FINAL_STATE_DIRNAME not in UNSEALED_RUN_ENTRIES
