"""A default that moves with an edition reaches a document of an older edition as ``old``.

This version serves one edition, "2.0", and its register moves no default, so
``persist_trial_series`` is on whatever the document writes. The mechanism is proved
on a register of its own: a row of a later edition writes ``old`` into a calibration
document of the first edition. A document that does not write ``[calibration]`` keeps
it absent, so a simulation keeps its resolved configuration and its identity.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from hydromodpy.config.config_migration import migrate_merged_doc, migrate_sealed_config_doc
from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.schema.changes import read

# A row of a later edition, which the register of this version does not hold.
ROW = (
    '[[default]]\nid = "trial_series_by_default"\nsince = "2.1.0"\nedition = "2.1"\n'
    'key = "calibration.persist_trial_series"\nold = false\nnew = true\n'
    'quantities = ["metrics"]\ntext = "t"\n'
)
HEAD = 'schema = "hydromodpy.changes.v1"\n'


def calibration_document(**top: Any) -> dict[str, Any]:
    return {
        "workspace": {},
        "workflow": {"mode": "calibration"},
        "geographic": {"source_mode": "synthetic"},
        "flow": {
            "param_list": ["K"],
            "param": {"K": {"field": {"kind": "homogeneous", "unit": "m/s", "value": 5e-5}}},
        },
        "calibration": {"parameters": {"K": {"bounds": [1e-7, 1e-3]}}},
        **top,
    }


def simulation_document() -> dict[str, Any]:
    return {
        "workspace": {},
        "workflow": {"mode": "simulation"},
        "geographic": {"source_mode": "synthetic"},
    }


def test_an_unserved_edition_is_refused(tmp_path: Path) -> None:
    with pytest.raises(Exception, match="2.0") as refused:
        HydroModPyConfig.from_dict(calibration_document(edition="2.1"), base_dir=tmp_path)

    assert "edition" in str(refused.value)


@pytest.mark.parametrize("sealed", [False, True])
def test_a_later_edition_creates_no_section(sealed: bool) -> None:
    register = read(HEAD + ROW)
    doc = simulation_document()

    if sealed:
        migrate_sealed_config_doc(doc, register=register)
    else:
        migrate_merged_doc(doc, register=register)

    # A sealed read drops an empty [workspace], the one difference from the input.
    expected = {k: v for k, v in simulation_document().items() if not (sealed and k == "workspace")}
    assert doc == expected
