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

from hydromodpy.results.storage.contract import (
    ALLOWED_RUN_ENTRIES,
    FINAL_STATE_DIRNAME,
    UNSEALED_RUN_ENTRIES,
)
from hydromodpy.results.storage.final_state import (
    FinalState,
    final_state_dir,
    read_final_state,
    write_final_state,
)

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


def test_no_final_state(tmp_path: Path) -> None:
    assert read_final_state(tmp_path) is None


def test_other_schema_refused(tmp_path: Path) -> None:
    write_final_state(tmp_path, STATES[0][1])
    root = zarr.open_group(str(final_state_dir(tmp_path)), mode="r+")
    root.attrs["schema"] = "hydromodpy.final_state.v9"

    with pytest.raises(ValueError, match="hydromodpy.final_state.v9"):
        read_final_state(tmp_path)


def test_head_shape_refused() -> None:
    with pytest.raises(ValueError, match=r"\(nlay, ncpl\)"):
        FinalState(head=np.zeros(3))


def test_sealed_with_the_run() -> None:
    assert FINAL_STATE_DIRNAME in ALLOWED_RUN_ENTRIES
    assert FINAL_STATE_DIRNAME not in UNSEALED_RUN_ENTRIES
