"""Date window of ``[overview]`` (ISO dates). A missing or reversed window is refused."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hydromodpy.display.overview.config import OverviewConfig

REFUSED_WINDOWS = [
    pytest.param({"date_start": "2019-01-01"}, "overview.date_end is missing", id="no end"),
    pytest.param({"date_end": "2025-12-31"}, "overview.date_start is missing", id="no start"),
    pytest.param(
        {"date_start": "2025-12-31", "date_end": "2019-01-01"},
        "overview.date_start must be before",
        id="reversed",
    ),
    pytest.param(
        {"date_start": "01-01-2019", "date_end": "2025-12-31"}, "Invalid ISO date", id="not ISO"
    ),
]


@pytest.mark.parametrize(("declared", "message"), REFUSED_WINDOWS)
def test_refused_windows(declared, message) -> None:
    with pytest.raises(ValidationError, match=message):
        OverviewConfig(**declared)
