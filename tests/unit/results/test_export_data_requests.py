"""The data requests of a run are written in the order of the file; the views wait for the seal.

A request that fails does not stop the next one: every request has its turn,
then the failures are raised together, each named by its block.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.core.exceptions import ExportError
from hydromodpy.results.exporters import request as request_module
from hydromodpy.results.exporters.export_spec import ExportRequest, load_export_requests
from hydromodpy.results.exporters.job import ExportTarget


@pytest.fixture
def recorded(monkeypatch, tmp_path) -> list[str]:
    seen: list[str] = []

    def fake_request(_store, _sim_id, request, _target, *, taken) -> list[Path]:
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


def test_the_ledger_line_of_a_block_never_carries_deliver_to(monkeypatch, tmp_path) -> None:
    """The registry is replayed by ``regen_exports``, and a replay delivers nothing."""
    seen: list[dict] = []

    def record(_directory, _path, *, producer, options, identity) -> None:
        seen.append(dict(options))

    monkeypatch.setattr(request_module, "record_derived_file", record)
    exports = tmp_path / "exports"
    exports.mkdir()
    written = exports / "head_last.tif"
    written.write_bytes(b"II*\x00 a raster")
    target = ExportTarget(
        run_dir=tmp_path,
        identity=SimpleNamespace(write_meta_json=lambda _path: None),
        model_crs=lambda: None,
        default_resolution=lambda: None,
        global_attrs=lambda: {},
    )
    request = ExportRequest.model_validate(
        {"variables": "head", "time": "last", "deliver_to": "/srv/depot/"}
    )

    request_module._stamp(written, request, target)

    (options,) = seen
    assert "deliver_to" not in options
    assert options == request.model_dump(mode="json", exclude_none=True, exclude={"deliver_to"})
