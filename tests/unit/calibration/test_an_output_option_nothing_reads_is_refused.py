"""An output option that nothing reads is refused, not ignored.

Beside ``observes``, the record is paired with the simulated series step by
step and the paired series is scored: a ``reducer`` was applied, then
overwritten, so ``none``, ``mean`` and ``sum`` gave the same cost. A list of
dates in ``time`` was accepted and documented, and read as ``"all"``.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hydromodpy.calibration.config import validate_calib_output

SUPPORTS = [
    ("point", {"variable": "head", "x": 0.0, "y": 0.0}),
    ("boundary", {"variable": "discharge", "boundary_id": "drainage"}),
    ("cell", {"variable": "head", "row": 0, "col": 0}),
    ("lake", {"variable": "stage", "lake_id": "lac0"}),
]


@pytest.mark.parametrize(("support", "where"), SUPPORTS)
@pytest.mark.parametrize("reducer", ["mean", "sum", "last"])
def test_a_reducer_beside_observes_is_refused(support: str, where: dict, reducer: str) -> None:
    with pytest.raises(ValidationError, match="reduced value is never scored"):
        validate_calib_output({"support": support, "observes": "PZ1", "reducer": reducer, **where})


def test_a_reducer_on_a_written_vector_still_reduces() -> None:
    decl = validate_calib_output(
        {
            "variable": "stage",
            "support": "lake",
            "lake_id": "lac0",
            "reducer": "mean",
            "observed_values": [10.0],
        }
    )

    assert decl.reducer == "mean"


@pytest.mark.parametrize(("support", "where"), SUPPORTS)
def test_a_list_of_dates_is_refused(support: str, where: dict) -> None:
    with pytest.raises(ValidationError, match="selects nothing"):
        validate_calib_output({"support": support, "time": ["2020-01-01"], **where})


@pytest.mark.parametrize("time", ["all", "first", "last"])
def test_the_named_instants_stay(time: str) -> None:
    decl = validate_calib_output(
        {"variable": "head", "support": "cell", "row": 0, "col": 0, "time": time}
    )

    assert decl.time == time
