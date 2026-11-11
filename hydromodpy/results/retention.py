"""What ``hmp catalog gc`` collects in a project, and what it weighs.

Why
---
The directories are the truth and the index is derived, so a collection that
asks the index what to remove removes what the index believes. Here every
decision reads the project tree: ``outcome.json`` and the heartbeat for the
state of an attempt, ``annotations.json`` for the protected tag, the
``.vN`` suffix for the versions of a name, ``trash/`` for what was deleted.

What
----
A plan has nine categories:

- ``stale_runs``: a run whose attempt stopped beating without an outcome.
  Its ``outcome.json`` is rewritten ``aborted``; its ``.hmp/`` is kept for a
  relaunch to resume from.
- ``stale_sessions``: a session whose attempt stopped beating. Its
  ``outcome.json`` and its ``session.json`` are rewritten ``aborted``, so the
  session can be trashed and the index stops showing it as running.
- ``superseded_runs``: the versions of a name beyond the ``keep_versions``
  newest. Moved to the trash.
- ``expired_runs``: the runs started more than ``max_age_days`` ago. Moved
  to the trash.
- ``expired_trash``: the trash entries older than
  :data:`TRASH_RETENTION_DAYS`. Removed, each leaving a tombstone, so its
  name is never given out again.
- ``dead_scratch``: the run scratch ``.hmp/scratch/<name>.p<pid>/`` whose
  process and resume holder are gone, or older than a day with no live run or
  session of that name, and ``.hmp/`` inside a sealed run. Removed. Any other
  folder of ``.hmp/scratch/`` (``_preprocessing/`` kept on request) stays.
- ``sealed_attempts``: what ``attempts/<n>/`` of a sealed run holds beside its
  ``outcome.json``. Removed; the outcome stays for the index, and an unsealed
  run keeps its attempts whole, since they serve a resume.
- ``old_trial_fields``: the ``fields.zarr/`` of a kept trial that reached the
  project more than ``trial_fields_days`` ago, all but the best, in a session
  that names one. Removed after ``purged.json`` says what leaves; a purge cut
  short is taken up again by the next ``gc``.
- ``products``: the product keys over the store cap, its live keys kept.
  ``gc -y`` removes exactly the keys the plan lists that are still not live.

A directory tagged :data:`~hydromodpy.results.trash.PROTECTED_TAG`, one a live
attempt writes into, and one this code cannot read, is never selected.

The same module weighs a run and a project by family. The index reads the
run weight; ``gc`` reports the project weight before and after.
"""

from __future__ import annotations

import shutil
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.host import death_is_proven, host_name
from hydromodpy.core.state.layout import (
    CATALOG_FILENAME,
    INTERNAL_DIRNAME,
    PRODUCTS_DIRNAME,
    TRIALS_DIRNAME,
    internal_dir,
    runs_dir_for,
    sessions_dir_for,
)
from hydromodpy.core.state.result_dirs import run_dir_rel, session_dir_rel
from hydromodpy.core.state.scratch import process_is_alive, run_scratch_pids, run_scratch_stem
from hydromodpy.results.catalog.registration import split_stem_version
from hydromodpy.results.field_registry import CONNECTION_CELLS, FACE_FLOW
from hydromodpy.results.outcome import (
    Outcome,
    OutcomeError,
    effective_status,
    read_outcome,
    write_outcome,
)
from hydromodpy.results.products.cited import alive_keys
from hydromodpy.results.products.store import ProductStore, products_root
from hydromodpy.results.record.manifest import is_sealed, read_seal
from hydromodpy.results.session.descriptor import read_session, write_session
from hydromodpy.results.storage.contract import (
    FIELDS_STORE_NAME,
    FINAL_STATE_DIRNAME,
    MESH_DIRNAME,
    PUBLICATION_FILENAME,
    PURGEABLE_TRIAL_ENTRIES,
    README_FILENAME,
    RUN_ANNOTATIONS_FILENAME,
    RUN_ATTEMPTS_DIRNAME,
    RUN_CONFIG_FILENAME,
    RUN_EXPORTS_DIRNAME,
    RUN_FIGURES_DIRNAME,
    RUN_INPUTS_FILENAME,
    RUN_LOGS_DIRNAME,
    RUN_MANIFEST_FILENAME,
    RUN_OUTCOME_FILENAME,
    RUN_PRODUCTS_FILENAME,
    RUN_PROFILE_FILENAME,
    RUN_PROVENANCE_FILENAME,
    RUN_PURGED_FILENAME,
    RUN_REPORT_DIRNAME,
    RUN_REQUEST_FILENAME,
    RUN_RESOLVED_CONFIG_FILENAME,
    RUN_SOLVER_DIRNAME,
    SESSION_DESCRIPTOR_FILENAME,
    SESSION_TRIAL_SERIES_DIRNAME,
    TABLES_DIRNAME,
)
from hydromodpy.results.storage.json_io import beside_seal, readable
from hydromodpy.results.storage.kept import Purged, level_of, write_purged
from hydromodpy.results.trash import (
    TrashedEntry,
    as_utc,
    expired_entries,
    is_protected,
    purge_trashed,
    trash_run,
)

