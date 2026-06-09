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
from hydromodpy.data.schemas import validate_abacus


def _good() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "lake_id": ["lac0", "lac0", "lac0"],
            "stage": [85.0, 87.0, 90.0],
            "volume": [0.0, 2.0e5, 1.2e6],
            "sarea": [0.0, 1.0e5, 4.0e5],
        }
    )


def test_valid_abacus_passes_and_coerces() -> None:
    out = validate_abacus(_good())
    assert list(out.columns) == ["lake_id", "stage", "volume", "sarea"]
    assert out["volume"].tolist() == [0.0, 2.0e5, 1.2e6]


def _failure_blob(exc: DataContractViolation) -> str:
    return str(exc.context["failures"]).lower()


def test_non_monotone_stage_is_rejected() -> None:
    bad = _good()
    bad.loc[2, "stage"] = 86.0  # breaks strictly increasing stage
    with pytest.raises(DataContractViolation) as exc:
        validate_abacus(bad)
    # The monotonicity wide-check is named after the stage axis it guards.
    assert "stage" in _failure_blob(exc.value)


def test_duplicate_stage_is_rejected() -> None:
    bad = _good()
    bad.loc[2, "stage"] = 87.0  # duplicate, not strictly increasing
    with pytest.raises(DataContractViolation):
        validate_abacus(bad)


def test_negative_volume_is_rejected_and_names_column() -> None:
    bad = _good()
    bad.loc[1, "volume"] = -1.0
    with pytest.raises(DataContractViolation) as exc:
        validate_abacus(bad)
    failures = exc.value.context["failures"]
    assert any(str(f.get("column")) == "volume" for f in failures)


def test_negative_sarea_is_rejected() -> None:
    bad = _good()
    bad.loc[1, "sarea"] = -5.0
    with pytest.raises(DataContractViolation):
        validate_abacus(bad)


def test_missing_column_is_rejected() -> None:
    bad = _good().drop(columns=["sarea"])
    with pytest.raises(DataContractViolation) as exc:
        validate_abacus(bad)
    assert "sarea" in _failure_blob(exc.value)


def test_decreasing_volume_is_rejected() -> None:
    # MF6 needs dV/dz >= 0; a volume that drops as stage rises is non-physical and
    # must be caught by the contract, not late at solver build.
    bad = _good()
    bad.loc[2, "volume"] = 1.0e5  # below the row at the lower stage (2.0e5)
    with pytest.raises(DataContractViolation) as exc:
        validate_abacus(bad)
    assert "volume" in _failure_blob(exc.value)


def test_single_row_per_lake_is_rejected() -> None:
    # A one-row abacus cannot bracket the stage range; the contract rejects it
    # before the Parquet write so no orphan invalid artifact reaches the catalog.
    bad = pd.DataFrame({"lake_id": ["lac0"], "stage": [85.0], "volume": [0.0], "sarea": [0.0]})
    with pytest.raises(DataContractViolation):
        validate_abacus(bad)


def test_monotonicity_is_per_lake_not_global() -> None:
    # Two lakes interleaved: each is individually increasing, the global
    # column is not. The contract must accept this.
    df = pd.DataFrame(
        {
            "lake_id": ["lac0", "lac1", "lac0", "lac1"],
            "stage": [85.0, 10.0, 90.0, 20.0],
            "volume": [0.0, 0.0, 1.0e6, 5.0e4],
            "sarea": [0.0, 0.0, 4.0e5, 2.0e4],
        }
    )
    out = validate_abacus(df)
    assert len(out) == 4
