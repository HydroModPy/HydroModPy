"""MF6 MVR (Water Mover) records, package-agnostic.

The MVR package routes water from a *provider* package feature to a *receiver*
package feature, controlled by a transfer rule. This module is general: it knows
nothing about LAK, SFR or MAW; it only formats and validates the transfer records
shared by two packages of the same GWF model. The LAK adapter that compiles lake
outlets into :class:`MoverRecord` instances lives in ``builders/lake_outflow.py``.

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

import flopy

from hydromodpy.solver.modflow6.builders.solver_options import output_control_records

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


# The receivers whose size the build knows: package name, model attribute, and
# the FloPy variable that counts its features.
_RECEIVER_SIZES = {"SFR": ("sfr", "nreaches"), "LAK": ("lak", "nlakes")}


def refuse_movers_without_receiver(model, rows: Sequence[Sequence[Any]]) -> None:
    """Refuse a record whose SFR reach or LAK lake was not built.

    A ``mover.reach`` or ``mover.lake`` past the end of its package, or a mover
    to SFR when no SFR network is active, is otherwise met by MODFLOW 6 with a
    message that names no config key, or moves the water to the wrong feature.
    """
    for row in rows:
        name, feature = str(row[2]), int(row[3])
        if name not in _RECEIVER_SIZES:
            continue
        attribute, counter = _RECEIVER_SIZES[name]
        package = getattr(model, attribute, None)
        if package is None:
            raise ValueError(
                f"MVR record {row[0]} {int(row[1]) + 1} -> {name} {feature + 1}: the model "
                f"has no {name} package. Check the outlet mover of the lake and that the "
                f"{name} boundary is active."
            )
        size = int(getattr(package, counter).get_data())
        if not 0 <= feature < size:
            raise ValueError(
                f"MVR record {row[0]} {int(row[1]) + 1} -> {name} feature {feature + 1} "
                f"(1-based) is outside the {size} feature(s) of the {name} package."
            )


def build_mover_and_output(model, all_mover_rows):
    """MVR, built last, then OC."""
    # MVR last: it routes provider features to receiver features by package name,
    # so every package it references must already exist. The packages list is
    # derived from the record rows so LAK-only, SFR-only and mixed models all
    # produce a consistent block.
    if all_mover_rows:
        refuse_movers_without_receiver(model, all_mover_rows)
        mvr_packages = sorted(
            {(str(row[0]),) for row in all_mover_rows} | {(str(row[2]),) for row in all_mover_rows}
        )
        model.mvr = flopy.mf6.ModflowGwfmvr(
            model.gwf,
            pname="MVR",
            maxmvr=len(all_mover_rows),
            maxpackages=mover_package_count(all_mover_rows),
            packages=mvr_packages,
            perioddata={0: all_mover_rows},
        )

    model.oc = flopy.mf6.ModflowGwfoc(
        model.gwf,
        head_filerecord=f"{model.model_output_name}.hds",
        budget_filerecord=f"{model.model_output_name}.cbc",
        **output_control_records(print_head=model.modflow_config.runtime.print_head),
    )