logger = get_logger(__name__)

TRASH_RETENTION_DAYS = 30
"""Days a trashed directory stays restorable before ``gc -y`` removes it."""

DEFAULT_KEEP_VERSIONS = 5
"""Versions of one name ``gc`` keeps by default before trashing the older ones."""

DEFAULT_TRIAL_FIELDS_DAYS = 90
"""Days a kept trial keeps its fields before ``gc`` removes them, all but the best."""

DEAD_SCRATCH_AGE = timedelta(hours=24)
"""Age of the newest file past which the scratch of a run that does not run is removed."""

FAMILIES: tuple[str, ...] = (
    "fields",
    "budget",
    "face_flow",
    "tables",
    "documents",
    "renders",
    "solver_files",
    "history",
    "other",
    "runs",
    "trials",
    "series",
    "sessions_other",
    "products",
    "index",
    "scratch",
    "logs",
    "trash",
    "inputs",
    "data",
)
"""The families a weight is reported by, run families first.

One list for :func:`run_weight` and :func:`project_weight`. A family a run
does not carry is zero in a :class:`Weight`.
"""

_RUN_FAMILIES: tuple[str, ...] = FAMILIES[:9]
"""The families :func:`run_weight` reports."""

_DOCUMENT_NAMES = frozenset(
    {
        RUN_MANIFEST_FILENAME,
        RUN_CONFIG_FILENAME,
        RUN_RESOLVED_CONFIG_FILENAME,
        RUN_PROVENANCE_FILENAME,
        RUN_INPUTS_FILENAME,
        RUN_PRODUCTS_FILENAME,
        RUN_REQUEST_FILENAME,
        RUN_OUTCOME_FILENAME,
        RUN_ANNOTATIONS_FILENAME,
        RUN_PROFILE_FILENAME,
        RUN_PURGED_FILENAME,
        README_FILENAME,
        PUBLICATION_FILENAME,
    }
)
_FIELD_DIRS = frozenset({MESH_DIRNAME, FINAL_STATE_DIRNAME})
_RENDER_DIRS = frozenset({RUN_FIGURES_DIRNAME, RUN_EXPORTS_DIRNAME, RUN_REPORT_DIRNAME})
_HISTORY_DIRS = frozenset({RUN_ATTEMPTS_DIRNAME, RUN_LOGS_DIRNAME, INTERNAL_DIRNAME})
_LIVE_STATES = frozenset({"running", "stale"})


