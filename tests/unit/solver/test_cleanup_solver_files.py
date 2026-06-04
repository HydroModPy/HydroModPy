"""Unit tests for solver output-file cleanup."""

from __future__ import annotations

from hydromodpy.solver.base.cleanup import cleanup_solver_files


class TestCleanupSolverFiles:
    def test_remove_all(self, tmp_path):
        d = tmp_path / "solver_output"
        d.mkdir()
        (d / "model.hds").write_text("head data")
        (d / "model.cbc").write_text("budget data")
        (d / "model.lst").write_text("listing")

        cleanup_solver_files(d)
        assert not d.exists()

    def test_keep_extensions(self, tmp_path):
        d = tmp_path / "solver_output"
        d.mkdir()
        (d / "model.hds").write_text("head data")
        (d / "model.lst").write_text("listing")
        (d / "model.nam").write_text("name file")

        cleanup_solver_files(d, keep={".lst", ".nam"})
        assert (d / "model.lst").exists()
        assert (d / "model.nam").exists()
        assert not (d / "model.hds").exists()
