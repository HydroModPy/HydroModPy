"""``[overview]`` is the date declaration of overview mode, so it validates like one."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hydromodpy.display.overview.config import OverviewConfig


def test_no_window_is_accepted() -> None:
    cfg = OverviewConfig(name="nancon")

    assert cfg.date_start is None
    assert cfg.date_end is None


def test_full_window_is_accepted() -> None:
    cfg = OverviewConfig(date_start="2019-01-01", date_end="2025-12-31")

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
    with pytest.raises(ValidationError, match=f"overview.{missing} is missing"):
        OverviewConfig(**declared)


def test_reversed_window_is_rejected() -> None:
    with pytest.raises(ValidationError, match="overview.date_start must be before"):
        OverviewConfig(date_start="2025-12-31", date_end="2019-01-01")


def test_non_iso_date_is_rejected() -> None:
    with pytest.raises(ValidationError, match="Invalid ISO date"):
        OverviewConfig(date_start="01-01-2019", date_end="2025-12-31")
