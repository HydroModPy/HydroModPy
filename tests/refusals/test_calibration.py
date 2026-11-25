"""A calibration that asks the zoomed Latin hypercube for what it cannot do is refused.

The refusal comes when the file is read or when ``hmp check`` runs, before any solve.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.optim.method_config import method_options_problem
from tests.unit.calibration._factories_config import messages, preflight_of

_TWO_PARAMETERS = """
@KB
[calibration.parameters.Sy]
bounds = [1e-3, 0.35]
"""

CHECKS = [
    pytest.param(
        '[calibration]\nmethod = "lhs_zoom"\n' + _TWO_PARAMETERS,
        ["'lhs_zoom' moves 1 parameter(s)", "K, Sy"],
        id="two_parameters",
    ),
    pytest.param(
        '[calibration]\nmethod = "lhs_zoom"\nmethod_options = { levels = [24] }\n@KB',
        ["method_options", "at least two levels", "write method = 'lhs'"],
        id="one_level",
    ),
    pytest.param(
        '[calibration]\nmethod = "lhs_zoom"\nprecision = 0.01\n@KB',
        ["stops on its evaluation budget"],
        id="a_precision",
    ),
    pytest.param(
        '[calibration]\nmethod = "lhs_zoom"\nmax_trials = 39\n@KB',
        ["max_trials = 39 is below the 40 evaluations"],
        id="a_budget_below_the_levels",
    ),
]


@pytest.mark.parametrize(("doc", "said"), CHECKS)
def test_hmp_check_refuses_the_zoom(tmp_path: Path, doc: str, said: list[str]) -> None:
    found = messages(preflight_of(tmp_path, doc))

    for word in said:
        assert word in found


OPTIONS = [
    ({"levels": [24]}, "at least two levels"),
    ({"levels": []}, "at least two levels"),
    ({"levels": [24, 1]}, "at least two points"),
    ({"levels": [0, 8]}, "at least two points"),
    ({"levels": "24,16"}, "levels"),
    ({"n_samples": 40}, "does not take n_samples"),
]


@pytest.mark.parametrize(("options", "said"), OPTIONS)
def test_a_zoom_refuses_what_its_options_do_not_say(options: dict, said: str) -> None:
    assert said in (method_options_problem("lhs_zoom", options) or "")


@pytest.mark.parametrize(("options", "said"), OPTIONS[:2])
def test_a_file_with_such_options_does_not_load(options: dict, said: str) -> None:
    with pytest.raises(ValidationError, match=said):
        CalibrationConfig.model_validate(
            {
                "method": "lhs_zoom",
                "method_options": options,
                "parameters": {"K": {"bounds": [1e-7, 1e-3], "path": "flow.param.K.field.value"}},
            }
        )
