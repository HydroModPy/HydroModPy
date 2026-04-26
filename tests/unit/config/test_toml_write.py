from __future__ import annotations

import tomllib
from datetime import datetime, timezone

from hydromodpy.core.config.toml_write import dumps


def test_dumps_round_trips_nested_tables_and_arrays() -> None:
    payload = {
        "base_config": r"C:\configs\base.toml",
        "workspace": {
            "root": r"C:\workspace",
            "flags": ["calibration", "snapshot"],
        },
        "simulation": {
            "run_id": "case_a",
            "enabled": True,
        },
        "simulation process": [
            {"type": "flow", "solvers": ["modflow6"]},
            {"type": "transport", "solvers": ["mt3dms"]},
        ],
    }

    rendered = dumps(payload)
    parsed = tomllib.loads(rendered)

    assert parsed["base_config"] == r"C:\configs\base.toml"
    assert parsed["workspace"]["root"] == r"C:\workspace"
    assert parsed["workspace"]["flags"] == ["calibration", "snapshot"]
    assert parsed["simulation"]["run_id"] == "case_a"
    assert parsed["simulation"]["enabled"] is True
    assert parsed["simulation process"][0]["type"] == "flow"
    assert parsed["simulation process"][1]["solvers"] == ["mt3dms"]


def test_dumps_serializes_datetimes_and_inline_tables() -> None:
    payload = {
        "meta": {
            "created_at": datetime(2026, 4, 26, 21, 10, tzinfo=timezone.utc),
            "limits": [{"min": 1.0, "max": 2.5}],
        }
    }

    rendered = dumps(payload)
    parsed = tomllib.loads(rendered)

    assert parsed["meta"]["created_at"] == datetime(2026, 4, 26, 21, 10, tzinfo=timezone.utc)
    assert parsed["meta"]["limits"][0] == {"min": 1.0, "max": 2.5}
