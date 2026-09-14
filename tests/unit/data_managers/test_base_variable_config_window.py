"""``BaseVariableConfig`` accepts a full window or none, never a half one."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hydromodpy.data.variables.recharge.config import RechargeConfig, RechargeSourceConfig

SOURCES = [
    RechargeSourceConfig(
        source="synthetic",
        freq="MS",
        start_date="2019-01-01",
        periods=12,
        values=[1.0] * 12,
    )
]


def test_no_window_is_accepted() -> None:
    cfg = RechargeConfig(sources=SOURCES)

    assert cfg.date_start is None
    assert cfg.date_end is None


def test_full_window_is_accepted() -> None:
    cfg = RechargeConfig(sources=SOURCES, date_start="2019-01-01", date_end="2025-12-31")

    assert cfg.date_start == "2019-01-01"
    assert cfg.date_end == "2025-12-31"


@pytest.mark.parametrize(
    ("declared", "missing"),
    [
        ({"date_start": "2019-01-01"}, "date_end"),
        ({"date_end": "2025-12-31"}, "date_start"),
    ],
)
def test_half_declared_window_is_rejected(declared: dict[str, str], missing: str) -> None:
    with pytest.raises(ValidationError, match=f"{missing} is missing"):
        RechargeConfig(sources=SOURCES, **declared)


def test_reversed_window_is_rejected() -> None:
    with pytest.raises(ValidationError, match="date_start must be before date_end"):
        RechargeConfig(sources=SOURCES, date_start="2025-12-31", date_end="2019-01-01")
