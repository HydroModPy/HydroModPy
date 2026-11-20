"""Source settings of the recharge variable (recharge in m/s unless a unit is given).

A file source needs a path and a synthetic source needs its values. A sine wave
(amplitude, period_days, offset) only shapes a synthetic source.
"""

import pytest
from pydantic import ValidationError

from hydromodpy.data.variables.recharge.config import RechargeSourceConfig

pytestmark = pytest.mark.fast

SYNTHETIC = {"source": "synthetic", "values": [2.0]}

REFUSALS = [
    pytest.param({"source": "file"}, "path", id="file without path"),
    pytest.param({"source": "synthetic"}, "values", id="synthetic without values"),
    pytest.param(SYNTHETIC | {"offset": 0.5}, "shifts the sinusoid", id="offset alone"),
    pytest.param(SYNTHETIC | {"amplitude": 1.0}, "only with period_days", id="no period"),
    pytest.param(SYNTHETIC | {"period_days": 365}, "only with amplitude", id="no amplitude"),
    pytest.param(
        SYNTHETIC | {"amplitude": 1.0, "period_days": 0}, "must be positive", id="zero period"
    ),
    pytest.param(
        {"source": "sim2", "amplitude": 1.0, "period_days": 365},
        "only shape a synthetic source",
        id="wave on a loaded source",
    ),
]


@pytest.mark.parametrize(("fields", "match"), REFUSALS)
def test_refusals(fields, match):
    with pytest.raises(ValidationError, match=match):
        RechargeSourceConfig(**fields)


def test_a_file_source_may_carry_a_source_unit(tmp_path):
    cfg = RechargeSourceConfig(source="file", path=tmp_path, source_unit="m/day")

    assert cfg.source_unit == "m/day"
