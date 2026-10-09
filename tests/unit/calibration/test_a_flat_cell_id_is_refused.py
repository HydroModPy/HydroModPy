"""A calibration cell output names its cell by row and col; cell_id is refused.

No solver read a flat cell index: every run refused the output it named.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hydromodpy.calibration.config import CalibOutputCell
from hydromodpy.core.config_kit.base import HydroModelBase


def test_cell_id_is_refused_with_the_keys_to_write() -> None:
    with pytest.raises(ValidationError) as excinfo:
        CalibOutputCell(variable="head", cell_id=7)
    message = str(excinfo.value)
    assert "'cell_id' is not accepted any more" in message
    assert "row and col" in message
    assert "support = 'point'" in message


def test_a_cell_output_without_row_and_col_is_refused() -> None:
    with pytest.raises(ValidationError, match="row"):
        CalibOutputCell(variable="head")


def test_row_and_col_name_the_cell() -> None:
    output = CalibOutputCell(variable="head", row=3, col=4, layer=1)
    assert (output.layer, output.row, output.col) == (1, 3, 4)


def test_a_model_without_refused_keys_accepts_its_fields() -> None:
    class _Plain(HydroModelBase):
        value: int = 0

    assert _Plain(value=2).value == 2
