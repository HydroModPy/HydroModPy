from __future__ import annotations

from types import SimpleNamespace

import pytest

from hydromodpy.spatial.geographic import store_ingestion
from hydromodpy.workflow import orchestrator as pipeline_module


def test_cleanup_run_explicit_keep_solver_files_overrides_results_config(tmp_path) -> None:
    scratch = tmp_path / ".solver_scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    (scratch / "keep.txt").write_text("preserve", encoding="utf-8")

    ctx = SimpleNamespace(
        _effective_results_cfg=SimpleNamespace(keep_solver_files=False),
        setup=SimpleNamespace(
            workspace=SimpleNamespace(solver_scratch_folder=scratch),
            geographic=None,
        ),
        store=None,
    )

    pipeline_module.cleanup_run(
        ctx,
        "sim-keep",
        keep_solver_files=True,
        save_artifacts=False,
        close_store=False,
    )

    assert scratch.exists()
    assert (scratch / "keep.txt").exists()


@pytest.mark.parametrize("write_intermediates", [True, False])
def test_cleanup_run_keeps_the_rasters_the_option_just_wrote(
    monkeypatch, write_intermediates: bool
) -> None:
    """``write_intermediates`` wrote them; the cleanup must not delete them."""
    dumped: list[object] = []
    kept: list[bool] = []
    monkeypatch.setattr(
        store_ingestion, "dump_cached_rasters_to_disk", lambda geo: dumped.append(geo)
    )
    monkeypatch.setattr(
        store_ingestion,
        "cleanup_stable_folder",
        lambda geo, *, keep=False: kept.append(keep) or 0,
    )

    geographic = SimpleNamespace(stable_folder=None)
    ctx = SimpleNamespace(
        cfg=SimpleNamespace(geographic=SimpleNamespace(write_intermediates=write_intermediates)),
        setup=SimpleNamespace(workspace=None, geographic=geographic),
        store=None,
    )

    pipeline_module.cleanup_run(ctx, "sim", save_artifacts=False, close_store=False)

    assert kept == [write_intermediates]
    assert dumped == ([geographic] if write_intermediates else [])
