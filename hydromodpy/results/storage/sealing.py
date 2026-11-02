"""The seal of a completed run, built from its store and written by it.

Why
---
The seal is what makes a run directory readable without the index. It used
to be a projection of SQL rows; here it is built from the facts the run
accumulated in its store (:mod:`hydromodpy.results.storage.run_facts`) and
from the files already in the directory, then written by
:class:`~hydromodpy.results.record.RunRecord` in the order the record
states, ``manifest.json`` last.

Order of the seal
-----------------
0. The declared projection is resolved to WKT2.
1. The field store gets its ACDD root attributes, the identity block and
   its consolidated metadata.
2. The record is written: tables, provenance, inputs, manifest.
3. ``README.md`` is rendered from the record and the label of the day.

What follows the seal (``outcome.json`` to ``completed``, the removal of
``<run>/.hmp/``) belongs to the attempt protocol
(:func:`hydromodpy.results.storage.attempt.close_sealed_attempt`), once the
pipeline has written its last journal row: the seal is a step, the close of
the attempt is the bracket around every step.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from hydromodpy.core.budget_terms import kept_budget
from hydromodpy.core.licensing import UNDETERMINED_LICENSE
from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.paths import (
    PROJECTS_DIRNAME,
    WORKSPACE_TOML_FILENAME,
    display_path,
    internal_dir,
    run_dir_rel,
)
from hydromodpy.core.version import __version__ as HMP_VERSION
from hydromodpy.results.catalog.registration import split_stem_version
from hydromodpy.results.checks import Checks
from hydromodpy.results.export.run_identity import label_of
from hydromodpy.results.manifest import (
    KEY_PACKAGES,
    RUN_RECORD_MANIFEST_VERSION,
    InputEntry,
    ManifestBudget,
    ManifestConfig,
    ManifestGeometry,
    ManifestPeriod,
    ManifestRun,
    read_manifest,
)
from hydromodpy.results.outcome import Outcome
from hydromodpy.results.readme import manifest_sha256, render_run_readme, write_readme
from hydromodpy.results.record import RunProvenance, RunRecord
from hydromodpy.results.storage.contract import RUN_CONFIG_FILENAME
from hydromodpy.results.storage.geo_metadata import wgs84_bounds
from hydromodpy.results.storage.json_io import readable
from hydromodpy.results.storage.run_facts import RunFacts
from hydromodpy.results.storage.run_store import RunStore
from hydromodpy.results.zarr_store import SimulationZarr

logger = get_logger(__name__)

IDENTITY_NOTICE_FILENAME: Final[str] = "identity_notice.json"
"""Marker under the workspace ``.hmp/`` recording what the identity warning already said."""

_DECLARED_IDENTITY_KEYS: Final[tuple[str, ...]] = ("creator_name", "creator_institution")
_UNKNOWN_LICENCE = "a known licence"


def seal_completed(store: RunStore, *, ended_at: datetime | None = None) -> RunRecord:
    """Seal the run of *store* as completed and return its record.

    The store is closed afterwards. The outcome is left as it is: the attempt
    protocol flips it to ``completed`` and drops ``<run>/.hmp/`` once nothing
    writes there any more.
    """
    when = ended_at if ended_at is not None else datetime.now(UTC)
    facts = store.facts
    if facts.solver is None:
        raise ValueError("a run seals with its solver named; the facts carry none")
    run_dir = store.run_dir
    _resolve_declared_crs(facts)
    _seal_field_store(store, when)
    record = build_record(store, ended_at=when)
    record.write(run_dir)
    label = label_of(record)
    write_readme(
        run_dir,
        render_run_readme(record, None, label, manifest_sha256=manifest_sha256(run_dir)),
    )
    store.close()
    return record


def _resolve_declared_crs(facts: RunFacts) -> None:
    """Store the projection of the run as WKT2, the form ``crs_wkt`` promises.

    The run declares its projection as a token (``EPSG:2154`` in
    ``[geographic] crs_project``), or only its catchment records one
    (``crs_proj``). Resolved once, at the seal, so the field store, the tables
    and the manifest state the same WKT. A projection pyproj cannot read
    leaves ``crs_wkt`` empty rather than holding a string no reader parses.
    """
    from pyproj import CRS
    from pyproj.exceptions import CRSError

    catchment = facts.geographic_metadata
    candidate = facts.crs_wkt or catchment.get("crs_proj") or catchment.get("crs_epsg")
    if not candidate:
        return
    try:
        crs = CRS.from_user_input(str(candidate))
    except CRSError as exc:
        logger.warning(
            "Run %s declares the projection %r, which pyproj cannot read: %s",
            facts.sim_id[:8],
            str(candidate)[:40],
            exc,
        )
        facts.crs_wkt = None
        return
    facts.crs_wkt = crs.to_wkt()
    epsg = crs.to_epsg()
    if epsg is not None:
        facts.crs_epsg = epsg


def build_record(store: RunStore, *, ended_at: datetime) -> RunRecord:
    """Return the record of the run of *store*, from its facts and its directory."""
    facts = store.facts
    run_dir = store.run_dir
    stem, version = split_stem_version(facts.name)
    duration = (ended_at - facts.started_at).total_seconds()
    run = ManifestRun(
        sim_id=facts.sim_id,
        name=facts.name,
        name_stem=stem,
        version=version or 1,
        status="completed",
        project=facts.project,
        case_id=facts.case_id,
        recipe=facts.recipe,
        rel_dir=run_dir_rel(facts.name),
        attempt=facts.attempt,
        attempt_id=facts.attempt_id,
        solver=str(facts.solver),
        solver_category=facts.solver_category,
        flow_regime=facts.flow_regime,
        created_at=facts.created_at,
        started_at=facts.started_at,
        ended_at=ended_at,
        duration_s=max(0.0, duration),
        description=facts.description,
        scientific_objective=facts.scientific_objective,
        contact_email=facts.contact_email,
        doi=facts.doi,
        license=store.licence(),
    )
    engine = _mesh_engine_of(run_dir)
    geometry = ManifestGeometry(
        n_cells=facts.n_cells,
        n_layers=facts.n_layers,
        mesh_topology=facts.mesh_topology,
        mesh_engine=engine.get("engine"),
        mesh_engine_version=engine.get("engine_version"),
        mesh_hash=facts.mesh_hash,
        crs_wkt=facts.crs_wkt,
        crs_epsg=facts.crs_epsg,
        bbox=facts.bbox,
        catchment=dict(facts.geographic_metadata),
    )
    period = ManifestPeriod(
        start=facts.period_start,
        end=facts.period_end,
        n_timesteps=facts.n_timesteps,
        time_unit=facts.time_unit,
    )
    config_file = RUN_CONFIG_FILENAME if (run_dir / RUN_CONFIG_FILENAME).is_file() else None
    if config_file is None:
        logger.warning(
            "Run %s has no %s: the resolved configuration was not frozen on disk.",
            facts.sim_id[:8],
            RUN_CONFIG_FILENAME,
        )
    identity = store.identity()
    checks = Checks(
        budget_pct=facts.budget_pct,
        budget_threshold_pct=facts.budget_threshold_pct,
        converged=facts.converged,
        score_window=identity.score_window,
        n_samples=None if facts.score is None else facts.score.nse_n,
        calibrated_by=facts.calibrated_by,
        validities=list(facts.validities),
        bounds_hit=list(facts.bounds_hit),
        code_reproducible=identity.code_reproducible,
    )
    return RunRecord(
        run=run,
        site=facts.site,
        geometry=geometry,
        period=period,
        config=ManifestConfig(file=config_file, hash=facts.config_hash, source=facts.config_source),
        lineage=facts.lineage,
        identity=identity,
        checks=checks,
        tracked_inputs=list(facts.tracked_inputs),
        inputs=loaded_and_declared_inputs(facts, store.data_root),
        parameters=list(facts.parameters),
        metrics=list(facts.metrics),
        score=facts.score,
        objective_name=facts.objective_name,
        objective_value=facts.objective_value,
        objective_window=facts.objective_window,
        budget=_budget_of(run_dir),
        provenance=build_provenance(facts, ended_at=ended_at),
    )


def loaded_and_declared_inputs(facts: RunFacts, data_root: Path | None) -> list[InputEntry]:
    """Return the inputs of ``inputs.json``: every loaded input, then every declared file.

    A file the configuration declares and no loaded record names (the DEM a
    catchment is cut from, a mapped network) is an input the run read too. It
    enters with its role as variable, the provider its sidecar names
    (``custom`` without one) and the licence its sidecar states. A declared
    folder is not an input: the files the run read in it are.
    """
    from hydromodpy.core.state.paths import decode_workspace_path
    from hydromodpy.schema.sources import input_licence, sidecar_source

    inputs = list(facts.inputs)
    named = {entry.path for entry in inputs}
    for tracked in facts.tracked_inputs:
        if tracked.path in named:
            continue
        located = (
            Path(tracked.path)
            if data_root is None
            else decode_workspace_path(data_root, tracked.path)
        )
        if not located.is_file():
            continue
        inputs.append(
            InputEntry(
                variable=tracked.role,
                provider=sidecar_source(located) or "custom",
                path=tracked.path,
                sha256=tracked.sha256,
                bytes=tracked.bytes,
                license=input_licence(located).spdx,
            )
        )
        named.add(tracked.path)
    return inputs


def build_provenance(facts: RunFacts, *, ended_at: datetime) -> RunProvenance:
    """Return ``provenance.json`` of the run: what produced the numbers."""
    env = facts.environment
    frozen = list(env.get("env_packages") or [])
    return RunProvenance(
        provenance_version=RUN_RECORD_MANIFEST_VERSION,
        sim_id=facts.sim_id,
        tool={"name": "hydromodpy", "version": env.get("hydromodpy_version") or HMP_VERSION},
        git={
            "commit": env.get("git_commit"),
            "dirty": env.get("git_dirty"),
            "project_commit": env.get("project_git_commit"),
        },
        python={"version": env.get("python_version")},
        platform={
            "platform": env.get("platform"),
            "hostname": env.get("hostname"),
            "user": env.get("user_name"),
            "cpu": dict(env.get("cpu_info") or {}),
            "memory_gb": env.get("memory_gb"),
        },
        packages=_key_package_versions(frozen),
        solver={
            "name": env.get("solver_name"),
            "engine": env.get("solver_engine"),
            "execution_mode": env.get("solver_execution_mode"),
            "version": env.get("solver_version_text"),
            "binary_path": env.get("solver_binary_path"),
            "binary_sha256": env.get("solver_binary_sha256"),
        },
        timing={
            "started_at": facts.started_at.isoformat(),
            "ended_at": ended_at.isoformat(),
            "duration_s": max(0.0, (ended_at - facts.started_at).total_seconds()),
        },
        environment={
            "conda_env_hash": env.get("conda_env_hash"),
            "rng_seed": env.get("rng_seed"),
            "packages_frozen": frozen,
            "binaries": _binaries_of(env),
        },
    )


def _binaries_of(env: dict[str, Any]) -> dict[str, dict[str, Any]]:
    name = env.get("solver_name")
    path = env.get("solver_binary_path")
    if not name or not path:
        return {}
    return {
        str(name): {
            "path": str(path),
            "sha256": env.get("solver_binary_sha256"),
            "version": env.get("solver_version_text"),
        }
    }


def _key_package_versions(frozen: list[Any]) -> dict[str, str]:
    """Return the :data:`KEY_PACKAGES` versions of a ``pip freeze`` list."""
    wanted = {name.lower(): name for name in KEY_PACKAGES}
    found: dict[str, str] = {}
    for line in frozen:
        text = str(line)
        if "==" not in text:
            continue
        name, _, version = text.partition("==")
        canonical = wanted.get(name.strip().lower())
        if canonical is not None:
            found[canonical] = version.strip()
    return dict(sorted(found.items()))


def _open_root(run_dir: Path) -> Any | None:
    """Return the root of the field store of a run, read-only, or None without one."""
    import zarr

    store_path = run_dir / "fields.zarr"
    if not store_path.is_dir():
        return None
    try:
        return zarr.open_group(str(store_path), mode="r", use_consolidated=False)
    except (FileNotFoundError, KeyError, ValueError, zarr.errors.GroupNotFoundError):
        return None


def _mesh_engine_of(run_dir: Path) -> dict[str, str]:
    root = _open_root(run_dir)
    mesh = None if root is None else root.get("mesh")
    if mesh is None:
        return {}
    return {
        key: str(mesh.attrs[key])
        for key in ("engine", "engine_version")
        if mesh.attrs.get(key) is not None
    }


def _budget_of(run_dir: Path) -> ManifestBudget | None:
    root = _open_root(run_dir)
    if root is None:
        return None
    kept = kept_budget(root)
    if kept is None:
        return None
    return ManifestBudget(policy=kept.policy, kept_terms=list(kept.terms))


# -- The field store at the seal -------------------------------------------


def _seal_field_store(store: RunStore, ended_at: datetime) -> None:
    """Write the ACDD attributes and the identity on the field store, then consolidate."""
    fields = store.fields_path
    if not fields.is_dir():
        return
    facts = store.facts
    workspace = store.workspace_path
    sz = SimulationZarr(fields)
    try:
        sz.harmonize_axis_references()
        written = sz.write_acdd_root_attrs(
            sim_row=_acdd_row(facts, licence=store.licence()),
            runs_env=_acdd_environment(facts.environment),
            project_table=_declared_identity(workspace),
            geographic_bounds=_bounds_in_degrees(facts),
        )
        store.identity().apply_to_zarr(sz.root)
        _warn_about_undeclared_identity(facts.sim_id, written, workspace)
        sz.consolidate_metadata()
    finally:
        sz.close()


def _acdd_row(facts: RunFacts, *, licence: str) -> dict[str, Any]:
    bbox = facts.bbox or (None, None, None, None)
    return {
        "sim_id": facts.sim_id,
        "name": facts.name,
        "description": facts.description,
        "solver": facts.solver,
        "scientific_objective": facts.scientific_objective,
        "period_start": facts.period_start,
        "period_end": facts.period_end,
        "time_unit": facts.time_unit,
        "crs_wkt": facts.crs_wkt,
        "crs_epsg": facts.crs_epsg,
        "bbox_xmin": bbox[0],
        "bbox_ymin": bbox[1],
        "bbox_xmax": bbox[2],
        "bbox_ymax": bbox[3],
        "contact_email": facts.contact_email,
        "doi": facts.doi,
        "config_hash": facts.config_hash,
        "license": licence,
    }


def _acdd_environment(env: dict[str, Any]) -> dict[str, Any]:
    return {
        key: env.get(key)
        for key in (
            "user_name",
            "hostname",
            "hydromodpy_version",
            "git_commit",
            "rng_seed",
            "solver_binary_sha256",
            "solver_version_text",
            "solver_name",
        )
    }


def _bounds_in_degrees(facts: RunFacts) -> dict[str, float] | None:
    crs = facts.crs_wkt
    if not crs and facts.crs_epsg is not None:
        crs = f"EPSG:{facts.crs_epsg}"
    return wgs84_bounds(facts.bbox, crs)


def _workspace_toml_path(root: Path | None) -> Path | None:
    """Return the ``workspace.toml`` that governs *root*, or None."""
    if root is None:
        return None
    start = Path(root).expanduser().resolve()
    for directory in (start, *start.parents):
        candidate = directory / WORKSPACE_TOML_FILENAME
        if candidate.is_file():
            return candidate
        if (directory / PROJECTS_DIRNAME).is_dir():
            return None
    return None


def _declared_identity(root: Path | None) -> dict[str, str]:
    """Return the creator identity ``workspace.toml`` declares, and nothing else."""
    toml_path = _workspace_toml_path(root)
    if toml_path is None:
        return {}
    from hydromodpy.core.workspace.workspace_toml import load_workspace_toml

    try:
        metadata = load_workspace_toml(toml_path.parent).workspace
    except Exception as exc:  # noqa: BLE001 - a bad file must not block a seal
        logger.debug("Could not read %s: %s", toml_path, exc)
        return {}
    return {
        key: str(getattr(metadata, key)).strip()
        for key in _DECLARED_IDENTITY_KEYS
        if str(getattr(metadata, key, "") or "").strip()
    }


def _identity_notice_path(root: Path | None) -> Path | None:
    if root is None:
        return None
    toml_path = _workspace_toml_path(root)
    base = toml_path.parent if toml_path is not None else Path(root).expanduser().resolve()
    return internal_dir(base) / IDENTITY_NOTICE_FILENAME


def _already_told(marker: Path | None) -> set[str]:
    if marker is None or not marker.is_file():
        return set()
    try:
        told = json.loads(marker.read_text(encoding="utf-8")).get("missing", [])
    except (OSError, ValueError, AttributeError) as exc:
        logger.debug("Could not read %s: %s", marker, exc)
        return set()
    return {str(item) for item in told} if isinstance(told, list) else set()


def _remember_told(marker: Path | None, missing: list[str]) -> None:
    if marker is None:
        return
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps({"missing": sorted(missing)}) + "\n", encoding="utf-8")
    except OSError as exc:
        logger.debug("Could not write %s: %s", marker, exc)


def _human_join(items: list[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return f"{', '.join(items[:-1])} and {items[-1]}"


def _warn_about_undeclared_identity(sid: str, attrs: dict, root: Path | None) -> None:
    """Say what a sealed run lacks: once per workspace, then at verbose level."""
    missing = [key for key in _DECLARED_IDENTITY_KEYS if not attrs.get(key)]
    if attrs.get("license") == UNDETERMINED_LICENSE:
        missing.append(_UNKNOWN_LICENCE)
    if not missing:
        return
    marker = _identity_notice_path(root)
    if set(missing) <= _already_told(marker):
        logger.info("Run %s is sealed without %s.", sid[:8], _human_join(missing))
        return
    advice: list[str] = []
    identity = [name for name in _DECLARED_IDENTITY_KEYS if name in missing]
    if identity:
        toml_path = _workspace_toml_path(root)
        if toml_path is None and root is not None:
            toml_path = Path(root).expanduser().resolve() / WORKSPACE_TOML_FILENAME
        where = display_path(toml_path) if toml_path is not None else WORKSPACE_TOML_FILENAME
        keys = " and ".join(f'{name} = "..."' for name in identity)
        advice.append(f"Add {keys} under [workspace] in {where}")
    if _UNKNOWN_LICENCE in missing:
        advice.append("a licence comes from the 'license' key of each input sidecar (<file>.json)")
    text = "; ".join(advice)
    logger.warning(
        "Runs of this workspace are sealed without %s. %s.",
        _human_join(missing),
        text[:1].upper() + text[1:],
    )
    _remember_told(marker, missing)


def sealed_config_hash(run_dir: Path) -> str | None:
    """Return ``identity.config_hash`` of a sealed run, or None.

    None when the directory is unsealed, and None when its manifest cannot be
    read: a run whose seal is unreadable matches nothing, which errs on the
    side of computing.
    """
    payload = readable(read_manifest, run_dir)
    identity = payload.get("identity") if isinstance(payload, dict) else None
    value = identity.get("config_hash") if isinstance(identity, dict) else None
    return None if value is None else str(value)


__all__ = [
    "IDENTITY_NOTICE_FILENAME",
    "Outcome",
    "build_provenance",
    "build_record",
    "seal_completed",
    "sealed_config_hash",
]
