"""The keys the guide advertises per engine are the keys that engine accepts.

Every method config forbids extra keys, so a documented option the model does
not carry is not a harmless inaccuracy: the file that copies it is refused. The
page that listed them drifted into advertising six such keys, ``n_points``,
``pruner``, ``mutation``, ``recombination``, ``adaptive``, ``acq``, and one
misspelling each of ``n_init`` and ``proposal_sigma``. Reading the table against
the union is what stops that returning.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, get_args

from hydromodpy.calibration.optim.method_config import CalibrationMethodConfig
from hydromodpy.calibration.optim.optimizer import available_optimizers

PAGE = (
    Path(__file__).resolve().parents[3]
    / "docs"
    / "source"
    / "architecture"
    / "calibration"
    / "calibration-guide.rst"
)
ANCHOR = ".. _calibration-engine-options:"


def _documented() -> dict[str, set[str]]:
    """Read the engine/keys table off the page."""
    section = PAGE.read_text(encoding="utf-8").split(ANCHOR, 1)[1]
    table = section.split(".. list-table::", 1)[1].split("\nThree of them", 1)[0]
    rows: dict[str, set[str]] = {}
    for chunk in table.split("* - ")[1:]:
        head, _, body = chunk.partition("\n")
        engine = head.strip().strip("`")
        if engine == "engine":
            continue
        rows[engine] = set(re.findall(r"``([a-z_0-9]+)``", body))
    return rows


def _models() -> dict[str, Any]:
    members = get_args(get_args(CalibrationMethodConfig)[0])
    return {member.model_fields["method"].default: member for member in members}


def test_the_table_covers_every_registered_engine() -> None:
    assert set(_documented()) == set(available_optimizers())


def test_each_row_lists_exactly_what_its_engine_accepts() -> None:
    models = _models()

    for engine, documented in _documented().items():
        accepted = set(models[engine].model_fields) - {"method"}
        assert documented == accepted, engine
