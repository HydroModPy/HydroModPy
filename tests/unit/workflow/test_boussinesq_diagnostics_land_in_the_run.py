"""The VI diagnostics of a Boussinesq run land in ``<run>/exports/solver_diagnostics/``.

They used to be written beside the solver files, in the scratch the seal of a
completed run removes. They now go to the run directory, where
``hmp report compare`` reads them; a run without a store writes none.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.results.storage.run_store import SOLVER_DIAGNOSTICS_DIRNAME
from hydromodpy.solver.boussinesq.adapters import flow as flow_adapter


def _model(tmp_path: Path) -> SimpleNamespace:
    solver_dir = tmp_path / "scratch" / "solver"
    solver_dir.mkdir(parents=True)
    (solver_dir / "_boussinesq_summary.json").write_text(
        json.dumps({"runtime_engine": "petsc"}), encoding="utf-8"
    )
    return SimpleNamespace(full_path=str(solver_dir))


def test_the_diagnostics_are_written_into_the_exports_of_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    written: list[Path] = []
    monkeypatch.setattr(
        flow_adapter, "write_vi_obstacle_diagnostic_files", lambda d, s: written.append(d)
    )
    monkeypatch.setattr(
        flow_adapter, "write_ts_vi_obstacle_diagnostic_files", lambda d, s: written.append(d)
    )
    run_dir = tmp_path / "runs" / "nancon"
    store = SimpleNamespace(solver_diagnostics_dir=run_dir / "exports" / SOLVER_DIAGNOSTICS_DIRNAME)

    flow_adapter.BoussinesqFlowAdapter._persist_obstacle_diagnostics(
        SimpleNamespace(store=store), _model(tmp_path)
    )

    assert written == [run_dir / "exports" / "solver_diagnostics"] * 2


def test_a_run_without_a_store_writes_no_diagnostics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    written: list[Path] = []
    monkeypatch.setattr(
        flow_adapter, "write_vi_obstacle_diagnostic_files", lambda d, s: written.append(d)
    )

    flow_adapter.BoussinesqFlowAdapter._persist_obstacle_diagnostics(
        SimpleNamespace(store=None), _model(tmp_path)
    )

    assert written == []
    assert not (tmp_path / "scratch" / "solver" / "solver_diagnostics").exists()


def test_the_store_names_the_folder_under_the_exports_of_the_run(tmp_path: Path) -> None:
    from hydromodpy.results.storage.run_store import RunStore

    store = RunStore.__new__(RunStore)
    store._run_dir = tmp_path / "runs" / "nancon"  # noqa: SLF001 - path only, no facts needed

    assert store.solver_diagnostics_dir == tmp_path / "runs" / "nancon" / "exports" / (
        "solver_diagnostics"
    )
