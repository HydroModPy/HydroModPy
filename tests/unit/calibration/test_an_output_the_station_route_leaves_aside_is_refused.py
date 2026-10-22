"""An output the one-line form never reads is refused when the file loads.

With no objective block, ``variable`` says what a calibration scores: the
output it names, or every loaded station of that variable. A file that
declared ``[calibration.outputs.h]`` and left ``variable`` at its default
``"head"`` used to fit the loaded piezometers, never ``h``, and
``hmp config check`` answered OK.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hydromodpy.calibration.config import CalibrationConfig

pytestmark = pytest.mark.unit

H = {"variable": "head", "support": "point", "x": 10.0, "y": 20.0, "observed_values": [1.0, 2.0]}


def _config(**section: object) -> CalibrationConfig:
    payload = {"parameters": {"K": {"bounds": [1e-7, 1e-3], "path": "flow.param.K.field.value"}}}
    payload.update(section)
    return CalibrationConfig.model_validate(payload)


def test_an_output_beside_the_default_variable_is_refused() -> None:
    with pytest.raises(ValidationError, match=r"\['h'\] are declared and nothing scores them"):
        _config(outputs={"h": H})


def test_naming_the_output_in_variable_scores_it() -> None:
    cfg = _config(outputs={"h": H}, variable="h")

    assert [block.uses_outputs for block in cfg.objective_blocks] == [["h"]]


def test_an_output_beside_a_block_may_feed_the_residuals() -> None:
    cfg = _config(
        outputs={"h": H, "spare": H},
        objective_blocks=[{"name": "fit", "metric": "rmse", "uses_outputs": ["h"]}],
    )

    assert set(cfg.outputs) == {"h", "spare"}
