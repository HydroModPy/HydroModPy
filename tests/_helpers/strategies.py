"""Hypothesis strategies reusable across tests.

Importing this module never fails: Hypothesis is an optional test
dependency. When the library is not installed the module exports the
same names as ``None``-valued placeholders, so downstream tests can
``pytest.importorskip("hypothesis")`` before use.
"""

from __future__ import annotations

try:
    import numpy as np
    from hypothesis import strategies as st
    from hypothesis.extra.numpy import arrays
except ImportError:  # pragma: no cover - fallback when hypothesis unavailable
    finite_floats = None
    positive_hk = None
    valid_porosity = None
    valid_specific_yield = None
    valid_recharge_mm_per_day = None
    finite_arrays_1d = None
    valid_heads_3d = None
    flow_regime = None
else:
    finite_floats = st.floats(
        min_value=-1e9,
        max_value=1e9,
        allow_nan=False,
        allow_infinity=False,
    )

    positive_hk = st.floats(min_value=1e-9, max_value=1e2, allow_nan=False)
    valid_porosity = st.floats(min_value=0.01, max_value=0.5, allow_nan=False)
    valid_specific_yield = st.floats(min_value=0.001, max_value=0.3, allow_nan=False)
    valid_recharge_mm_per_day = st.floats(min_value=0.0, max_value=50.0, allow_nan=False)

    finite_arrays_1d = arrays(
        dtype=np.float64,
        shape=st.integers(min_value=1, max_value=200),
        elements=st.floats(-1e6, 1e6, allow_nan=False, allow_infinity=False),
    )

    valid_heads_3d = arrays(
        dtype=np.float64,
        shape=(5, 5, 5),
        elements=st.floats(min_value=0.0, max_value=1000.0, allow_nan=False),
    )

    flow_regime = st.sampled_from(["steady", "transient"])


__all__ = [
    "finite_floats",
    "positive_hk",
    "valid_porosity",
    "valid_specific_yield",
    "valid_recharge_mm_per_day",
    "finite_arrays_1d",
    "valid_heads_3d",
    "flow_regime",
]
