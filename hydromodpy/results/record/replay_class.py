"""The class of a replay: whether it reproduced the sealed values, and by how much.

A replay plays a sealed run again and compares the numbers, never the files.
The class is computed before the seal of the replay is written, so the seal it
writes carries the verdict it earned. Three comparisons, one per source:

- a version 4 source compares the value digests of its seal to the digests the
  replay computed at its own seal, ``basis = "float64"``;
- a version 3 source has no value digests, so both directories are read from
  the disk, ``basis = "stored"``;
- a source whose values are gone, such as a published copy without fields or
  tables, compares nothing, ``basis = "none"``, and has no class.

``bit`` means every value key present on both sides hashes the same and no key
is present on one side only. ``deviation`` means one value moved, appeared or
left, and each moved key carries the size of the move. On the ``stored`` basis
the source keys are first renamed by the ``fields`` migration rows of the
register (the flat ``concentration`` of the 2.0.0 is the one species of 2.1),
and a key the 2.0.0 format cannot hold (``final_state/``) is listed in
``added`` without making the replay a deviation. Under ``--strict`` a
deviation is refused before the seal with :class:`ReplayDeviationError`, so the
attempt fails, keeps its fields and tables for reading, and writes no seal.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

from packaging.version import Version

from hydromodpy.core.exceptions import ResultsError
from hydromodpy.results.record.manifest import read_seal
from hydromodpy.results.record.values import stored_value_digests, value_deltas
from hydromodpy.results.storage.contract import (
    FINAL_STATE_DIRNAME,
    PUBLICATION_FILENAME,
    RUN_CONFIG_FILENAME,
)
from hydromodpy.results.validity_rules import run_quantities
from hydromodpy.schema.changes import REGISTER, Register, migrations_of
from hydromodpy.schema.lineage import ProducerSide, Replay, ReplayDifference
from hydromodpy.schema.seal import ValueDigests
from hydromodpy.schema.sources import declared_source_tokens

FORMAT_ADDITIONS: Final[tuple[str, ...]] = (f"{FINAL_STATE_DIRNAME}/",)
"""Key prefixes a version 3 seal cannot hold: a replay writing them is no deviation."""


class ReplayDeviationError(ResultsError):
    """A replay asked to be strict did not reproduce the sealed values."""


def classify_replay(
    source: str | Path,
    replay_dir: str | Path,
    digests: ValueDigests,
    *,
    strict: bool,
    producer: Mapping[str, ProducerSide] | None = None,
    register: Register = REGISTER,
) -> Replay:
    """Compare *replay_dir* to the run sealed in *source*, and return its class.

    *digests* is the value digests of the replay, computed by
    :func:`~hydromodpy.results.record.values.run_value_digests` at its seal. It
    is read for a version 4 source only; a version 3 source and its replay are
    read from the disk, because neither seal holds a value digest. *producer*
    is the provenance entries the replay found otherwise than its source.
    """
    source_dir, replay_root = Path(source), Path(replay_dir)
    seal = read_seal(source_dir)
    source_version = seal.identity.hydromodpy_version
    source_kind = "copy" if (source_dir / PUBLICATION_FILENAME).is_file() else "run"
    basis, sealed_digests, replay_digests = _basis(seal.values, source_dir, replay_root, digests)
    changes = _changes(seal, source_dir, register)
    if basis == "none":
        replay = Replay(
            of=seal.identity.sim_id,
            source=source_kind,
            source_version=source_version,
            basis="none",
            class_=None,
            changes=changes,
            strict=strict,
        )
    else:
        if basis == "stored":
            renamed = _renamed_fields(sealed_digests, replay_digests, register)
            sealed_digests = {renamed.get(key, key): value for key, value in sealed_digests.items()}
        common = sorted(set(sealed_digests) & set(replay_digests))
        moved = [key for key in common if sealed_digests[key] != replay_digests[key]]
        differs = {
            key: ReplayDifference(**measured)
            for key, measured in value_deltas(source_dir, replay_root, moved).items()
        }
        added = sorted(set(replay_digests) - set(sealed_digests))
        removed = sorted(set(sealed_digests) - set(replay_digests))
        counted = [
            key for key in added if basis != "stored" or not key.startswith(FORMAT_ADDITIONS)
        ]
        replay = Replay(
            of=seal.identity.sim_id,
            source=source_kind,
            source_version=source_version,
            basis=basis,
            class_="deviation" if differs or counted or removed else "bit",
            differs=differs,
            added=added,
            removed=removed,
            producer=dict(producer or {}),
            changes=changes,
            strict=strict,
        )
    if strict and replay.class_ != "bit":
        raise ReplayDeviationError(_refusal(replay))
    return replay


def _basis(
    sealed: ValueDigests | None,
    source_dir: Path,
    replay_dir: Path,
    digests: ValueDigests,
) -> tuple[str, dict[str, str], dict[str, str]]:
    """Return the basis and the two digest tables the comparison reads."""
    if sealed is not None and sealed.digests:
        return "float64", dict(sealed.digests), dict(digests.digests)
    source_stored = stored_value_digests(source_dir).digests
    replay_stored = stored_value_digests(replay_dir).digests
    if not source_stored or not replay_stored:
        return "none", {}, {}
    return "stored", dict(source_stored), dict(replay_stored)


def _renamed_fields(
    sealed: Mapping[str, str], replay: Mapping[str, str], register: Register
) -> dict[str, str]:
    """Return the source keys a ``fields`` migration row renames, old key to new key.

    A row ``old = "a"``, ``new = "a.{*}"`` turns the flat array ``fields/a`` of the
    source into the one array under ``fields/a/`` the replay writes. With no array
    there, or several, the key keeps its name and the comparison says so.
    """
    renamed: dict[str, str] = {}
    for row in migrations_of("fields", register):
        if not row.old or not row.new or not row.new.endswith(".{*}"):
            continue
        old_key = f"fields/{row.old.replace('.', '/')}"
        prefix = f"fields/{row.new.removesuffix('.{*}').replace('.', '/')}/"
        if old_key not in sealed:
            continue
        candidates = [key for key in replay if key.startswith(prefix)]
        if len(candidates) == 1:
            renamed[old_key] = candidates[0]
    return renamed


def _changes(seal: Any, source_dir: Path, register: Register) -> list[str]:
    """Return the register rows the source version crosses, by id, in register order."""
    config = source_dir / RUN_CONFIG_FILENAME
    text = config.read_text(encoding="utf-8") if config.is_file() else ""
    starts: tuple[str, ...] = ()
    if text:
        # The start tokens live with the label reader, which reads the run record.
        from hydromodpy.results.record.label import declared_start_tokens

        starts = declared_start_tokens(text)
    quantities = run_quantities(
        solver=seal.run.solver,
        mesh_engine=seal.geometry.mesh_engine,
        has_metrics=seal.score is not None and seal.score.value is not None,
        derive_rule_version=seal.derive_rule_version,
        sources=declared_source_tokens(text) if text else (),
        starts=starts,
    )
    if not quantities:
        return []
    version = Version(seal.identity.hydromodpy_version)
    rows = (*register.bugs, *register.defaults, *register.recipes)
    crossed = set(quantities)
    return [
        row.id for row in rows if Version(row.since) > version and crossed & set(row.quantities)
    ]


def _refusal(replay: Replay) -> str:
    """Return the sentence a strict replay raises, naming what moved."""
    parts = [f"{replay.of} was replayed and the values do not reproduce it"]
    if replay.differs:
        measures = "; ".join(
            f"{key} max |delta| {difference.max_abs!r}, relative L2 {difference.rel_l2!r} "
            f"({difference.precision})"
            for key, difference in sorted(replay.differs.items())
        )
        parts.append(f"values that moved: {measures}")
    if replay.added:
        parts.append(f"values only the replay writes: {', '.join(replay.added)}")
    if replay.removed:
        parts.append(f"values the seal holds and the replay does not: {', '.join(replay.removed)}")
    if replay.changes:
        parts.append(f"changes crossed: {', '.join(replay.changes)}")
    parts.append("run hmp replay without --strict to seal it as a deviation")
    return ". ".join(parts) + "."


__all__ = ["ReplayDeviationError", "classify_replay"]
