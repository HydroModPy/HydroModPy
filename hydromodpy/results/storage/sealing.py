"""The seal of a completed run, built from its store and written by it.

Why
---
The seal is what makes a run directory readable without the index. It used
to be a projection of SQL rows; here it is built from the facts the run
accumulated in its store (:mod:`hydromodpy.results.storage.run_facts`) and
from the files already in the directory, then written by
:class:`~hydromodpy.results.record.record.RunRecord` in the order the record
states, ``manifest.json`` last.

Order of the seal
-----------------
0. The declared projection is resolved to WKT2.
1. The field store gets its ACDD root attributes, the identity block and
   its consolidated metadata.
2. The value digests are taken: one per array and per quantity column, the
   rounded fields on the float64 values their writer received.
3. The mesh product the run cited is copied under ``mesh/``, for a replay to
   read it instead of asking the store.
4. The class of a replay is computed, and a strict replay refuses here, before
   any seal file is written.
5. The record is written: tables, provenance, inputs, manifest.
6. ``README.md`` is rendered from the record and the label of the day.

What follows the seal (``outcome.json`` to ``completed``, the removal of
``<run>/.hmp/``) belongs to the attempt protocol
(:func:`hydromodpy.results.storage.attempt.close_sealed_attempt`), once the
pipeline has written its last journal row: the seal is a step, the close of
the attempt is the bracket around every step.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from hydromodpy.core.budget.terms import kept_budget
from hydromodpy.core.code_fingerprint import RUN_LAYERS, code_fingerprint
from hydromodpy.core.io.filesystem import link_or_copy
from hydromodpy.core.licensing import UNDETERMINED_LICENSE
from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.layout import PROJECTS_DIRNAME, WORKSPACE_TOML_FILENAME, internal_dir
from hydromodpy.core.state.portable import display_path
from hydromodpy.core.state.result_dirs import run_dir_rel
from hydromodpy.core.version import __version__ as HMP_VERSION
from hydromodpy.results.catalog.registration import split_stem_version
from hydromodpy.results.products.cited import read_cited
from hydromodpy.results.products.store import ProductStore, products_root
from hydromodpy.results.readme import manifest_sha256, render_run_readme, write_readme
from hydromodpy.results.record.checks import Checks
from hydromodpy.results.record.label import label_of
from hydromodpy.results.record.manifest import (
    DERIVE_RULE_VERSION,
    KEY_PACKAGES,
    InputEntry,
    ManifestBudget,
    ManifestConfig,
    ManifestGeometry,
    ManifestPeriod,
    ManifestRun,
    read_manifest,
)
from hydromodpy.results.record.record import RunProvenance, RunRecord
from hydromodpy.results.record.replay_class import classify_replay
from hydromodpy.results.record.values import run_value_digests
from hydromodpy.results.storage.contract import MESH_DIRNAME, RUN_CONFIG_FILENAME
from hydromodpy.results.storage.digests import path_size_bytes, sha256_directory
from hydromodpy.results.storage.geo_metadata import wgs84_bounds
from hydromodpy.results.storage.json_io import readable
from hydromodpy.results.storage.run_facts import RunFacts
from hydromodpy.results.storage.run_profile import read_profile
from hydromodpy.results.storage.run_store import RunStore
from hydromodpy.results.zarr_store.simulation_zarr import SimulationZarr
from hydromodpy.schema.lineage import ProducerSide

logger = get_logger(__name__)

IDENTITY_NOTICE_FILENAME: Final[str] = "identity_notice.json"
"""Marker under the workspace ``.hmp/`` recording what the identity warning already said."""

_DECLARED_IDENTITY_KEYS: Final[tuple[str, ...]] = ("creator_name", "creator_institution")
_UNKNOWN_LICENCE = "a known licence"


def seal_completed(
    store: RunStore,
    *,
    ended_at: datetime | None = None,
    replay_of: str | Path | None = None,
    strict: bool = False,
    producer: Mapping[str, ProducerSide] | None = None,
    source_level: str | None = None,
) -> RunRecord:
    """Seal the run of *store* as completed and return its record.

    *replay_of* is the sealed run or published copy the run replays, and
    *producer* the provenance entries that differ from it. *source_level* is
    the level the replayed source was written at, read there by
    :func:`~hydromodpy.results.storage.kept.level_of`; a source below
    ``result`` lets the replay add keys without making a deviation. The tables
    of the record are written first, so the value digests cover every table;
    the class is computed from them before ``manifest.json`` is written; under
    ``strict`` a deviation raises
    :class:`~hydromodpy.results.record.replay_class.ReplayDeviationError` at
    that point, and the attempt keeps its fields and tables with no seal.

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
    _seal_mesh(store, replay_of)
    record = build_record(store, ended_at=when)
    record.write_tables(run_dir)
    digests = run_value_digests(run_dir, facts)
    if replay_of is not None:
        replay = classify_replay(
            replay_of,
            run_dir,
            digests,
            strict=strict,
            producer=producer or {},
            source_level=source_level,
        )
        facts.lineage = facts.lineage.model_copy(update={"replay": replay})
        record = record.model_copy(update={"lineage": facts.lineage})
    record.write_manifest(run_dir, values=digests, sealed_at=when)
    label = label_of(record, run_dir)
    write_readme(
        run_dir,
        render_run_readme(
            record,
            None,
            label,
            manifest_sha256=manifest_sha256(run_dir),
            profile=read_profile(run_dir),
            stored=frozenset(digests.digests),
            writes_face_flow=facts.writes_face_flow,
        ),
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
        n_samples=None if facts.score is None else facts.score.n_samples,
        calibrated_by=facts.calibrated_by,
        validities=list(facts.validities),
        bounds_hit=list(facts.bounds_hit),
        code_reproducible=identity.code_reproducible,
    )
    return RunRecord(
        derive_rule_version=DERIVE_RULE_VERSION,
        run=run,
        site=facts.site,
        geometry=geometry,
        period=period,
        config=ManifestConfig(file=config_file, source=facts.config_source),
        lineage=facts.lineage,
        identity=identity,
        checks=checks,
        tracked_inputs=list(facts.tracked_inputs),
        inputs=store.inputs(),
        parameters=list(facts.parameters),
        metrics=list(facts.metrics),
        score=facts.score,
        budget=_budget_of(run_dir),
        provenance=build_provenance(facts, ended_at=ended_at),
    )