@dataclass(frozen=True, slots=True)
class RetentionPolicy:
    """How much run history ``gc`` keeps in a project.

    Prudent by default: only names with more than :attr:`keep_versions`
    versions are trimmed, age expiry is opt-in, and the fields of a kept
    trial stay for :attr:`trial_fields_days`.
    """

    keep_versions: int | None = DEFAULT_KEEP_VERSIONS
    """Newest versions kept per name. ``None`` disables the rule."""

    max_age_days: int | None = None
    """Age past which a run is trashed. ``None`` (default) disables the rule."""

    trial_fields_days: int | None = DEFAULT_TRIAL_FIELDS_DAYS
    """Age past which a kept trial loses its fields. ``None`` disables the rule."""


@dataclass(frozen=True, slots=True)
class Weight:
    """Bytes per family of one project, family absent counted as zero."""

    by_family: dict[str, int] = field(default_factory=dict)

    def total(self) -> int:
        """Return the bytes of every family."""
        return sum(self.by_family.values())

    def as_dict(self) -> dict[str, int]:
        """Return a copy of the bytes by family."""
        return dict(self.by_family)

    def __getitem__(self, family: str) -> int:
        return self.by_family.get(family, 0)


@dataclass(frozen=True, slots=True)
class GcPlan:
    """What ``gc`` would do in one project, and the bytes each category holds."""

    project_root: Path
    stale_runs: tuple[str, ...]
    stale_sessions: tuple[str, ...]
    superseded_runs: tuple[str, ...]
    expired_runs: tuple[str, ...]
    expired_trash: tuple[TrashedEntry, ...]
    dead_scratch: tuple[str, ...] = ()
    sealed_attempts: tuple[str, ...] = ()
    old_trial_fields: tuple[str, ...] = ()
    products: tuple[str, ...] = ()
    bytes: dict[str, int] = field(default_factory=dict)

    def categories(self) -> dict[str, list[str]]:
        """Return each category as the relative directories or trash names it holds."""
        return {
            "stale_runs": list(self.stale_runs),
            "stale_sessions": list(self.stale_sessions),
            "superseded_runs": list(self.superseded_runs),
            "expired_runs": list(self.expired_runs),
            "expired_trash": [entry.name for entry in self.expired_trash],
            "dead_scratch": list(self.dead_scratch),
            "sealed_attempts": list(self.sealed_attempts),
            "old_trial_fields": list(self.old_trial_fields),
            "products": list(self.products),
        }

    def bytes_of(self, category: str) -> int:
        """Return the bytes the plan holds for one category."""
        return self.bytes.get(category, 0)


@dataclass(frozen=True, slots=True)
class GcReport:
    """What one collection did to one project, and what the project weighed."""

    plan: GcPlan
    applied: bool
    freed: dict[str, int]
    before: Weight
    after: Weight


@dataclass(frozen=True, slots=True)
class _Version:
    rel_dir: str
    stem: str
    version: int
    started_at: datetime | None


@dataclass(frozen=True, slots=True)
class _TrialFields:
    """One sealed directory of a kept trial whose fields may leave."""

    rel_dir: str
    bytes: dict[str, int]


def level_at(run_dir: Path) -> str:
    """Return the level a run directory was written at.

    ``publication`` when the copy carries ``PUBLICATION.json``, otherwise the
    level of the lineage of its seal. An unreadable seal raises, and the
    caller treats that as a directory that matches nothing.
    """
    directory = Path(run_dir)
    if (directory / PUBLICATION_FILENAME).is_file():
        return "publication"
    return level_of(read_seal(directory).lineage)


def run_weight(run_dir: Path) -> dict[str, int]:
    """Return the bytes of one run directory, by family.

    ``fields`` is the field store outside its budget terms and its face
    flows, with the mesh and the final state; ``budget`` is everything under
    ``fields.zarr/budget/``; ``face_flow`` is ``face_flow`` and
    ``connection_cells``. The nine families hold the whole tree.
    """
    root = Path(run_dir)
    weights = dict.fromkeys(_RUN_FAMILIES, 0)
    for path in _files(root):
        weights[_run_family(path.relative_to(root).parts)] += _size(path)
    return weights


