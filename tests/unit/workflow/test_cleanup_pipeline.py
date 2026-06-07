from __future__ import annotations

from types import SimpleNamespace

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