def build_provenance(facts: RunFacts, *, ended_at: datetime) -> RunProvenance:
    """Return ``provenance.json`` of the run: what produced the numbers."""
    env = facts.environment
    frozen = list(env.get("env_packages") or [])
    environment: dict[str, Any] = {
        "conda_env_hash": env.get("conda_env_hash"),
        "rng_seed": env.get("rng_seed"),
        "packages_frozen": frozen,
        "binaries": _binaries_of(env),
    }
    if env.get("image"):
        environment["image"] = dict(env["image"])
    return RunProvenance(
        sim_id=facts.sim_id,
        tool={
            "name": "hydromodpy",
            "version": env.get("hydromodpy_version") or HMP_VERSION,
            "code_fingerprint": code_fingerprint(RUN_LAYERS),
        },
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
            "options": env.get("solver_options"),
        },
        timing={
            "started_at": facts.started_at.isoformat(),
            "ended_at": ended_at.isoformat(),
            "duration_s": max(0.0, (ended_at - facts.started_at).total_seconds()),
        },
        environment=environment,
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


# -- The mesh at the seal --------------------------------------------------


def _seal_mesh(store: RunStore, replay_of: str | Path | None = None) -> None:
    """Copy the mesh the run read under ``mesh/``, and cite it as an input.

    An engine that does not rebuild a mesh bit for bit reads it from the
    product store, and a replay of the run must read the same bytes. The
    product is never rewritten in place, so a hard link keeps its bytes even
    after an eviction; another volume falls back to a copy. A replay that read
    the ``mesh/`` sealed beside *replay_of* (``reused = "sealed"`` in its
    profile) seals those bytes, whatever the store holds. A product the store
    no longer holds is said and skipped: such a run seals without ``mesh/``,
    and a replay rebuilds the mesh as before.
    """
    from hydromodpy.mesh.stored import ARRAYS_FILENAME, DESCRIPTION_FILENAME

    facts, run_dir = store.facts, store.run_dir
    cited = [product for product in read_cited(run_dir) if product.kind == MESH_DIRNAME]
    if not cited:
        return
    if replay_of is not None and _mesh_read_sealed(run_dir):
        origin: Path | None = Path(replay_of) / MESH_DIRNAME
        what = f"The mesh sealed in {replay_of}"
    else:
        workspace = store.workspace_path
        if workspace is None:
            logger.warning(
                "Run %s cites a mesh product and has no project root: no %s/ is sealed.",
                facts.sim_id[:8],
                MESH_DIRNAME,
            )
            return
        origin = ProductStore(products_root(workspace)).get(cited[0].key)
        what = f"The mesh product {cited[0].key[:12]}"
        if origin is None:
            logger.warning(
                "%s cited by run %s is gone from the store: the run seals without %s/, "
                "and a replay rebuilds it.",
                what,
                facts.sim_id[:8],
                MESH_DIRNAME,
            )
            return
    sources = [origin / name for name in (DESCRIPTION_FILENAME, ARRAYS_FILENAME)]
    if not all(source.is_file() for source in sources):
        logger.warning(
            "%s read by run %s is incomplete: the run seals without %s/.",
            what,
            facts.sim_id[:8],
            MESH_DIRNAME,
        )
        return
    target = run_dir / MESH_DIRNAME
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    for source in sources:
        destination = target / source.name
        link_or_copy(source, destination)
    facts.put_input(
        InputEntry(
            variable=MESH_DIRNAME,
            provider="store",
            product=MESH_DIRNAME,
            path=MESH_DIRNAME,
            sha256=sha256_directory(target),
            bytes=path_size_bytes(target),
        )
    )


def _mesh_read_sealed(run_dir: Path) -> bool:
    """Return whether the last mesh step of *run_dir* read the mesh sealed beside its source."""
    profile = read_profile(run_dir)
    if profile is None:
        return False
    lines = [line for line in profile.lines if line.kind == "step" and line.name == MESH_DIRNAME]
    return bool(lines) and lines[-1].reused == "sealed"


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
        "solution_key": facts.solution_key,
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


def sealed_solution_key(run_dir: Path) -> str | None:
    """Return ``identity.solution_key`` of a sealed run, or None.

    The key is the one of
    :func:`~hydromodpy.results.record.request_identity.solution_key`: the
    request id plus the code, the solver binaries, the numeric packages and
    the mesh engine. None when the directory is unsealed, and None when its
    seal cannot be read: a run whose seal is unreadable matches nothing, which
    errs on the side of computing.
    """
    payload = readable(read_manifest, run_dir)
    identity = payload.get("identity") if isinstance(payload, dict) else None
    value = identity.get("solution_key") if isinstance(identity, dict) else None
    return None if value is None else str(value)


__all__ = [
    "IDENTITY_NOTICE_FILENAME",
    "build_provenance",
    "build_record",
    "seal_completed",
    "sealed_solution_key",
]
