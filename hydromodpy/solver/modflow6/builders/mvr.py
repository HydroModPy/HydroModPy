"""MF6 MVR (Water Mover) records, package-agnostic.

The MVR package routes water from a *provider* package feature to a *receiver*
package feature, controlled by a transfer rule. This module is general: it knows
nothing about LAK, SFR or MAW; it only formats and validates the transfer records
shared by two packages of the same GWF model. The LAK adapter that compiles lake
outlets into :class:`MoverRecord` instances lives in ``builders/lake.py``.

A record follows the FloPy single-model layout
``[pname1, id1, pname2, id2, mvrtype, value]`` (model names are omitted because
provider and receiver share the one GWF model). Feature ids are 0-based.
``ModflowGwfmvr`` must be instantiated *last* in the build, after the packages it
references, and each provider package must advertise ``mover=True`` for MF6 to
accept the records.

Functions are pure and keyword-only, mirroring ``builders/wells.py``; they raise
plain ``ValueError``.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from typing import Any

# Transfer rules MF6 accepts on an MVR record (FloPy passes the string straight
# through). FACTOR = a fraction of the provider flow; UPTO = capped at value;
# EXCESS = only the part above value; THRESHOLD = all-or-nothing above value.
MVR_TYPES = ("FACTOR", "UPTO", "EXCESS", "THRESHOLD")


@dataclasses.dataclass(frozen=True)
class MoverRecord:
    """One MVR transfer between two packages of the same GWF model.

    ``provider`` / ``receiver`` are package names and ``provider_id`` /
    ``receiver_id`` the 0-based feature ids within them. ``mvrtype`` is one of
    :data:`MVR_TYPES` and ``value`` its parameter (a fraction, a cap or a
    threshold depending on the rule).
    """

    provider: str
    provider_id: int
    receiver: str
    receiver_id: int
    mvrtype: str = "FACTOR"
    value: float = 1.0


def build_mvr_period_records(moves: Sequence[MoverRecord]) -> list[list[Any]]:
    """Format MVR transfers into FloPy PERIOD records.

    Each move becomes a row ``[pname1, id1, pname2, id2, mvrtype, value]``.
    ``mvrtype`` is uppercased and stripped, then validated against
    :data:`MVR_TYPES`. ``value`` must be non-negative.
    """
    records: list[list[Any]] = []
    for move in moves:
        mvrtype = str(move.mvrtype).strip().upper()
        if mvrtype not in MVR_TYPES:
            raise ValueError(
                f"MVR record {move.provider} -> {move.receiver} mvrtype must be one of "
                f"{', '.join(MVR_TYPES)}; got {move.mvrtype!r}."
            )
        value = float(move.value)
        if value < 0.0:
            raise ValueError(
                f"MVR record {move.provider} -> {move.receiver} value must be >= 0, got {value}."
            )
        records.append(
            [
                str(move.provider),
                int(move.provider_id),
                str(move.receiver),
                int(move.receiver_id),
                mvrtype,
                value,
            ]
        )
    return records


def mover_package_count(records: list[list[Any]]) -> int:
    """Return the number of distinct provider/receiver packages in ``records``.

    MVR ``maxpackages`` counts the unique package names referenced as provider or
    receiver. For a LAK -> LAK cascade that is exactly one (the single LAK
    package), but we compute it from the records so it stays correct when SFR or
    MAW join in.
    """
    names: set[str] = set()
    for record in records:
        names.add(str(record[0]))  # provider package name (pname1)
        names.add(str(record[2]))  # receiver package name (pname2)
    return len(names)


__all__ = [
    "MVR_TYPES",
    "MoverRecord",
    "build_mvr_period_records",
    "mover_package_count",
]
