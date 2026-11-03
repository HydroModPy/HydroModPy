"""Writing a plan: ``plan/<hash>/`` from a draft, once, never over a running case.

A :class:`~hydromodpy.config.sites.expansion.PlanDraft` without errors
becomes ``plan/<hash>/{plan.json, sites.parquet, cases.parquet, <case>.toml}``
through :func:`hydromodpy.results.plan_store.write_plan`, and ``plan/current``
points at it. The hash is the fingerprint of the cases: the same project,
tables and recipes give the same hash and the write is a no-op. The plan
holds nothing that the disk changes afterwards: which cases are sealed is
read from ``runs/`` at ``--dry-run``, never written in ``plan.json``, so a
plan written again after a run finished is still the same plan. A case of
the current plan that is still running refuses a new plan unless the caller
forces it: an array job in a queue reads the plan it was given.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa

from hydromodpy.config.sites.expansion import DraftCase, PlanDraft
from hydromodpy.config.sites.issues import PlanError
from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.state.paths import PLAN_DIRNAME, runs_dir_for, sessions_dir_for
from hydromodpy.core.toml_io.overrides import env_set_names
from hydromodpy.core.version import __version__
from hydromodpy.results.outcome import effective_status
from hydromodpy.results.plan_store import (
    CASE_TOML_SUFFIX,
    Plan,
    PlanCase,
    current_plan_hash,
    plan_path,
    read_plan,
    write_plan,
)
from hydromodpy.results.storage.contract import PLAN_FILENAME
from hydromodpy.results.storage.json_io import readable

PLAN_HASH_LENGTH = 16
"""Hexadecimal characters of a plan hash."""


class RunningCaseError(ConfigError):
    """A case of the current plan is running; a new plan would change its ground."""


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def plan_hash(cases: Sequence[DraftCase], inputs: Mapping[str, str]) -> str:
    """Return the fingerprint of a plan: its cases and the files it was made from."""
    lines = sorted(
        f"{case.case_id}\t{case.config_hash}\t{_sha256_text(case.toml())}" for case in cases
    )
    lines.extend(f"{name}\t{digest}" for name, digest in sorted(inputs.items()))
    return _sha256_text("\n".join(lines))[:PLAN_HASH_LENGTH]


def fingerprints(draft: PlanDraft) -> dict[str, str]:
    """Return the digest of every file the draft was made from, by relative path."""
    out: dict[str, str] = {}
    for path in draft.inputs:
        try:
            key = path.relative_to(draft.project_root).as_posix()
        except ValueError:
            key = str(path)
        out[key] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def sites_table(draft: PlanDraft) -> pa.Table:
    """Return the resolved site table of a draft: the site name and the row cells."""
    rows = [
        {"site": site.name, **{k: _cell(v) for k, v in site.row.cells.items() if k != "site"}}
        for site in draft.sites
    ]
    if not rows:
        return pa.table({"site": pa.array([], pa.string())})
    return pa.Table.from_pylist(rows)


def _cell(value: object) -> object:
    if isinstance(value, (list, tuple)):
        return ";".join(str(item) for item in value)
    return value


def build_plan(draft: PlanDraft) -> tuple[Plan, pa.Table, list[PlanCase], dict[str, str]]:
    """Return what :func:`hydromodpy.results.plan_store.write_plan` takes, from a draft."""
    if draft.errors:
        raise PlanError(draft.errors)
    cases = [
        PlanCase(
            case_id=case.case_id,
            site=case.site,
            recipe=case.recipe,
            config_hash=case.config_hash or "",
            config_path=f"{case.case_id}{CASE_TOML_SUFFIX}",
        )
        for case in draft.cases
    ]
    run = draft.sites_config.run
    digests = fingerprints(draft)
    hashed = plan_hash(draft.cases, digests)
    existing = plan_path(draft.project_root, hashed)
    # The same plan written again is the same plan: it keeps its instant.
    previous = readable(read_plan, draft.project_root, hashed) if existing.is_dir() else None
    created_at = previous.plan.created_at if previous is not None else datetime.now(UTC)
    plan = Plan(
        plan_hash=hashed,
        hydromodpy_version=__version__,
        created_at=created_at,
        fingerprints=digests,
        n_cases=len(cases),
        budget={
            "parallel": run.parallel,
            "threads_per_case": run.threads_per_case,
            "solves": sum(case.solves for case in draft.cases),
            "kept_solves": sum(case.kept_solves for case in draft.cases),
        },
    )
    tomls = {case.case_id: case.toml() for case in draft.cases}
    return plan, sites_table(draft), cases, tomls


def running_cases(project_root: Path, case_ids: Iterable[str]) -> list[str]:
    """Return the cases whose run directory, or calibration session, says ``running``.

    A calibration case holds no run directory before its promotion: its
    session counts while its descriptor says ``running`` and its outcome is
    alive, the rule of a run (a dead or silent worker reads ``stale``).
    """
    from hydromodpy.results.catalog.registration import split_stem_version
    from hydromodpy.results.session.descriptor import read_session, session_descriptor_path

    wanted = set(case_ids)
    running: list[str] = []
    for tree in (runs_dir_for(project_root), sessions_dir_for(project_root)):
        if not tree.is_dir():
            continue
        for entry in sorted(tree.iterdir()):
            stem, _ = split_stem_version(entry.name)
            if stem not in wanted or not entry.is_dir():
                continue
            if session_descriptor_path(entry).is_file():
                descriptor = readable(read_session, entry)
                if descriptor is None or descriptor.status != "running":
                    continue
            if effective_status(entry) == "running":
                running.append(f"{tree.name}/{entry.name}")
    return running


def is_plan_case(config_path: str | Path) -> bool:
    """Whether *config_path* is a case of a plan: ``plan/<hash>/<case>.toml``."""
    path = Path(config_path).resolve()
    folder = path.parent
    return (
        folder.parent.name == PLAN_DIRNAME
        and (folder / PLAN_FILENAME).is_file()
        and path.suffix == CASE_TOML_SUFFIX
    )


def refuse_env_overrides(env: Mapping[str, str], config_path: str | Path) -> None:
    """Refuse ``HMP_SET_*`` for a case of a plan: the plan rendered the overrides.

    The hash of a case is the hash of the plan; an override applied by the
    worker would make the run another computation than the one planned.
    """
    names = env_set_names(env)
    if names and is_plan_case(config_path):
        raise ConfigError(
            f"{', '.join(names)} set while running a case of a plan; the plan renders "
            "HMP_SET_* into each case. Unset the variable(s), or plan again with them set."
        )


def write_plan_draft(project_root: str | Path, draft: PlanDraft, *, force: bool = False) -> Path:
    """Write ``plan/<hash>/`` from *draft* and return the directory.

    A draft with errors raises :class:`~hydromodpy.config.sites.issues.PlanError`.
    A case of the current plan, or of the draft, still running raises
    :class:`RunningCaseError` unless *force* is true.
    """
    root = Path(project_root).resolve()
    plan, sites, cases, tomls = build_plan(draft)
    if not force:
        ids = {case.case_id for case in cases}
        current = readable(read_plan, root) if current_plan_hash(root) is not None else None
        if current is not None:
            ids |= {case.case_id for case in current.cases}
        running = running_cases(root, ids)
        if running:
            raise RunningCaseError(
                f"case(s) running: {', '.join(running)}; a plan is not rewritten under a "
                "running case. Wait, or pass --force."
            )
    return write_plan(root, plan, sites, cases, tomls)


__all__ = [
    "PLAN_HASH_LENGTH",
    "RunningCaseError",
    "build_plan",
    "fingerprints",
    "is_plan_case",
    "plan_hash",
    "refuse_env_overrides",
    "running_cases",
    "sites_table",
    "write_plan_draft",
]