def project_weight(project_root: Path) -> Weight:
    """Return the bytes of one project, by family.

    Every file of a run counts in ``runs``, which is the sum of the run
    directories; :func:`run_weight` splits one. A session file counts in
    ``trials``, ``series`` or ``sessions_other``. The index, the product
    store, the scratch, the logs, the trash, the inputs and the data have their
    own family; the rest of the project is ``other``.
    """
    root = Path(project_root)
    families = dict.fromkeys(FAMILIES, 0)
    for path in _files(root):
        parts = path.relative_to(root).parts
        bytes_here = _size(path)
        head = parts[0]
        if head == "runs" and len(parts) > 2:
            families["runs"] += bytes_here
        elif head == "sessions" and len(parts) > 2:
            families[_session_family(parts[2:])] += bytes_here
        elif head == "trash":
            families["trash"] += bytes_here
        elif head == "inputs":
            families["inputs"] += bytes_here
        elif head == "data":
            families["data"] += bytes_here
        elif head == INTERNAL_DIRNAME and len(parts) > 1:
            families[_internal_family(parts[1])] += bytes_here
        else:
            families["other"] += bytes_here
    return Weight(families)


def plan_gc(
    project_root: Path,
    policy: RetentionPolicy,
    *,
    now: datetime,
    products_cap_bytes: int | None = None,
) -> GcPlan:
    """Return what ``gc`` would do in ``project_root``, touching nothing.

    ``products_cap_bytes`` caps the product store; ``None`` leaves the store
    out of the plan.
    """
    root = Path(project_root)
    stale: list[str] = []
    eligible: list[_Version] = []
    for run_dir in _dirs(runs_dir_for(root)):
        rel_dir = run_dir_rel(run_dir.name)
        state = effective_status(run_dir, now=now)
        if state == "stale" and _death_is_proven_for(run_dir):
            # A silent heartbeat alone is no proof: the process may live on
            # another host or sit in a long step. Such a run is left running.
            stale.append(rel_dir)
        if state in _LIVE_STATES or state == "unreadable" or is_protected(run_dir):
            continue
        stem, version = split_stem_version(run_dir.name)
        eligible.append(_Version(rel_dir, stem, version or 1, _started_at(run_dir)))

    superseded = _superseded(eligible, policy.keep_versions)
    taken = set(superseded)
    expired: list[str] = []
    if policy.max_age_days is not None:
        cutoff = as_utc(now) - timedelta(days=policy.max_age_days)
        expired = [
            item.rel_dir
            for item in eligible
            if item.rel_dir not in taken
            and item.started_at is not None
            and item.started_at < cutoff
        ]
    old_trash = [
        entry
        for entry in expired_entries(root, older_than=timedelta(days=TRASH_RETENTION_DAYS), now=now)
        if not is_protected(entry.path)
    ]
    stale_sessions = [
        session_dir_rel(session_dir.name)
        for session_dir in _dirs(sessions_dir_for(root))
        if effective_status(session_dir, now=now) == "stale"
    ]
    dead_scratch = _dead_scratch(root, now)
    sealed_attempts = _sealed_attempts(root)
    trials = _trial_fields(root, policy, now)
    products = _product_eviction(root, products_cap_bytes)
    weights = {
        "stale_runs": 0,
        "stale_sessions": 0,
        "superseded_runs": _bytes_of(root, superseded),
        "expired_runs": _bytes_of(root, expired),
        "expired_trash": sum(_size(entry.path) for entry in old_trash),
        "dead_scratch": _bytes_of(root, dead_scratch),
        "sealed_attempts": _bytes_of(root, sealed_attempts),
        "old_trial_fields": sum(sum(item.bytes.values()) for item in trials),
        "products": products[1],
    }
    return GcPlan(
        project_root=root,
        stale_runs=tuple(stale),
        stale_sessions=tuple(stale_sessions),
        superseded_runs=tuple(superseded),
        expired_runs=tuple(expired),
        expired_trash=tuple(old_trash),
        dead_scratch=tuple(dead_scratch),
        sealed_attempts=tuple(sealed_attempts),
        old_trial_fields=tuple(item.rel_dir for item in trials),
        products=products[0],
        bytes=weights,
    )


