"""The ``lineage`` block of a seal: where a run comes from, by ids.

Why
---
Names move: a rename, a restore, a tar extracted elsewhere. Ids do not. The
link from a promoted run to its session, from a rerun to its parent, from a
versioned run to the surcharge that made it, is written by id. A ``*_hint``
is a directory name as it was at seal time, for a human reading the file; a
tool never requires it.

Format
------
``parent_sim_id`` is the run this one derives from (a rerun, a restart).
``session_id``, ``phase`` and ``trial`` name the calibration trial a promoted
run is. ``kind`` says which relation holds. ``overrides`` is what ``--set``,
``--overlay`` or a keyword of ``Project.simulate`` changed against the file the
run was launched from, as dotted paths to values, so a ``.v2`` says what differs
from the ``.v1``. ``drift`` is what a rerun found moved against the configuration
its parent sealed: a default that changed since, with both values, by dotted path.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import ConfigDict, Field, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.stored import Vocabulary

LineageKind = Annotated[str, Vocabulary("rerun", "promoted", "trial", "version", "replay")]
"""The relation a run has with what it comes from."""

ReplaySource = Annotated[str, Vocabulary("run", "copy")]
"""What a replay read: a run directory, or a published copy of one."""

ReplayBasis = Annotated[str, Vocabulary("float64", "stored", "none")]
"""The values a replay compared: the source seal, the stored values of both, or nothing."""

ReplayClass = Annotated[str, Vocabulary("bit", "deviation")]
"""What a replay proved: the same values, or a measured deviation."""

ReplayPrecision = Annotated[str, Vocabulary("exact", "compact")]
"""The precision the compared values were read in."""

ReplayGap = Annotated[str, Vocabulary("shape", "nan_pattern", "zero_norm")]
"""Why a measure of a key that differs is null: two shapes, two NaN masks, a zero norm."""


class ReplayDifference(HydroModelBase):
    """How one key of the values differs between a source and its replay."""

    max_abs: float | None = Field(default=None, description="Largest absolute difference")
    rel_l2: float | None = Field(
        default=None, description="L2 norm of the difference over the norm of the source field"
    )
    precision: ReplayPrecision | None = Field(
        default=None, description="Precision of the values the two measures were read in"
    )
    reason: ReplayGap | None = Field(
        default=None, description="Why a measure is null when both sides hold the key"
    )


class ProducerSide(HydroModelBase):
    """One writer of a value: the source seal, or the replay as it ran."""

    sealed: Any = Field(default=None, description="Value in the source provenance")
    found: Any = Field(default=None, description="Value in the replay provenance")


class Replay(HydroModelBase):
    """What a replay compared to its source, and what it found.

    ``differs`` names every value key present on both sides whose digest moved,
    with the size of the move. ``added`` and ``removed`` name the keys present
    on one side only. ``producer`` names the provenance entries that differ,
    and ``changes`` the register rows the version range crosses.
    """

    model_config = ConfigDict(populate_by_name=True)

    of: str = Field(description="sim_id of the run the replay read")
    source: ReplaySource = Field(description="run for a sealed run, copy for a published copy")
    source_version: str = Field(description="hydromodpy_version of the source")
    basis: ReplayBasis = Field(description="Values the comparison read")
    class_: ReplayClass | None = Field(
        default=None, alias="class", description="bit, deviation, or none without a basis"
    )
    differs: dict[str, ReplayDifference] = Field(
        default_factory=dict, description="Keys present on both sides whose digest moved"
    )
    added: list[str] = Field(default_factory=list, description="Keys only the replay holds")
    removed: list[str] = Field(default_factory=list, description="Keys only the source holds")
    producer: dict[str, ProducerSide] = Field(
        default_factory=dict, description="Provenance entries that differ"
    )
    changes: list[str] = Field(
        default_factory=list, description="Register rows the version range crosses"
    )
    strict: bool = Field(default=False, description="Whether the replay was asked to refuse")

    @model_validator(mode="after")
    def _class_follows_basis(self) -> Replay:
        if self.basis == "none" and self.class_ is not None:
            raise ValueError(f"a replay with basis 'none' has no class, not {self.class_!r}")
        if self.basis != "none" and self.class_ is None:
            raise ValueError(f"a replay with basis {self.basis!r} states a class")
        return self


class Lineage(HydroModelBase):
    """Links of a run to its parent run, its session and its surcharges."""

    parent_sim_id: str | None = Field(default=None, description="Run this one derives from")
    session_id: str | None = Field(default=None, description="Session a promoted run comes from")
    phase: str | None = Field(default=None, description="Phase of that session")
    trial: int | None = Field(default=None, ge=1, description="Trial of that session")
    kind: LineageKind | None = Field(default=None, description="Relation to the parent")
    overrides: dict[str, Any] = Field(
        default_factory=dict,
        description="Dotted paths changed by --set, --overlay or a keyword of simulate",
    )
    drift: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description=(
            "Keys whose value differs from config.resolved.toml of the parent, "
            "by dotted path: {sealed, effective}, a side the file does not write left out. "
            "The key new_at_default holds, by dotted path, the keys the parent did not "
            "seal and the rerun holds at their default."
        ),
    )
    parent_hint: str | None = Field(
        default=None, description="Relative directory of the parent at seal time, for a reader"
    )
    replay: Replay | None = Field(
        default=None, description="What a replay compared and found; none for any other run"
    )


__all__ = [
    "Lineage",
    "LineageKind",
    "ProducerSide",
    "Replay",
    "ReplayBasis",
    "ReplayClass",
    "ReplayDifference",
    "ReplayGap",
    "ReplayPrecision",
    "ReplaySource",
]
