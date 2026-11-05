"""Open the store of a freshly claimed run, the way the pipeline does, for a test.

No index is opened: the run directory is claimed under ``runs/`` of a
project, its facts are written and its field store is created with the grid
size given. The store is returned open; the caller closes it or seals it.
"""

from __future__ import annotations

from pathlib import Path

from hydromodpy.core.state.layout import PROJECT_MARKER_FILENAME
from hydromodpy.results.storage.attempt import RunClaim, claim_run_directory
from hydromodpy.results.storage.run_facts import RunFacts
from hydromodpy.results.storage.run_store import RunStore


def claim_run(project: Path, name: str, *, site: str | None = None) -> RunClaim:
    """Claim ``runs/<name>`` of *project*, creating the project marker when absent."""
    project.mkdir(parents=True, exist_ok=True)
    marker = project / PROJECT_MARKER_FILENAME
    if not marker.exists():
        marker.write_text("[workspace]\n", encoding="utf-8")
    return claim_run_directory(project, name, case_id=name, project=project.name, site=site)


def facts_of(
    claim: RunClaim,
    *,
    project: str,
    solver: str = "modflow6",
    n_cells: int | None = None,
    n_layers: int | None = None,
    n_timesteps: int | None = None,
    **extra: object,
) -> RunFacts:
    """Return the facts of a claimed run, as the prepare step would build them."""
    return RunFacts(
        sim_id=claim.sim_id,
        name=claim.name,
        case_id=claim.name,
        project=project,
        attempt=claim.attempt,
        attempt_id=claim.attempt_id,
        created_at=claim.started_at,
        started_at=claim.started_at,
        solver=solver,
        n_cells=n_cells,
        n_layers=n_layers,
        n_timesteps=n_timesteps,
        **extra,
    )


def open_run_store(
    project: Path,
    name: str = "run",
    *,
    n_cells: int = 4,
    n_layers: int = 1,
    n_timesteps: int | None = None,
    solver: str = "modflow6",
    site: str | None = None,
    create_zarr: bool = True,
    **extra: object,
) -> RunStore:
    """Claim ``runs/<name>`` and return its open store with an empty field store."""
    claim = claim_run(project, name, site=site)
    facts = facts_of(
        claim,
        project=project.name,
        solver=solver,
        n_cells=n_cells,
        n_layers=n_layers,
        n_timesteps=n_timesteps,
        **extra,
    )
    store = RunStore.open(claim.run_dir, facts=facts, workspace=project)
    if create_zarr:
        store.create_zarr(n_cells=n_cells, n_layers=n_layers)
    return store


__all__ = ["claim_run", "facts_of", "open_run_store"]
