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


FORMULA_REFUSALS = [
    pytest.param({}, "loads its recharge from sources or computes it", id="neither"),
    pytest.param(
        {"formula": "turc", "sources": [{"source": "sim2"}]},
        "loads its recharge from sources or computes it",
        id="both",
    ),
    pytest.param({"formula": "eckhardt"}, "is not a yearly recharge formula", id="a gauge method"),
]


@pytest.mark.parametrize(("fields", "match"), FORMULA_REFUSALS)
def test_a_recharge_takes_sources_or_one_weather_formula(fields, match):
    from hydromodpy.data.variables.recharge.config import RechargeConfig

    with pytest.raises(ValidationError, match=match):
        RechargeConfig.model_validate(fields)


def test_a_formula_names_the_families_the_run_then_loads():
    from types import SimpleNamespace

    from hydromodpy.config.data_reads import families_read_by
    from hydromodpy.data.variables.recharge.config import RechargeConfig

    cfg = SimpleNamespace(
        flow=None, data=SimpleNamespace(recharge=RechargeConfig(formula="turc"), etp=None)
    )

    assert families_read_by(cfg) == {
        "[data.recharge] formula": ("recharge", "precipitation", "temperature")
    }
