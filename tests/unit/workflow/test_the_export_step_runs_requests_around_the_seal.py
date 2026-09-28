"""The export step writes the data requests before the seal and the run requests after it.

A data request (a field, a series, a layer) may read the per-cell budget the
step drops before the seal, so it runs first. The package and the metadata
views read the seal, so they run after it. The console says once, for the
whole run, how many files were written and where.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import hydromodpy.simulation.extraction.post_run as post_run_module
import hydromodpy.workflow.steps.export as export_module
from hydromodpy.core.config_kit.export_spec import load_export_requests
from hydromodpy.workflow.internals.state import PipelineState


def test_data_requests_run_before_the_seal_and_the_package_after(
    monkeypatch, tmp_path: Path, caplog
) -> None:
    order: list[str] = []
    requests = load_export_requests(
        [{"variables": "head", "time": "last"}, {"variables": "all", "format": "package"}]
    )
    store = SimpleNamespace(project_path=tmp_path)

    @contextmanager
    def fake_catalog(_ctx):
        yield store

    def fake_results(**kwargs):
        order.append("data")
        assert kwargs["export_requests"] == requests
        return [tmp_path / "share" / "run-1" / "head_last.tif"]

    def fake_package(**kwargs):
        order.append("package")
        return [tmp_path / "share" / "run-1" / "run-1.hmp"]

    monkeypatch.setattr(export_module, "run_is_catalogued", lambda _ctx: True)
    monkeypatch.setattr(export_module, "run_catalog", fake_catalog)
    monkeypatch.setattr(export_module, "step_save_run_artifacts", lambda *_a, **_k: None)
    monkeypatch.setattr(
        export_module, "step_drop_intermediate_budget", lambda *_a, **_k: order.append("drop")
    )
    monkeypatch.setattr(export_module, "step_seal_store", lambda *_a, **_k: order.append("seal"))
    monkeypatch.setattr(export_module, "step_cleanup_scratch", lambda *_a, **_k: None)
    monkeypatch.setattr(export_module, "step_cleanup_preprocessing", lambda *_a, **_k: 0)
    monkeypatch.setattr(export_module, "step_drop_empty_scratch", lambda *_a, **_k: None)
    monkeypatch.setattr(post_run_module, "auto_export_results", fake_results)
    monkeypatch.setattr(post_run_module, "auto_export_package", fake_package)
    monkeypatch.setattr(post_run_module, "cleanup_solver_outputs", lambda **_k: None)

    results_cfg = SimpleNamespace(
        keep_solver_files=True, persistence=SimpleNamespace(save_catalog=True)
    )
    ctx = SimpleNamespace(
        sim_id="0123456789abcdef",
        cfg=SimpleNamespace(simulation=SimpleNamespace(results=results_cfg), export=requests),
        effective_results_config=None,
        execution=SimpleNamespace(simulation_plan=SimpleNamespace(runs=())),
        setup=SimpleNamespace(run_id="run-1", workspace=None),
    )
    caplog.set_level(logging.INFO, logger=post_run_module.logger.name)

    export_module.ExportStep().run(
        PipelineState(run_id="run-1", step_index=7, data={"ctx": ctx, "wall_seconds": 1.0})
    )

    assert order == ["data", "drop", "seal", "package"]
    announced = [r.getMessage() for r in caplog.records if r.getMessage().startswith("Exported")]
    assert len(announced) == 1
    assert announced[0].startswith("Exported 2 file(s) -> ")