def apply_gc(plan: GcPlan, *, now: datetime) -> dict[str, int]:
    """Carry out ``plan`` and return the bytes each category freed, read before removal."""
    root = plan.project_root
    freed = {
        "stale_runs": 0,
        "stale_sessions": 0,
        "superseded_runs": 0,
        "expired_runs": 0,
        "expired_trash": 0,
        "dead_scratch": 0,
        "sealed_attempts": 0,
        "old_trial_fields": 0,
        "products": 0,
    }
    for rel_dir in plan.stale_runs:
        mark_aborted(root / rel_dir, now=now)
    for rel_dir in plan.stale_sessions:
        _close_session(root / rel_dir, now=now)
    for rel_dir in plan.superseded_runs:
        freed["superseded_runs"] += _size(root / rel_dir)
        trash_run(root, rel_dir, now=now)
    for rel_dir in plan.expired_runs:
        freed["expired_runs"] += _size(root / rel_dir)
        trash_run(root, rel_dir, now=now)
    trash_bytes = sum(_size(entry.path) for entry in plan.expired_trash)
    purged = purge_trashed(root, list(plan.expired_trash), now=now)
    freed["expired_trash"] = trash_bytes if purged else 0
    for rel_dir in plan.dead_scratch:
        freed["dead_scratch"] += _remove(root / rel_dir)
    for rel_path in plan.sealed_attempts:
        freed["sealed_attempts"] += _remove(root / rel_path)
    for item in plan.old_trial_fields:
        freed["old_trial_fields"] += _purge_trial_fields(root / item, now=now)
    freed["products"] = _discard_products(root, plan.products)
    return freed


def gc(
    project_root: Path,
    policy: RetentionPolicy,
    *,
    now: datetime,
    products_cap_bytes: int,
    dry_run: bool,
) -> GcReport:
    """Measure a project, plan the collection, then carry it out unless *dry_run*."""
    root = Path(project_root)
    before = project_weight(root)
    plan = plan_gc(root, policy, now=now, products_cap_bytes=products_cap_bytes)
    if dry_run:
        return GcReport(plan=plan, applied=False, freed={}, before=before, after=before)
    freed = apply_gc(plan, now=now)
    return GcReport(plan=plan, applied=True, freed=freed, before=before, after=project_weight(root))


def mark_aborted(run_dir: Path, *, now: datetime) -> Outcome:
    """Rewrite the outcome of a stale attempt as ``aborted`` and return it."""
    outcome = read_outcome(run_dir)
    if outcome is None:
        raise FileNotFoundError(f"{run_dir} holds no outcome.json to close")
    closed = outcome.model_copy(
        update={
            "status": "aborted",
            "ended_at": as_utc(now),
            "written_by": "launcher",
            "error": OutcomeError(
                type="stale",
                message=(
                    f"no heartbeat since the attempt on {outcome.host} (pid {outcome.pid}); "
                    f"closed by gc on {host_name()}"
                ),
            ),
        }
    )
    write_outcome(run_dir, closed)
    return closed


def _close_session(session_dir: Path, *, now: datetime) -> None:
    """Close a stale session: its outcome, then its descriptor, say ``aborted``."""
    closed = mark_aborted(session_dir, now=now)
    if not (session_dir / SESSION_DESCRIPTOR_FILENAME).is_file():
        return
    descriptor = readable(read_session, session_dir)
    if descriptor is None or descriptor.status != "running":
        return
    assert closed.error is not None
    write_session(
        session_dir,
        descriptor.model_copy(
            update={
                "status": "aborted",
                "ended_at": closed.ended_at,
                "error_message": closed.error.message,
            }
        ),
    )


