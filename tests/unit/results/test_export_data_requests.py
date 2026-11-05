"""The data requests of a run are written in the order of the file; the views wait for the seal.

A request that fails does not stop the next one: every request has its turn,
then the failures are raised together, each named by its block.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.core.exceptions import ExportError
from hydromodpy.results.exporters import request as request_module
from hydromodpy.results.exporters.export_spec import load_export_requests


@pytest.fixture
def recorded(monkeypatch, tmp_path) -> list[str]:
    seen: list[str] = []

    def fake_request(_store, _sim_id, request, _target) -> list[Path]:
        seen.append(request.variables)
        if request.variables == "head":
            raise ValueError("cannot write head")
        return [tmp_path / f"{request.variables}.csv"]

    monkeypatch.setattr(request_module, "run_export_target", lambda _store, _sim_id: object())
    monkeypatch.setattr(request_module, "export_request", fake_request)
    return seen


def test_the_data_requests_run_in_file_order_and_the_views_wait(recorded, tmp_path) -> None:
    requests = load_export_requests(
        [
            {"variables": "discharge"},
            {"variables": "all", "format": "rocrate"},
            {"variables": "budget"},
        ]
    )

    written = request_module.export_data_requests(object(), "sim-1", requests)

    assert recorded == ["discharge", "budget"]
    assert written == [tmp_path / "discharge.csv", tmp_path / "budget.csv"]


def test_a_failed_request_does_not_stop_the_next_one(recorded) -> None:
    requests = load_export_requests([{"variables": "head"}, {"variables": "discharge"}])

    with pytest.raises(ExportError, match=r"export request 1 \(variables = head\)"):
        request_module.export_data_requests(object(), "sim-1", requests)
    assert recorded == ["head", "discharge"]
