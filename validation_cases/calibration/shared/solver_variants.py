"""Per-solver simulation configs for the twin calibration benchmarks.

A twin runs on every solver column that can host it: MODFLOW-NWT, MODFLOW 6 on
its structured grid, MODFLOW 6 on a triangle mesh, MODFLOW 6 on the Voronoi
dual of that mesh and the in-house Boussinesq solver on the same triangles,
with its PETSc engine (``boussinesq``) and its default local engine
(``boussinesq_local``). The analytical case of a twin holds one config per
solver. The builders here read them, point ``[mesh.triangle] path`` at an
absolute path (the paths in the case files are relative to the case folder, and
break once the config is written to the benchmark folder) and write one
project config.

``TWIN_SOLVERS`` is the single list of the solver columns a twin test
parametrizes. Adding a column means one more entry in ``VARIANTS`` and in the
test parameters, nothing else.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any

from validation_cases.shared.runtime import _dump_toml, _merge_toml_payloads, _read_toml


@dataclass(frozen=True, slots=True)
class SolverVariant:
    """How one solver column of a twin reads its case files."""

    column: str
    """Matrix column, also the suffix of the case id."""
    solver_name: str
    """Solver family written in the twin definition."""
    config_file: str
    """Case file holding the solver section, merged over the common files."""
    unstructured: bool = False
    """True when the mesh comes from a triangulation file, not from a regular grid."""
    engine: str | None = None
    """``triangle`` keeps one cell per triangle, ``voronoi`` one per vertex."""
    mesh_config_file: str | None = None
    """Case file that names the triangulation when ``config_file`` does not.

    The Boussinesq files of a case hold the ``[flow]`` engine keys only. The
    solver reads the triangles of the file that the triangle file names.
    """


VARIANTS: Mapping[str, SolverVariant] = {
    "modflow_nwt": SolverVariant(
        column="modflow_nwt",
        solver_name="modflow_nwt",
        config_file="config_modflownwt.toml",
    ),
    "modflow6": SolverVariant(
        column="modflow6",
        solver_name="modflow6",
        config_file="config_modflow6.toml",
    ),
    "modflow6_irregular_tri": SolverVariant(
        column="modflow6_irregular_tri",
        solver_name="modflow6",
        config_file="config_modflow6_irregular_tri.toml",
        unstructured=True,
        engine="triangle",
    ),
    "modflow6_voronoi": SolverVariant(
        column="modflow6_voronoi",
        solver_name="modflow6",
        config_file="config_modflow6_irregular_tri.toml",
        unstructured=True,
        engine="voronoi",
    ),
    "boussinesq": SolverVariant(
        column="boussinesq",
        solver_name="boussinesq",
        config_file="config_boussinesq.toml",
        unstructured=True,
        engine="triangle",
        mesh_config_file="config_modflow6_irregular_tri.toml",
    ),
    "boussinesq_local": SolverVariant(
        column="boussinesq_local",
        solver_name="boussinesq",
        config_file="config_boussinesq_local.toml",
        unstructured=True,
        engine="triangle",
        mesh_config_file="config_modflow6_irregular_tri.toml",
    ),
}

TWIN_SOLVERS: tuple[str, ...] = tuple(VARIANTS)
"""Solver columns a twin test parametrizes, in matrix order."""


def case_id_for(base_case_id: str, column: str) -> str:
    """Return the case id of one solver column.

    The structured MODFLOW 6 column keeps the id of the original twin, so its
    results and its history stay under the same name.
    """
    if column == "modflow6":
        return base_case_id
    stem = base_case_id.removesuffix("_modflow6")
    return f"{stem}_{column}"


def write_variant_config(
    path: Path,
    *,
    column: str,
    case_dir: Path,
    common_files: Sequence[str],
    run_id: str,
    planar: tuple[int, int] | None = None,
    bundle_dir: Path | None = None,
) -> None:
    """Write the simulation config of one solver column.

    The file names no project root: the caller writes it in a project folder,
    beside the ``project.toml`` that anchors the runs.

    Parameters
    ----------
    column
        Key of :data:`VARIANTS`.
    case_dir
        Analytical case folder holding the config files.
    common_files
        Case files merged first, in order, before the solver file.
    run_id
        Simulation name written in the config.
    planar
        ``(nx, ny)`` of the structured solver grid, for the solvers that mesh
        the domain themselves. The case file resolution is kept when ``None``.
    bundle_dir
        Folder of the ``mesh_2d.msh`` of the unstructured columns, replacing the
        file of the case config. Relative paths of the case file are resolved
        from ``case_dir``.
    """
    variant = VARIANTS[column]
    payload: dict[str, Any] = {}
    for name in (*common_files, variant.config_file):
        payload = _merge_toml_payloads(payload, _read_toml(case_dir / name))
    payload.setdefault("simulation", {})["name"] = str(run_id)
    # The truth is read back from the catalog and the trials from the solver
    # files. Compact storage rounds a field to 16 mantissa bits, about 1e-4 m
    # on a 10 m head, so the truth would differ from a trial at the truth.
    payload.setdefault("simulation", {}).setdefault("results", {}).setdefault("persistence", {})[
        "field_precision"
    ] = "exact"
    payload.setdefault("simulation", {}).setdefault("process", [{}])[0]["solvers"] = [
        variant.solver_name
    ]
    if variant.mesh_config_file is not None:
        mesh_payload = _read_toml(case_dir / variant.mesh_config_file)
        payload["mesh"] = copy.deepcopy(mesh_payload.get("mesh", {}))
    if variant.unstructured:
        mesh = payload.setdefault("mesh", {})
        triangle = mesh.setdefault("triangle", {})
        resolved = (
            Path(bundle_dir) / "mesh_2d.msh"
            if bundle_dir is not None
            else _absolute(case_dir, triangle["path"])
        )
        triangle["path"] = str(resolved)
        mesh["engine"] = str(variant.engine)
        mesh.pop("voronoi", None)
        if variant.engine == "voronoi":
            mesh["voronoi"] = {"seeds": "triangulation"}
    elif planar is not None:
        regular = payload.setdefault("mesh", {}).setdefault("regular", {})
        regular["shape"] = [int(planar[1]), int(planar[0])]
    path.write_text(_dump_toml(copy.deepcopy(payload)), encoding="utf-8", newline="\n")


def _absolute(case_dir: Path, raw: str) -> Path:
    """Resolve a path of a case file against the case folder."""
    candidate = Path(raw).expanduser()
    return candidate if candidate.is_absolute() else (case_dir / candidate).resolve()


def config_builder(
    column: str,
    *,
    case_dir: Path,
    common_files: Sequence[str],
    run_id: str,
    planar: tuple[int, int] | None = None,
    bundle_dir: Path | None = None,
) -> Callable[[Path], None]:
    """Return the ``build_simulation_config(path)`` of one column."""
    return partial(
        write_variant_config,
        column=column,
        case_dir=case_dir,
        common_files=tuple(common_files),
        run_id=run_id,
        planar=planar,
        bundle_dir=bundle_dir,
    )


def runnable_method_names(definition: Any) -> tuple[str, ...] | None:
    """Return the methods of ``definition`` that this environment can run.

    ``None`` means all of them. CMA-ES needs the ``cma`` package, which the PETSc
    environment does not ship. The other methods exercise the forward model of a
    solver just as well, so a leg that runs there drops CMA-ES and keeps the rest.
    """
    from importlib.util import find_spec

    if find_spec("cma") is not None:
        return None
    names = tuple(dict.fromkeys(str(profile.name) for profile in definition.method_profiles))
    return tuple(name for name in names if name != "cma_es")


def checks_for_methods(methods: Sequence[str] | None, checks: Mapping[str, Any]) -> dict[str, Any]:
    """Keep the checks of the methods that run, or all of them for ``None``."""
    if methods is None:
        return dict(checks)
    return {name: check for name, check in checks.items() if name in methods}