def _death_is_proven_for(run_dir: Path) -> bool:
    """Whether the attempt of ``run_dir`` ran on this host and its process is gone."""
    if is_sealed(run_dir):
        outcome = beside_seal(read_outcome, run_dir, RUN_OUTCOME_FILENAME)
    else:
        outcome = readable(read_outcome, run_dir)
    return outcome is not None and death_is_proven(outcome.host, outcome.pid)


def _dead_scratch(root: Path, now: datetime) -> list[str]:
    """Return the scratch directories whose writer is gone, under the project or a sealed run."""
    cutoff = as_utc(now) - DEAD_SCRATCH_AGE
    out: list[str] = []
    scratch = internal_dir(root) / "scratch"
    for child in _dirs(scratch):
        stem = run_scratch_stem(child.name)
        if stem is None:
            # Not the folder of one run: ``_preprocessing/`` kept on request, say.
            continue
        if _live_run_named(root, stem, now=now):
            continue
        pids = run_scratch_pids(scratch, child.name)
        if not any(process_is_alive(pid) for pid in pids) or _newest_write(child) < cutoff:
            out.append(f"{INTERNAL_DIRNAME}/scratch/{child.name}")
    for run_dir in _dirs(runs_dir_for(root)):
        internal = run_dir / INTERNAL_DIRNAME
        if not internal.is_dir() or not is_sealed(run_dir):
            continue
        dead = _death_is_proven_for(run_dir)
        if dead or (
            _newest_write(internal) < cutoff
            and effective_status(run_dir, now=now) not in _LIVE_STATES
        ):
            out.append(f"{run_dir_rel(run_dir.name)}/{INTERNAL_DIRNAME}")
    return out


def _sealed_attempts(root: Path) -> list[str]:
    """Return what the earlier attempts of each sealed run hold beside their outcome.

    ``attempts/<n>/outcome.json`` stays: the index reads it for the history of
    the run.
    """
    out: list[str] = []
    for run_dir in _dirs(runs_dir_for(root)):
        attempts = run_dir / RUN_ATTEMPTS_DIRNAME
        if not attempts.is_dir() or not is_sealed(run_dir):
            continue
        rel_attempts = f"{run_dir_rel(run_dir.name)}/{RUN_ATTEMPTS_DIRNAME}"
        for attempt in _dirs(attempts):
            for entry in sorted(attempt.iterdir()):
                if entry.name != RUN_OUTCOME_FILENAME:
                    out.append(f"{rel_attempts}/{attempt.name}/{entry.name}")
    return out


def _trial_fields(root: Path, policy: RetentionPolicy, now: datetime) -> list[_TrialFields]:
    """Return the sealed trial directories whose fields are older than the policy allows.

    The age runs from the later of the seal and the arrival of the directory
    in this project (its inode change), so the trials of an imported session
    count from the import. A session that names no single best keeps every
    trial. A trial whose ``purged.json`` stands beside fields still on the
    disk is a purge cut short, taken up again.
    """
    if policy.trial_fields_days is None:
        return []
    cutoff = as_utc(now) - timedelta(days=policy.trial_fields_days)
    out: list[_TrialFields] = []
    for session_dir in _dirs(sessions_dir_for(root)):
        descriptor = readable(read_session, session_dir)
        if descriptor is None or descriptor.status == "running" or descriptor.best is None:
            continue
        best = descriptor.best.trial
        for trial_dir in _dirs(session_dir / TRIALS_DIRNAME):
            if _trial_number(trial_dir.name) == best or is_protected(trial_dir):
                continue
            for sealed in _sealed_trial_dirs(trial_dir):
                if is_protected(sealed):
                    continue
                seal = readable(read_seal, sealed)
                if seal is None or seal.lineage.kind != "trial":
                    continue
                if max(as_utc(seal.sealed_at), _arrival(sealed)) >= cutoff:
                    continue
                bytes_here = {
                    name: _size(sealed / name)
                    for name in sorted(PURGEABLE_TRIAL_ENTRIES)
                    if (sealed / name).exists()
                }
                if bytes_here:
                    rel = sealed.relative_to(root).as_posix()
                    out.append(_TrialFields(rel, bytes_here))
    return out


