"""The identity block a derived file of a run carries, and the label of the day.

Why
---
A figure, an export or a published copy is written from a run directory. Each
one carries the :class:`~hydromodpy.results.identity.Identity` block of that
run. A sealed run gives the block of its manifest, labelled today by
:mod:`hydromodpy.results.validity_rules`. A run still being computed has no
seal yet: its block is built from the facts the run recorded so far
(:func:`~hydromodpy.results.storage.run_facts.identity_of`), else from
``outcome.json``, which the run writes at the creation of its directory. It
carries no label.

This module is the one place that answers "who is this run directory" for a
derived file. It reads the directory alone: no index, no workspace.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from hydromodpy.core.version import __version__ as HYDROMODPY_VERSION
from hydromodpy.results.identity import Identity
from hydromodpy.results.manifest import Manifest, is_sealed, read_seal
from hydromodpy.results.outcome import read_outcome
from hydromodpy.results.record import RunRecord
from hydromodpy.results.storage.run_facts import identity_of, read_facts
from hydromodpy.results.validity_rules import LabelResult, label_for, run_quantities


def read_sealed_manifest(run_dir: str | Path) -> Manifest | None:
    """Return the manifest of a sealed run directory, or ``None`` when it has none."""
    directory = Path(run_dir)
    if not is_sealed(directory):
        return None
    return read_seal(directory)


def label_of(seal: Manifest | RunRecord) -> LabelResult:
    """Return the label of a sealed run today, under the shipped rules and register.

    A run has metrics for the register when its headline score holds a value.
    """
    score = seal.score
    return label_for(
        seal.checks,
        hydromodpy_version=seal.identity.hydromodpy_version,
        quantities=run_quantities(
            solver=seal.run.solver,
            mesh_engine=seal.geometry.mesh_engine,
            has_metrics=score is not None and score.value is not None,
            derive_rule_version=seal.derive_rule_version,
        ),
    )


def labelled_identity(manifest: Manifest, *, today: date | None = None) -> Identity:
    """Return the identity of a sealed run, carrying its label of *today*."""
    result = label_of(manifest)
    return manifest.identity.labelled(
        result.label,
        label_date=today or datetime.now(UTC).date(),
        rule_version=result.rule_version,
    )


def identity_of_run_dir(run_dir: str | Path, *, today: date | None = None) -> Identity | None:
    """Return the identity block a derived file of *run_dir* carries.

    A sealed run gives its manifest block, labelled *today*. An unsealed run
    gives the block of its facts (site, case, config hash, period), without a
    label; a directory whose run recorded no facts yet gives a block built
    from ``outcome.json``, without a period, which the caller adds when it
    knows it. ``None`` when the directory carries neither, or when its
    outcome does not name the run yet.
    """
    directory = Path(run_dir)
    manifest = read_sealed_manifest(directory)
    if manifest is not None:
        return labelled_identity(manifest, today=today)
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


__all__ = ["identity_of_run_dir", "label_of", "labelled_identity", "read_sealed_manifest"]
