"""``persist_trial_series`` is on under edition 2.1 and off under edition 2.0, on every path.

The row ``trial_series_by_default`` of the register writes ``false`` into a calibration
document of the first edition. A document that does not write ``[calibration]`` keeps it
absent, so a simulation keeps its resolved configuration and its identity.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
import tomlkit

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.config import HydroModPyConfig
from hydromodpy.config.config_migration import (
    migrate_merged_doc,
    migrate_sealed_config_doc,
    optional_root_sections,
)
from hydromodpy.schema.changes import read

ROW = (
    '[[default]]\nid = "trial_series_by_default"\nsince = "2.1.0"\nedition = "2.1"\n'
    'key = "calibration.persist_trial_series"\nold = false\nnew = true\n'
    'quantities = ["metrics"]\ntext = "t"\n'
)
HEAD = 'schema = "hydromodpy.changes.v1"\n'


def _register():
    return read(HEAD + ROW)


def _calibration(**top: Any) -> dict[str, Any]:
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


def _simulation() -> dict[str, Any]:
    return {
        "workspace": {},
        "workflow": {"mode": "simulation"},
        "geographic": {"source_mode": "synthetic"},
    }


def _series(config: HydroModPyConfig) -> bool:
    assert config.calibration is not None
    return config.calibration.persist_trial_series


CASES = {
    "no edition is the edition 2.0": (_calibration(), False),
    "edition 2.0 written": (_calibration(edition="2.0"), False),
    "edition 2.1 written": (_calibration(edition="2.1"), True),
}


@pytest.mark.parametrize(("doc", "expected"), CASES.values(), ids=CASES.keys())
@pytest.mark.parametrize("path", ["dict", "json", "toml", "snapshot"])
def test_every_path_of_a_document_reads_the_default_of_its_edition(
    path: str, doc: dict, expected: bool, tmp_path: Path
) -> None:
    if path == "dict":
        config = HydroModPyConfig.from_dict(copy.deepcopy(doc), base_dir=tmp_path)
    elif path == "json":
        config = HydroModPyConfig.from_json(json.dumps(doc), base_dir=tmp_path)
    elif path == "toml":
        file = tmp_path / "config.toml"
        file.write_text(tomlkit.dumps(doc), encoding="utf-8")
        config = HydroModPyConfig.from_toml(file)
    else:
        config = HydroModPyConfig.from_snapshot(copy.deepcopy(doc))

    assert _series(config) is expected


def test_a_value_the_document_writes_wins_over_the_edition(tmp_path: Path) -> None:
    doc = _calibration(edition="2.1")
    doc["calibration"]["persist_trial_series"] = False

    assert _series(HydroModPyConfig.from_dict(doc, base_dir=tmp_path)) is False


@pytest.mark.parametrize("path", ["dict", "snapshot"])
def test_a_simulation_document_keeps_calibration_absent(path: str, tmp_path: Path) -> None:
    doc = _simulation()
    config = (
        HydroModPyConfig.from_dict(doc, base_dir=tmp_path)
        if path == "dict"
        else HydroModPyConfig.from_snapshot(doc)
    )

    assert config.calibration is None
    assert "calibration" not in doc


MERGED = {
    "a calibration of the first edition": (_calibration(), {"persist_trial_series": False}),
    "a calibration of edition 2.1": (_calibration(edition="2.1"), {}),
}


@pytest.mark.parametrize(("doc", "table"), MERGED.values(), ids=MERGED.keys())
@pytest.mark.parametrize("sealed", [False, True])
def test_the_register_row_writes_old_into_a_calibration_of_the_first_edition(
    doc: dict, table: dict, sealed: bool
) -> None:
    register = _register()
    read_doc = copy.deepcopy(doc)
    expected = {**doc["calibration"], **table}

    if sealed:
        migrate_sealed_config_doc(read_doc, register=register)
    else:
        migrate_merged_doc(read_doc, register=register)

    assert read_doc["calibration"] == expected


@pytest.mark.parametrize("sealed", [False, True])
def test_the_register_row_never_creates_a_section_the_document_leaves_out(sealed: bool) -> None:
    register = _register()
    doc = _simulation()

    if sealed:
        migrate_sealed_config_doc(doc, register=register)
    else:
        migrate_merged_doc(doc, register=register)

    # A sealed read drops an empty [workspace], the one difference from the input.
    assert doc == {k: v for k, v in _simulation().items() if not (sealed and k == "workspace")}


def test_the_optional_sections_are_the_ones_that_default_to_none() -> None:
    names = optional_root_sections()

    assert "calibration" in names
    assert "workflow" not in names
    assert CalibrationConfig.model_fields["persist_trial_series"].default is True
