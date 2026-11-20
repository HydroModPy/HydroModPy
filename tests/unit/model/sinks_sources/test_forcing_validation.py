"""Numeric checks on a forcing payload, with the label of the entry that fails."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from hydromodpy.model.forcing.validation import (
    ensure_finite_numeric_payload,
    ensure_non_negative_numeric_payload,
    has_temporal_index,
    numeric_payload_array,
)


def test_payload_validators_name_the_failing_entry():
    ensure_finite_numeric_payload({"rch": [1.0, 0.0]}, label="forcing")
    ensure_non_negative_numeric_payload({"rch": [1.0, 0.0]}, label="forcing")

    with pytest.raises(ValueError, match=r"forcing\['bad'\] must be non-negative"):
        ensure_non_negative_numeric_payload({"bad": [2.0, -0.1]}, label="forcing")
    with pytest.raises(ValueError, match=r"forcing\['well'\] must contain only finite"):
        ensure_finite_numeric_payload({"well": [1.0, np.nan]}, label="forcing")


def test_payload_array():
    assert numeric_payload_array(2.5, label="forcing").tolist() == [2.5]

    with pytest.raises(TypeError, match="must be numeric"):
        numeric_payload_array(True, label="forcing")
    with pytest.raises(ValueError, match="cannot be empty"):
        numeric_payload_array([], label="forcing")
    with pytest.raises(TypeError, match="numeric sequence"):
        numeric_payload_array(["bad"], label="forcing")


def test_temporal_index():
    assert has_temporal_index(pd.Series([1.0], index=pd.to_datetime(["2020-01-01"])))
    assert has_temporal_index(pd.Series([1.0], index=["2020-01-01"]))
    assert not has_temporal_index(pd.Series([1.0], index=[0]))
    assert not has_temporal_index(object())
