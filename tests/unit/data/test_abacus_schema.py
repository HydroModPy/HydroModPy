"""AbacusTableSchema contract: stage monotonicity, non-negative volume/area.

Guards that MF6's stage-volume-area table is validated
before it reaches ``ModflowUtllaktab``: a good abacus passes; a non-monotone
stage, a negative volume, or a missing column is rejected with a structured
``DataContractViolation`` naming the offending column.
"""

from __future__ import annotations

import pandas as pd
import pytest

from hydromodpy.core.exceptions import DataContractViolation
from hydromodpy.data.schemas.abacus import validate_abacus


def _good() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "lake_id": ["lac0", "lac0", "lac0"],
            "stage": [85.0, 87.0, 90.0],
            "volume": [0.0, 2.0e5, 1.2e6],
            "sarea": [0.0, 1.0e5, 4.0e5],
        }
    )


def _failure_blob(exc: DataContractViolation) -> str:
    return str(exc.context["failures"]).lower()


def test_non_monotone_stage_is_rejected() -> None:
    bad = _good()
    bad.loc[2, "stage"] = 86.0  # breaks strictly increasing stage
    with pytest.raises(DataContractViolation) as exc:
        validate_abacus(bad)
    # The monotonicity wide-check is named after the stage axis it guards.
    assert "stage" in _failure_blob(exc.value)