def _sealed_trial_dirs(trial_dir: Path) -> list[Path]:
    """Return the sealed directories of a kept trial, itself or one per case."""
    if is_sealed(trial_dir):
        return [trial_dir]
    return [child for child in _dirs(trial_dir) if is_sealed(child)]


def _product_eviction(root: Path, cap_bytes: int | None) -> tuple[tuple[str, ...], int]:
    """Return the product keys over the cap and the bytes they hold, touching nothing."""
    if cap_bytes is None:
        return (), 0
    store = ProductStore(products_root(root))
    report = store.evict(cap_bytes, keep=alive_keys(root), dry_run=True)
    items = tuple(
        f"{INTERNAL_DIRNAME}/{PRODUCTS_DIRNAME}/{key[:2]}/{key}" for key in report.removed
    )
    return items, report.freed


def _discard_products(root: Path, items: tuple[str, ...]) -> int:
    """Remove the product keys the plan listed, unless a run cites one since; return bytes."""
    if not items:
        return 0
    store = ProductStore(products_root(root))
    held = {entry.key: entry.bytes for entry in store.entries()}
    alive = alive_keys(root)
    freed = 0
    for item in items:
        key = Path(item).name
        if key in alive or key not in held:
            continue
        store.discard(key)
        if store.get(key) is None:
            freed += held[key]
    return freed


def _purge_trial_fields(directory: Path, *, now: datetime) -> int:
    """Write ``purged.json``, then remove the fields it names; return the bytes removed.

    The witness comes first, so a ``gc`` cut short never leaves an absence
    nobody names. A witness that stands beside fields still on the disk is a
    purge cut short: it stays as written, and the fields leave now.
    """
    entries = {
        name: _size(directory / name)
        for name in sorted(PURGEABLE_TRIAL_ENTRIES)
        if (directory / name).exists()
    }
    if not entries:
        return 0
    if not (directory / RUN_PURGED_FILENAME).is_file():
        write_purged(directory, Purged(at=as_utc(now), entries=entries))
    return sum(_remove(directory / name) for name in entries)


def _remove(path: Path) -> int:
    """Remove a file or a tree and return its bytes, or 0 with a warning when it stays."""
    bytes_here = _size(path)
    try:
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("gc could not remove %s, the next gc takes it up again: %s", path, exc)
        return 0
    return bytes_here


def _live_run_named(root: Path, stem: str, *, now: datetime) -> bool:
    """Whether a run or a session of the project carries *stem* in its name and may still run."""
    for directory in (*_dirs(runs_dir_for(root)), *_dirs(sessions_dir_for(root))):
        if split_stem_version(directory.name)[0] != stem:
            continue
        if effective_status(directory, now=now) in _LIVE_STATES:
            return True
    return False


def _trial_number(name: str) -> int | None:
    return int(name) if name.isdigit() else None


def _run_family(parts: tuple[str, ...]) -> str:
    """Return the family of one path inside a run directory."""
    head = parts[0]
    if head == FIELDS_STORE_NAME:
        inner = parts[1] if len(parts) > 1 else ""
        if inner == "budget":
            return "budget"
        if inner in (FACE_FLOW, CONNECTION_CELLS):
            return "face_flow"
        return "fields"
    if head == TABLES_DIRNAME:
        return "tables"
    if head in _RENDER_DIRS:
        return "renders"
    if head == RUN_SOLVER_DIRNAME:
        return "solver_files"
    if head in _HISTORY_DIRS:
        return "history"
    if head in _DOCUMENT_NAMES:
        return "documents"
    if head in _FIELD_DIRS:
        return "fields"
    return "other"


