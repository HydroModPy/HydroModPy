"""``geographic.enforce_streams`` and a recharge ``runoff_ratio`` are refused with advice."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hydromodpy.data.variables.recharge.config import RechargeSourceConfig
from hydromodpy.spatial.geographic.geographic_config import GeographicConfig


def test_enforce_streams_is_refused_by_name() -> None:
    with pytest.raises(ValidationError, match="enforce_streams.*not accepted any more"):
        GeographicConfig.model_validate({"enforce_streams": True})


def test_runoff_ratio_is_refused_by_name() -> None:
    with pytest.raises(ValidationError, match="runoff_ratio.*not accepted any more"):
        RechargeSourceConfig.model_validate({"source": "synthetic", "runoff_ratio": 0.0})
