"""The identity block a derived file of a run carries, and the label of the day.

Why
---
A figure, an export or a published copy is written from a run directory. Each
one carries the :class:`~hydromodpy.results.identity.Identity` block of that
run. A sealed run gives the block of its manifest, labeled today by
:mod:`hydromodpy.results.validity_rules`. A run still being computed has no
seal yet: its block is built from the facts the run recorded so far
(:func:`~hydromodpy.results.storage.run_facts.identity_of`), else from
``outcome.json``, which the run writes at the creation of its directory. It
carries no label.

This module is the one place that answers "who is this run directory" for a
derived file. It reads the directory alone: no index, no workspace.
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from datetime import UTC, date, datetime
from pathlib import Path

from hydromodpy.core.version import __version__ as HYDROMODPY_VERSION
from hydromodpy.results.identity import Identity
from hydromodpy.results.manifest import Manifest, is_sealed, read_seal
from hydromodpy.results.outcome import read_outcome
from hydromodpy.results.record import RunRecord
from hydromodpy.results.storage.contract import RUN_CONFIG_FILENAME
from hydromodpy.results.storage.run_facts import identity_of, read_facts
from hydromodpy.results.validity_rules import (
    CYCLIC_LAKE_START,
    RESTART_START,
    LabelResult,
    label_for,
    run_quantities,
)
from hydromodpy.schema.sources import declared_source_tokens


def read_sealed_manifest(run_dir: str | Path) -> Manifest | None:
    """Return the manifest of a sealed run directory, or ``None`` when it has none."""
    directory = Path(run_dir)
    if not is_sealed(directory):
        return None
    return read_seal(directory)


def declared_start_tokens(config_text: str) -> tuple[str, ...]:
    """Return the ``start@<kind>`` tokens of how a sealed ``config.toml`` starts its heads.

    ``start@restart_from`` marks a run that starts from an earlier one by
    ``[flow] restart_from``. ``start@spinup_cyclic_lake`` marks a cyclic spin-up
    (``[flow.ic.h] kind = "spinup_cyclic"``) beside a declared lake
    (``[flow.sinks_sources.lakes.<name>]``). The text is read as TOML alone,
    whatever grammar wrote it.
    """
    flow = tomllib.loads(config_text).get("flow")
    if not isinstance(flow, Mapping):
        return ()
    tokens = []
    if flow.get("restart_from"):
        tokens.append(RESTART_START)
    ic = flow.get("ic")
    head = ic.get("h") if isinstance(ic, Mapping) else None
    sinks = flow.get("sinks_sources")
    lakes = sinks.get("lakes") if isinstance(sinks, Mapping) else None
    has_lake = isinstance(lakes, Mapping) and any(isinstance(v, Mapping) for v in lakes.values())
    if isinstance(head, Mapping) and head.get("kind") == "spinup_cyclic" and has_lake:
        tokens.append(CYCLIC_LAKE_START)
    return tuple(tokens)


def label_of(seal: Manifest | RunRecord, run_dir: str | Path) -> LabelResult:
    """Return the label of a sealed run today, under the shipped rules and register.

    *run_dir* is the folder of the run. A run has metrics for the register when its
    headline score holds a value, and a source for each one its sealed
    ``config.toml`` declares, and a start token for how its heads start. A run
    without that file declares none.
    """
    score = seal.score
    config = Path(run_dir) / RUN_CONFIG_FILENAME
    text = config.read_text(encoding="utf-8") if config.is_file() else ""
    sources = declared_source_tokens(text) if text else ()
    starts = declared_start_tokens(text) if text else ()
    return label_for(
        seal.checks,
        hydromodpy_version=seal.identity.hydromodpy_version,
        quantities=run_quantities(
            solver=seal.run.solver,
            mesh_engine=seal.geometry.mesh_engine,
            has_metrics=score is not None and score.value is not None,
            derive_rule_version=seal.derive_rule_version,
            sources=sources,
            starts=starts,
        ),
    )


def labelled_identity(
    manifest: Manifest, run_dir: str | Path, *, today: date | None = None
) -> Identity:
    """Return the identity of the sealed run at *run_dir*, carrying its label of *today*."""
    result = label_of(manifest, run_dir)
    return manifest.identity.labelled(
        result.label,
        label_date=today or datetime.now(UTC).date(),
        rule_version=result.rule_version,
    )


def identity_of_run_dir(run_dir: str | Path, *, today: date | None = None) -> Identity | None:
    """Return the identity block a derived file of *run_dir* carries.

    A sealed run gives its manifest block, labeled *today*. An unsealed run
    gives the block of its facts (site, case, config hash, period), without a
    label; a directory whose run recorded no facts yet gives a block built
    from ``outcome.json``, without a period, which the caller adds when it
    knows it. ``None`` when the directory carries neither, or when its
    outcome does not name the run yet.
    """
    directory = Path(run_dir)
    manifest = read_sealed_manifest(directory)
    if manifest is not None:
        return labelled_identity(manifest, directory, today=today)
    facts = read_facts(directory)
    if facts is not None:
        return identity_of(facts)
    outcome = read_outcome(directory)
    if outcome is None or outcome.sim_id is None:
        return None
    return Identity(
        site=outcome.site,
        case_id=outcome.case_id,
        sim_id=outcome.sim_id,
        attempt_id=outcome.attempt_id,
        hydromodpy_version=HYDROMODPY_VERSION,
    )


__all__ = [
    "declared_start_tokens",
    "identity_of_run_dir",
    "label_of",
    "labelled_identity",
    "read_sealed_manifest",
]
