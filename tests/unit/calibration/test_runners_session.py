"""Tests of `runners.session`: the file a session reads, the identity it records, the period it scores."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.runners import session
from hydromodpy.calibration.runners.session import search_windows


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_the_calibration_is_read_from_the_first_file_of_the_chain_that_writes_it(tmp_path) -> None:
    _write(tmp_path / "base.toml", "[calibration]\nmethod = 'grid'\n")
    _write(tmp_path / "mid.toml", "base_config = 'base.toml'\n")
    top = _write(tmp_path / "top.toml", f"base_config = '{tmp_path / 'mid.toml'}'\n")

    assert session._carrier_of_calibration(top) == (tmp_path / "base.toml").resolve()


def test_a_chain_that_never_writes_the_calibration_stays_on_the_file_it_started_from(
    tmp_path,
) -> None:
    top = _write(tmp_path / "top.toml", "base_config = 'missing.toml'\n")

    assert session._carrier_of_calibration(top) == top


def test_the_identity_of_a_session_follows_the_model_then_the_document(monkeypatch) -> None:
    ctx = SimpleNamespace(base_cfg=SimpleNamespace(model_dump=dict))
    monkeypatch.setattr(session, "config_identity_hash", lambda cfg: "from-the-model")
    monkeypatch.setattr(session, "run_identity_hash", lambda raw: "from-the-run")

    assert session.session_config_hash({"a": 1}, ctx) == "from-the-model"
    assert session.session_config_hash({"a": 1}, None) == "from-the-run"

    monkeypatch.setattr(session, "run_identity_hash", lambda raw: None)
    expected = hashlib.sha256(json.dumps({"a": 1}, sort_keys=True).encode()).hexdigest()
    assert session.session_config_hash({"a": 1}, None) == expected


_PARAMETERS = {"K": {"bounds": [1e-9, 1e-3], "path": "flow.param.K.field.value"}}


@pytest.mark.parametrize(
    ("phase", "document", "expected"),
    [
        ({"regime": "steady"}, None, {}),
        ({}, None, {}),
        ({}, {"simulation": "x"}, {}),
        ({}, {"simulation": {"time": {"start_datetime": "", "end_datetime": None}}}, {}),
        (
            {},
            {
                "simulation": {
                    "time": {"start_datetime": "2000-01-01", "end_datetime": "2001-06-30"}
                }
            },
            (date(2000, 1, 1), date(2001, 6, 30)),
        ),
    ],
)
def test_the_period_a_search_scores_is_the_declared_one_or_nothing(
    phase, document, expected
) -> None:
    cfg = CalibrationConfig.model_validate(
        {
            "method": "grid",
            "parameters": _PARAMETERS,
            "phases": [{"name": "p", "parameters": ["K"], **phase}],
        }
    )

    found = search_windows(cfg, document)

    if expected == {}:
        assert found == {}
    else:
        [window] = found.values()
        assert (window.start, window.end) == expected
