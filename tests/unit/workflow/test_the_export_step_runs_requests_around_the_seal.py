"""The data requests are written before the seal and the metadata views after it.

A data request (a field, a series, a layer) reads the fields of the run, so
the export step writes it. A metadata view (STAC, RO-Crate, PROV) renders the
seal, so :func:`step_after_seal` writes it once the run is sealed, from the
directory alone. Every file lands under ``runs/<run>/exports/`` and the
console says how many files were written and where.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import hydromodpy.results.exporters.request as request_module
import hydromodpy.simulation.extraction.post_run as post_run_module
import hydromodpy.workflow.steps.export as export_module
from hydromodpy.core.config_kit.export_spec import load_export_requests
from hydromodpy.results.identity import read_identity_from
from hydromodpy.results.ledger import Ledger
from hydromodpy.workflow.internals.state import PipelineState
from tests.unit.results._run_record_factory import make_record


def _ctx(run_dir: Path, requests) -> SimpleNamespace:
    results_cfg = SimpleNamespace(
        keep_solver_files=True, persistence=SimpleNamespace(save_catalog=True)
    )
    return SimpleNamespace(
        sim_id="0123456789abcdef",
        run_dir=run_dir,
        cfg=SimpleNamespace(simulation=SimpleNamespace(results=results_cfg), export=requests),
        execution=SimpleNamespace(simulation_plan=SimpleNamespace(runs=()), lightweight=False),
        setup=SimpleNamespace(run_id="run-1", workspace=None),
    )


def test_the_export_step_writes_the_data_requests_only(monkeypatch, tmp_path: Path) -> None:
    seen: list = []
    requests = load_export_requests(
        [{"variables": "head", "time": "last"}, {"variables": "all", "format": "rocrate"}]
    )

    @contextmanager
    def fake_store(_ctx):
        yield SimpleNamespace()

    def fake_results(_store, _sim_id, requests):
        seen.append(requests)
        return [tmp_path / "runs" / "run-1" / "exports" / "head_last.tif"]

    monkeypatch.setattr(export_module, "run_store", fake_store)
    monkeypatch.setattr(export_module, "step_cleanup_scratch", lambda *_a, **_k: None)
    monkeypatch.setattr(export_module, "step_cleanup_preprocessing", lambda *_a, **_k: 0)
    monkeypatch.setattr(export_module, "step_drop_empty_scratch", lambda *_a, **_k: None)
    monkeypatch.setattr(request_module, "export_data_requests", fake_results)
    monkeypatch.setattr(post_run_module, "cleanup_solver_outputs", lambda **_k: None)

    export_module.ExportStep().run(
        PipelineState(run_id="run-1", step_index=7, data={"ctx": _ctx(tmp_path, requests)})
    )

    assert seen == [requests]


def test_the_views_are_written_after_the_seal_from_the_directory(tmp_path: Path, caplog) -> None:
    record = make_record()
    run_dir = tmp_path / record.run.rel_dir
    run_dir.mkdir(parents=True)
    record.write(run_dir)
    requests = load_export_requests(
        [
            {"variables": "head", "time": "last"},
            {"variables": "all", "format": "rocrate", "folder": "crate"},
        ]
    )
    caplog.set_level(logging.INFO, logger=export_module.logger.name)

    written = export_module.step_after_seal(_ctx(run_dir, requests))

    crate = run_dir / "exports" / "crate" / "ro-crate-metadata.json"
    assert written == [crate]
    assert read_identity_from(crate).sim_id == record.run.sim_id
    assert [entry.file for entry in Ledger.read(run_dir / "exports").entries] == [
        "crate/ro-crate-metadata.json"
    ]
    announced = [r.getMessage() for r in caplog.records if r.getMessage().startswith("Exported")]
    assert announced == [announced[0]]
    assert announced[0].startswith("Exported 1 file(s) -> ")