def _session_family(parts: tuple[str, ...]) -> str:
    """Return the family of one path below ``sessions/<name>/``."""
    if parts and parts[0] == TRIALS_DIRNAME:
        return "trials"
    if parts and parts[0] == SESSION_TRIAL_SERIES_DIRNAME:
        return "series"
    return "sessions_other"


def _internal_family(name: str) -> str:
    """Return the family of one entry of ``.hmp/``."""
    if name == PRODUCTS_DIRNAME:
        return "products"
    if name == "scratch":
        return "scratch"
    if name == "logs":
        return "logs"
    if name.startswith(CATALOG_FILENAME):
        return "index"
    return "other"


def _files(tree: Path) -> list[Path]:
    """Return the files under *tree*, deepest last, without following a link twice."""
    if not tree.is_dir():
        return []
    return [path for path in sorted(tree.rglob("*")) if path.is_file()]


def _size(path: Path) -> int:
    """Return the bytes of a file, or of every file under a directory."""
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    if not path.is_dir():
        return 0
    total = 0
    for child in path.rglob("*"):
        if child.is_file():
            try:
                total += child.stat().st_size
            except OSError:
                pass
    return total


def _newest_write(tree: Path) -> datetime:
    """Return the last write of a tree, its deepest files and folders included, UTC."""
    stamps = [tree.stat().st_mtime]
    for child in tree.rglob("*"):
        try:
            stamps.append(child.stat().st_mtime)
        except OSError:
            continue  # A file a neighbour removed meanwhile has no stamp to give.
    return datetime.fromtimestamp(max(stamps), tz=UTC)


def _arrival(directory: Path) -> datetime:
    """Return when a directory reached this disk: its inode change, which no copy keeps."""
    return datetime.fromtimestamp(directory.stat().st_ctime, tz=UTC)


def _bytes_of(root: Path, rel_dirs: list[str] | tuple[str, ...]) -> int:
    return sum(_size(root / rel_dir) for rel_dir in rel_dirs)


def _dirs(tree: Path) -> list[Path]:
    if not tree.is_dir():
        return []
    return sorted(entry for entry in tree.iterdir() if entry.is_dir())


def _superseded(versions: list[_Version], keep: int | None) -> list[str]:
    """Return the versions beyond the ``keep`` newest of their name, oldest first."""
    if keep is None:
        return []
    by_stem: dict[str, list[_Version]] = defaultdict(list)
    for item in versions:
        by_stem[item.stem].append(item)
    superseded: list[str] = []
    for _stem, group in sorted(by_stem.items()):
        newest_first = sorted(group, key=lambda item: item.version, reverse=True)
        dropped = sorted(newest_first[keep:], key=lambda item: item.version)
        superseded.extend(item.rel_dir for item in dropped)
    return superseded


def _started_at(run_dir: Path) -> datetime | None:
    """Return when the run started: its outcome, else its seal; ``None`` when neither says.

    A run reaches this function after :func:`effective_status` read its seal, or
    its outcome when it has no seal.
    """
    if not is_sealed(run_dir):
        outcome = read_outcome(run_dir)
        return None if outcome is None else as_utc(outcome.started_at)
    outcome = beside_seal(read_outcome, run_dir, RUN_OUTCOME_FILENAME)
    if outcome is not None:
        return as_utc(outcome.started_at)
    run = read_seal(run_dir).run
    return as_utc(run.started_at or run.created_at)


__all__ = [
    "DEAD_SCRATCH_AGE",
    "DEFAULT_KEEP_VERSIONS",
    "DEFAULT_TRIAL_FIELDS_DAYS",
    "FAMILIES",
    "TRASH_RETENTION_DAYS",
    "GcPlan",
    "GcReport",
    "RetentionPolicy",
    "Weight",
    "apply_gc",
    "gc",
    "level_at",
    "mark_aborted",
    "plan_gc",
    "project_weight",
    "run_weight",
]
