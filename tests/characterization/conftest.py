"""Fixtures of the characterization tier: one real run, produced once.

Everything this tier asserts is read from a run a stranger could have produced:
one ``hmp run`` on a committed example project, through the real CLI. The
project is the synthetic Dupuit aquifer of ``examples/projects/00_getting_started``
because it is the cheapest complete pipeline in the repository (four seconds,
no network, no DEM) and it still writes every artefact the contract names.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from tests.regression.golden_utils import assert_required_executables, run_hmp_cli

REPO_ROOT = Path(__file__).resolve().parents[2]
CHARACTERIZATION_PROJECT = (
    REPO_ROOT / "examples" / "projects" / "00_getting_started" / "project.toml"
)
CHARACTERIZATION_RUN_NAME = "getting_started_dupuit"


@dataclass(frozen=True)
class ProducedRun:
    """One finished run and the workspace that holds it."""

    workspace: Path
    run_dir: Path
    run_name: str
    config: Path

    @property
    def field_store(self) -> Path:
        return self.run_dir / "fields.zarr"

    @property
    def tables(self) -> Path:
        return self.run_dir / "tables.parquet"

    @property
    def manifest(self) -> Path:
        return self.run_dir / "manifest.json"


@pytest.fixture(scope="session")
def produced_run(tmp_path_factory: pytest.TempPathFactory) -> ProducedRun:
    """Run the characterization project once through the real CLI."""
    assert_required_executables(require_modflow=True, require_modpath=False)
    workspace = tmp_path_factory.mktemp("characterization")
    run_hmp_cli(config_path=CHARACTERIZATION_PROJECT, out_path=workspace, timeout=900)
    run_dir = workspace / "runs" / CHARACTERIZATION_RUN_NAME
    if not run_dir.is_dir():
        produced = sorted(path.name for path in (workspace / "runs").glob("*"))
        raise AssertionError(f"run directory {run_dir} not produced; runs/ holds {produced}")
    return ProducedRun(
        workspace=workspace,
        run_dir=run_dir,
        run_name=CHARACTERIZATION_RUN_NAME,
        config=CHARACTERIZATION_PROJECT,
    )


@pytest.fixture(scope="session")
def live_project(tmp_path_factory: pytest.TempPathFactory):
    """Drive the same project in process and hand back the live ``Project``.

    The subprocess fixture above cannot answer what crosses a process boundary,
    because the CLI already destroyed everything by the time it returns. This
    one keeps the runtime state alive after a real simulation.
    """
    from hydromodpy.project.facade import Project

    assert_required_executables(require_modflow=True, require_modpath=False)
    workspace = tmp_path_factory.mktemp("characterization_live")
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("HMP_PROJECT_ROOT", str(workspace))
        patch.setenv("HMP_WORKSPACE", str(workspace))
        patch.setenv("MPLBACKEND", "Agg")
        project = Project(CHARACTERIZATION_PROJECT, headless=True, no_display=True)
        project.simulate(name="characterization_live")
        try:
            yield project
        finally:
            project.close()
