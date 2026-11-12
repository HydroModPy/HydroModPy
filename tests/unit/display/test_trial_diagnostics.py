"""The trial table of a calibration session: one row per trial, parameters and cost as flat columns.

A table that records no trial number is read by rank. A column that is not session
bookkeeping and has no dot in its name is a sampled parameter.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.display.figures._trial_diagnostics import TrialTable, trial_table


def flat_session() -> SimpleNamespace:
    # Two parameters written as bare columns, one dotted diagnostic, no `parameters` block.
    frame = pd.DataFrame(
        {
            "K": [1e-5, 2e-5, 3e-5],
            "Sy": [0.1, 0.2, 0.3],
            "cost": [3.0, 2.0, 1.0],
            "net.D_so": [10.0, 20.0, 30.0],
        }
    )
    return SimpleNamespace(name="flat", trials=frame)


def test_bare_columns_are_the_sampled_parameters() -> None:
    table = trial_table(flat_session())

    assert table.parameters == ("K", "Sy")
    np.testing.assert_allclose(table.parameter_values("K")[1], [1e-5, 2e-5, 3e-5])


def test_a_table_without_trial_numbers_is_read_by_rank() -> None:
    table = trial_table(flat_session())

    np.testing.assert_array_equal(table.iterations(), [0.0, 1.0, 2.0])
    assert table.row_of_trial(1) is None


OBJECTIVES = [
    pytest.param(["cost"], True, id="cost column"),
    pytest.param(["objective"], True, id="objective column"),
    pytest.param(["K"], False, id="no objective"),
]


@pytest.mark.parametrize(("columns", "expected"), OBJECTIVES)
def test_has_objective(columns: list[str], expected: bool) -> None:
    table = TrialTable(frame=pd.DataFrame({name: [1.0] for name in columns}), parameters=())

    assert table.has_objective() is expected


def test_a_table_without_objective_is_refused() -> None:
    table = TrialTable(frame=pd.DataFrame({"K": [1.0]}), parameters=("K",))

    with pytest.raises(ValueError, match="no trial recorded an objective under cost or objective"):
        table.objective_column()
