"""``hmp catalog show --format json`` writes strict JSON: NaN and infinities are ``null``."""

from __future__ import annotations

import importlib
import json
import sys

from tests._helpers.sealed_runs import make_project


def test_a_nan_score_is_null_in_the_json(monkeypatch, capsys, tmp_path) -> None:
    project = make_project(tmp_path / "demo")
    index = project / ".hmp" / "index.duckdb"
    index.parent.mkdir(parents=True)
    index.touch()
    payload = {
        "sim_id": "a" * 32,
        "name": "alpha",
        "nse": float("nan"),
        "kge": float("inf"),
        "nested": {"rmse": float("-inf"), "values": [1.0, float("nan")]},
        "n_cells": 12,
    }
    monkeypatch.setattr("hydromodpy.cli._workers.catalog.show_simulation", lambda *a, **k: payload)
    monkeypatch.setattr(
        sys, "argv", ["hmp", "catalog", "show", "alpha", "--format", "json", "-w", str(project)]
    )

    importlib.import_module("hydromodpy.cli.main").main()

    out = capsys.readouterr().out
    loaded = json.loads(out, parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)))
    assert loaded["nse"] is None and loaded["kge"] is None
    assert loaded["nested"] == {"rmse": None, "values": [1.0, None]}
    assert loaded["n_cells"] == 12
