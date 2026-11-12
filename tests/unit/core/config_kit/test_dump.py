"""Writing a config section to a TOML file (``HydroModelBase.to_toml``).

A profile name that does not exist is refused before any file is written.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.data.families.base_config import BaseVariableConfig
from hydromodpy.data.families.timeseries_config import (
    TimeseriesColumnsMixin,
    TimeseriesSelectionMixin,
)


class StationSeriesConfig(TimeseriesColumnsMixin, TimeseriesSelectionMixin, BaseVariableConfig):
    """A station time series built from the shared mixins."""


def test_unknown_profile_is_refused(tmp_path: Path) -> None:
    cfg = StationSeriesConfig(date_start="2020-01-01", date_end="2020-12-31")

    with pytest.raises(ValueError):
        cfg.to_toml(tmp_path / "out.toml", profile="superexpert")
