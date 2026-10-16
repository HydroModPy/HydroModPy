"""Which sealed runs a comparison reads, and whether they are the same case.

``hmp report compare <ref> <ref>...`` names runs, never a TOML. A reference is
a run directory, a run name under ``runs/`` of the project, or a recipe: the
latest version of every case of that recipe. Two runs compare as one case when
their ``manifest.json`` gives the same site fingerprint and the same mesh hash;
``allow_different_mesh`` lifts the mesh condition for a mesh comparison.
Everything here reads the run directories, never the project index.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import numpy as np

from hydromodpy.analysis.comparison.config import (
    ComparisonFineRaster,
    ComparisonObservable,
    ComparisonSimulation,
    MeshMode,
)
from hydromodpy.analysis.comparison.runtime.mesh import cells_from_run_mesh
from hydromodpy.analysis.comparison.runtime.physics import _variable_candidates
from hydromodpy.analysis.comparison.runtime.run_source import RunSource
from hydromodpy.core.state.paths import runs_dir_for
from hydromodpy.results.derive.virtual_fields import available_virtual_fields
from hydromodpy.results.manifest import is_sealed
from hydromodpy.results.record import RunRecord

DEFAULT_VARIABLES: tuple[str, ...] = ("watertable_elevation", "watertable_depth")
"""Variables mapped at the last step when ``--variables`` is not given, if every run has them."""

OUTLET_FLUX_VARIABLE = "outlet_flux"
"""Canonical outlet discharge, read at the outlet the manifests declare."""

HEAD_VARIABLE = "watertable_elevation"
"""Head variable, also read as a series at the outlet."""

_MESH_MODES: frozenset[str] = frozenset(
    {"triangle", "voronoi", "sgrid", "structured", "unstructured"}
)
_STRUCTURED_TOPOLOGIES: frozenset[str] = frozenset({"regular", "grid", "dis", "structured"})


class ComparisonReferenceError(LookupError):
    """A reference of ``hmp report compare`` names no sealed run."""


class ComparisonCaseError(ValueError):
    """The runs of one comparison are not the same case."""


@dataclass(frozen=True)
class ComparedRun:
    """One sealed run and its seal."""

    run_dir: Path
    record: RunRecord

    @classmethod
    def read(cls, run_dir: Path) -> ComparedRun:
        """Read the seal of the run in *run_dir*."""
        directory = Path(run_dir).expanduser().resolve()
        return cls(directory, RunRecord.read(directory))

    @property
    def name(self) -> str:
        """The run directory name, with its ``.vN``."""
        return self.record.run.name

    @property
    def site(self) -> str | None:
        """The site the run modelled, or None for a run without ``[site]``."""
        return self.record.identity.site

    @property
    def site_fingerprint(self) -> str | None:
        """Fingerprint of the site declaration of the run."""
        return self.record.identity.site_fingerprint

    @property
    def mesh_hash(self) -> str | None:
        """Hash of the mesh the run solved on."""
        return self.record.identity.mesh_hash


def _sealed_runs(project_root: Path) -> list[ComparedRun]:
    runs_dir = runs_dir_for(project_root)
    if not runs_dir.is_dir():
        return []
    return [
        ComparedRun.read(child)
        for child in sorted(runs_dir.iterdir())
        if child.is_dir() and is_sealed(child)
    ]


def _latest_of_recipe(runs: Iterable[ComparedRun], recipe: str) -> list[ComparedRun]:
    """Keep the highest version of every case of *recipe*."""
    latest: dict[str, ComparedRun] = {}
    for run in runs:
        if run.record.run.recipe != recipe:
            continue
        case = run.record.run.case_id
        held = latest.get(case)
        if held is None or run.record.run.version > held.record.run.version:
            latest[case] = run
    return [latest[case] for case in sorted(latest)]


def resolve_references(
    refs: Sequence[str], *, project_root: Path | None
) -> list[list[ComparedRun]]:
    """Return the sealed runs each reference names, one list per reference.

    A run directory or a run name gives one run; a recipe gives the latest run
    of each of its cases. Raises :class:`ComparisonReferenceError` with the
    reference when it names nothing sealed.
    """
    resolved: list[list[ComparedRun]] = []
    project_runs: list[ComparedRun] | None = None
    for ref in refs:
        path = Path(ref).expanduser()
        if is_sealed(path):
            resolved.append([ComparedRun.read(path)])
            continue
        if project_root is not None:
            named = runs_dir_for(project_root) / ref
            if is_sealed(named):
                resolved.append([ComparedRun.read(named)])
                continue
            if project_runs is None:
                project_runs = _sealed_runs(project_root)
            of_recipe = _latest_of_recipe(project_runs, ref)
            if of_recipe:
                resolved.append(of_recipe)
                continue
        where = "" if project_root is None else f" under {runs_dir_for(project_root)}"
        raise ComparisonReferenceError(
            f"{ref!r} names no sealed run{where}: give a run directory, a run name such "
            "as base.v2, or a recipe of the project."
        )
    return resolved


def group_runs(
    resolved: Sequence[Sequence[ComparedRun]], *, by_site: bool
) -> dict[str | None, list[ComparedRun]]:
    """Return the comparisons to make, keyed by site under ``by_site``, else one under None.

    Under ``by_site`` a site enters when at least two references hold a run of
    it; each reference gives at most one run per site.
    """
    if not by_site:
        flat = [run for runs in resolved for run in runs]
        if len({run.run_dir for run in flat}) != len(flat):
            raise ComparisonCaseError("The references name the same run twice.")
        return {None: flat}
    groups: dict[str | None, list[ComparedRun]] = {}
    for runs in resolved:
        seen: set[str | None] = set()
        for run in runs:
            if run.site in seen:
                raise ComparisonCaseError(
                    f"One reference holds two runs of site {run.site!r}: name the runs, "
                    "not their recipe, to compare them."
                )
            seen.add(run.site)
            groups.setdefault(run.site, []).append(run)
    return {site: runs for site, runs in sorted(groups.items(), key=_site_key) if len(runs) > 1}


def _site_key(item: tuple[str | None, list[ComparedRun]]) -> str:
    return item[0] or ""


@dataclass(frozen=True)
class CaseCheck:
    """The verdict that the compared runs are one case, written in the comparison manifest."""

    status: Literal["same_case", "different_mesh_allowed"]
    site: str | None
    site_fingerprint: str | None
    mesh_hashes: dict[str, str | None]
    allow_different_mesh: bool
    issues: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        """Return the ``case_check`` block of ``comparison_manifest.json``."""
        return {
            "status": self.status,
            "site": self.site,
            "site_fingerprint": self.site_fingerprint,
            "mesh_hashes": dict(self.mesh_hashes),
            "allow_different_mesh": self.allow_different_mesh,
            "issues": list(self.issues),
        }


def check_same_case(
    runs: Sequence[ComparedRun], *, allow_different_mesh: bool = False
) -> CaseCheck:
    """Check that *runs* share their site fingerprint and their mesh hash.

    Raises :class:`ComparisonCaseError` naming each run when the sites differ,
    or when the meshes differ and ``allow_different_mesh`` is False.
    """
    fingerprints = {run.site_fingerprint for run in runs}
    if len(fingerprints) > 1:
        detail = ", ".join(f"{run.name}: {run.site} ({run.site_fingerprint})" for run in runs)
        raise ComparisonCaseError(
            f"The runs model different sites ({detail}). Compare runs of one site, or "
            "pass --by site to compare the runs of each site."
        )
    mesh_hashes = {run.name: run.mesh_hash for run in runs}
    issues: list[str] = []
    if len(set(mesh_hashes.values())) > 1:
        detail = ", ".join(f"{name}: {mesh}" for name, mesh in mesh_hashes.items())
        if not allow_different_mesh:
            raise ComparisonCaseError(
                f"The runs solved on different meshes ({detail}). Pass "
                "--allow-different-mesh to compare meshes."
            )
        issues.append(f"different meshes, allowed: {detail}")
    return CaseCheck(
        status="different_mesh_allowed" if issues else "same_case",
        site=runs[0].site,
        site_fingerprint=runs[0].site_fingerprint,
        mesh_hashes=mesh_hashes,
        allow_different_mesh=allow_different_mesh,
        issues=tuple(issues),
    )


def _mesh_mode(topology: str | None) -> MeshMode:
    key = (topology or "").strip().lower()
    if key in _MESH_MODES:
        return key  # type: ignore[return-value]
    if key in _STRUCTURED_TOPOLOGIES:
        return "structured"
    return "unknown"


def comparison_simulation(run: ComparedRun) -> ComparisonSimulation:
    """Return the comparison entry of one run."""
    return ComparisonSimulation(
        id=run.name,
        label=run.name,
        run_dir=run.run_dir,
        solver=run.record.run.solver,
        mesh_label=run.mesh_hash,
        mesh_mode=_mesh_mode(run.record.geometry.mesh_topology),
    )


def simulation_summary(run: ComparedRun) -> dict[str, Any]:
    """Return what the exports and the report read of one run, from its seal."""
    record = run.record
    timing = record.provenance.timing
    flow_solve = timing.get("flow_solve_time_seconds")
    metrics: dict[str, Any] = {
        "wall_time_seconds": record.run.duration_s,
        "solvers": [record.run.solver],
    }
    if flow_solve is not None:
        metrics["flow_solve_time_seconds"] = flow_solve
    return {
        "id": run.name,
        "label": run.name,
        "status": "completed",
        "solver": record.run.solver,
        "mesh_label": run.mesh_hash or "",
        "mesh_mode": _mesh_mode(record.geometry.mesh_topology),
        "run_dir": str(run.run_dir),
        "run_folder": str(run.run_dir),
        "config_path": str(RunSource(run.run_dir, record).config_path),
        "sim_id": record.run.sim_id,
        "run_name": run.name,
        "case_id": record.run.case_id,
        "recipe": record.run.recipe,
        "site": run.site,
        "site_fingerprint": run.site_fingerprint,
        "mesh_hash": run.mesh_hash,
        "config_hash": record.identity.config_hash,
        "wall_time_seconds": record.run.duration_s,
        "flow_solve_time_seconds": flow_solve,
        "n_cells": record.geometry.n_cells,
        "n_layers": record.geometry.n_layers,
        "n_timesteps": record.period.n_timesteps,
        "mesh_topology": record.geometry.mesh_topology,
        "crs_wkt": record.geometry.crs_wkt,
        "crs_epsg": record.geometry.crs_epsg,
        "metrics": metrics,
    }


def _outlet(runs: Sequence[ComparedRun]) -> tuple[float, float] | None:
    """Return the outlet every run declares, snapped first; None when they disagree."""
    points: set[tuple[float, float]] = set()
    for run in runs:
        site = run.record.site
        if site is None:
            return None
        if site.snapped_outlet is not None:
            points.add((float(site.snapped_outlet[0]), float(site.snapped_outlet[1])))
        elif site.x_outlet is not None and site.y_outlet is not None:
            points.add((float(site.x_outlet), float(site.y_outlet)))
        else:
            return None
    return points.pop() if len(points) == 1 else None


def _readable(source: RunSource, variable: str) -> bool:
    """Return whether the run stores *variable*, or one of its aliases, or can derive it."""
    try:
        handle = source.open_zarr()
    except FileNotFoundError:
        return False
    try:
        root = handle.root
        derivable = set(available_virtual_fields(root))
        state = root.get("boussinesq_state")
        return any(
            name in root or name in derivable or (state is not None and name in state)
            for name in _variable_candidates(variable)
        )
    finally:
        handle.close()


def _readable_in_all(runs: Sequence[ComparedRun], variable: str) -> bool:
    for run in runs:
        with RunSource(run.run_dir, run.record) as source:
            if not _readable(source, variable):
                return False
    return True


def _map_name(variable: str) -> str:
    return "head_map_last" if variable == HEAD_VARIABLE else f"{variable}_map_last"


def comparison_observables(
    runs: Sequence[ComparedRun], variables: Sequence[str] | None
) -> list[ComparisonObservable]:
    """Return the observables of a comparison.

    Each variable is mapped at the last step. Given variables must be readable
    in every run; the default ones are kept when they are. When every run
    declares the same outlet, the head and the outlet discharge are also read
    there as series.
    """
    if variables:
        missing = [variable for variable in variables if not _readable_in_all(runs, variable)]
        if missing:
            raise ComparisonCaseError(
                f"Variables {missing} are not stored, nor derivable, in every compared run."
            )
        chosen = list(variables)
    else:
        chosen = [variable for variable in DEFAULT_VARIABLES if _readable_in_all(runs, variable)]
    observables = [
        ComparisonObservable(
            name=_map_name(variable),
            variable=variable,
            support="map",
            time="last",
            reducer="identity",
        )
        for variable in chosen
    ]
    outlet = _outlet(runs)
    if outlet is not None:
        x, y = outlet
        if HEAD_VARIABLE in chosen:
            observables.append(
                ComparisonObservable(
                    name="head_outlet_series", variable=HEAD_VARIABLE, x=x, y=y, unit="m"
                )
            )
        if _readable_in_all(runs, OUTLET_FLUX_VARIABLE):
            observables.append(
                ComparisonObservable(
                    name="outlet_flux_series",
                    variable=OUTLET_FLUX_VARIABLE,
                    support="outlet",
                    x=x,
                    y=y,
                    unit="m3/s",
                )
            )
    if not observables:
        raise ComparisonCaseError(
            "No variable is readable in every compared run: name some with --variables."
        )
    return observables


def comparison_fine_raster(reference: ComparedRun) -> ComparisonFineRaster | None:
    """Return the shared raster the maps are compared on, at the cell size of the reference.

    The cell size is the square root of the median cell area of the reference
    mesh. A reference without a stored mesh has no raster.
    """
    with RunSource(reference.run_dir, reference.record) as source:
        cells = cells_from_run_mesh(source, source.sim_id)
    if cells is None or cells.area_m2 is None:
        return None
    areas = np.asarray(cells.area_m2, dtype=float)
    areas = areas[np.isfinite(areas) & (areas > 0.0)]
    if areas.size == 0:
        return None
    return ComparisonFineRaster(enabled=True, resolution=float(np.sqrt(np.median(areas))))


__all__ = (
    "DEFAULT_VARIABLES",
    "CaseCheck",
    "ComparedRun",
    "ComparisonCaseError",
    "ComparisonReferenceError",
    "check_same_case",
    "comparison_fine_raster",
    "comparison_observables",
    "comparison_simulation",
    "group_runs",
    "resolve_references",
    "simulation_summary",
)
