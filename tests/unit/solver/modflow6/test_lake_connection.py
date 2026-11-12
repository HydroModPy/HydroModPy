"""LAK stage-volume-area rows (m, m3, m2) and the names of the LAK output files.

An abacus is a mapping of three equal columns or a sequence of rows. A lake id becomes
a file-safe tag of at most 24 characters, so the longest observation name fits the
40 characters of MODFLOW 6.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.solver.modflow6.builders._lake_connection import (
    _abacus_rows,
    _lak_output_stem,
    _safe_lake_tag,
)

ROWS = [(100.0, 0.0, 0.0), (101.0, 500.0, 900.0)]

ABACUS_ROWS = [
    pytest.param(
        {"stage": [100.0, 101.0], "volume": [0.0, 500.0], "sarea": [0.0, 900.0]},
        ROWS,
        id="mapping of lists",
    ),
    pytest.param(
        {
            "stage": np.array([[100.0], [101.0]]),
            "volume": np.array([0, 500]),
            "sarea": (0, 900),
        },
        ROWS,
        id="mapping of arrays, flattened",
    ),
    pytest.param(ROWS, ROWS, id="sequence of rows"),
    pytest.param([[100, 0, 0], (101, "500", 900)], ROWS, id="rows of mixed numbers"),
]


@pytest.mark.parametrize(("abacus", "rows"), ABACUS_ROWS)
def test_abacus_rows(abacus, rows) -> None:
    assert _abacus_rows("res", abacus) == rows


ABACUS_REFUSALS = [
    pytest.param(None, "abacus is required", id="missing"),
    pytest.param(
        {"stage": [1.0, 2.0], "volume": [0.0], "sarea": [0.0, 1.0]},
        "same length",
        id="columns of different lengths",
    ),
    pytest.param(42, "mapping of stage/volume/sarea", id="a number"),
    pytest.param([(100.0, 0.0)], r"rows must be \(stage, volume, sarea\)", id="a row of two"),
]


@pytest.mark.parametrize(("abacus", "match"), ABACUS_REFUSALS)
def test_refusals(abacus, match) -> None:
    with pytest.raises(ValueError, match=match):
        _abacus_rows("res", abacus)


OUTPUT_STEMS = [
    pytest.param(
        SimpleNamespace(model_output_name="run7", model_name="m"), "run7", id="output name"
    ),
    pytest.param(SimpleNamespace(model_output_name="", model_name="m"), "m", id="model name"),
    pytest.param(SimpleNamespace(), "model", id="nothing declared"),
]


@pytest.mark.parametrize(("model", "stem"), OUTPUT_STEMS)
def test_output_stem(model, stem) -> None:
    assert _lak_output_stem(model) == stem


def test_short_lake_ids_keep_their_letters() -> None:
    assert _safe_lake_tag("lac 1-nord") == "lac_1_nord"


def test_long_lake_ids_get_a_hash_suffix() -> None:
    long_id = "reservoir-" + "x" * 30
    other_id = "reservoir-" + "x" * 29 + "y"

    tag = _safe_lake_tag(long_id)

    assert len(tag) == 24
    assert tag.startswith("reservoir_xxxxxxx_")  # first 17 characters, then "_" and 6 hex digits
    assert tag == _safe_lake_tag(long_id)
    assert tag != _safe_lake_tag(other_id)
