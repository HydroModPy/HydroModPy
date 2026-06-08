"""MF6 MVR (Water Mover) records for LAK -> LAK cascades.

The MVR package routes water from a *provider* package outlet to a *receiver*
package, controlled by a transfer rule. In v1 the only providers and receivers
are LAK lakes, so MVR carries a *controlled* transfer between two lakes of the
same package (préretenue -> retenue with a fraction, a cap or a threshold rather
than the unconditional direct ``lakeout`` routing).

A LAK provider is identified by its **outlet number** (0-based ``outletno``) and a
LAK receiver by its **lake number** (0-based ``ifno``). A record follows the FloPy
single-model layout ``[pname1, id1, pname2, id2, mvrtype, value]`` (model names are
omitted because provider and receiver share the one GWF model). ``ModflowGwfmvr``
must be instantiated *last* in the build, after the LAK package it references, and
LAK must advertise ``mover=True`` for MF6 to accept the record.

Functions are pure and keyword-only, mirroring ``builders/wells.py``; they raise
plain ``ValueError`` naming the offending TOML path exactly as ``wells.py`` does.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from hydromodpy.core.logging import get_logger

logger = get_logger(__name__)

# The single LAK package name used across the GWF model (see build.py: pname="LAK").
_LAK_PACKAGE_NAME = "LAK"

# Transfer rules MF6 accepts on an MVR record (FloPy passes the string straight
# through). FACTOR = a fraction of the provider flow; UPTO = capped at value;
# EXCESS = only the part above value; THRESHOLD = all-or-nothing above value.
_MVR_TYPES = ("FACTOR", "UPTO", "EXCESS", "THRESHOLD")


def build_mover_records(
    model,
    *,
    lakes: Mapping[str, dict[str, Any]],
) -> list[list[Any]]:
    """Build the MVR PERIOD records for every outlet carrying a ``mover`` spec.

    Rows follow the FloPy single-model layout
    ``[pname1, id1, pname2, id2, mvrtype, value]`` where ``pname1``/``pname2`` are
    the LAK package name, ``id1`` is the provider outlet number (0-based, assigned
    in the same order as :func:`build_lake_outlets`) and ``id2`` is the receiver
    lake number (0-based ``ifno``).

    Only outlets with a ``mover`` spec produce a record; an outlet routed directly
    via ``lakeout`` (the conservative LAK -> LAK path, no MVR) is skipped. The
    receiving lake is the ``mover.lake`` 1-based number translated to its 0-based
    packagedata index. An empty result means no controlled transfer is requested.
    """
    lake_count = len(lakes)
    records: list[list[Any]] = []
    outletno = 0
    for lake_id, definition in lakes.items():
        outlets = definition.get("outlets") or []
        for outlet in outlets:
            mover = _outlet_attr(outlet, "mover")
            if mover is None:
                outletno += 1
                continue
            receiver_index = _resolve_receiver_lake(lake_id, mover, lake_count)
            mvrtype = _resolve_mvrtype(lake_id, mover)
            raw_value = _outlet_attr(mover, "value")
            value = _scalar(raw_value) if raw_value is not None else 1.0
            if value < 0.0:
                raise ValueError(
                    f"flow.sinks_sources.lakes.{lake_id} outlet mover value must be >= 0, "
                    f"got {value}."
                )
            records.append(
                [
                    _LAK_PACKAGE_NAME,
                    int(outletno),
                    _LAK_PACKAGE_NAME,
                    int(receiver_index),
                    mvrtype,
                    value,
                ]
            )
            outletno += 1
    return records


def _resolve_receiver_lake(lake_id: str, mover: object, lake_count: int) -> int:
    """Translate a ``mover.lake`` (1-based) to its 0-based receiver lake index."""
    raw = _outlet_attr(mover, "lake")
    if raw is None:
        raise ValueError(
            f"flow.sinks_sources.lakes.{lake_id} outlet mover requires a 'lake' "
            "(1-based downstream receiving lake)."
        )
    value = int(_scalar(raw))
    if value < 1:
        raise ValueError(
            f"flow.sinks_sources.lakes.{lake_id} outlet mover lake must be >= 1 "
            f"(1-based downstream lake); got {value}."
        )
    if value > lake_count:
        raise ValueError(
            f"flow.sinks_sources.lakes.{lake_id} outlet mover lake={value} has no "
            f"matching downstream lake ({lake_count} lakes declared)."
        )
    return value - 1


def _resolve_mvrtype(lake_id: str, mover: object) -> str:
    raw = _outlet_attr(mover, "mvrtype")
    mvrtype = str(raw).strip().upper() if raw is not None else "FACTOR"
    if mvrtype not in _MVR_TYPES:
        raise ValueError(
            f"flow.sinks_sources.lakes.{lake_id} outlet mover mvrtype must be one of "
            f"{', '.join(_MVR_TYPES)}; got {raw!r}."
        )
    return mvrtype


def _outlet_attr(payload: object, name: str) -> object:
    """Read ``name`` from a mapping payload or a pydantic config object."""
    if isinstance(payload, Mapping):
        return payload.get(name)
    return getattr(payload, name, None)


def _scalar(value: object) -> float:
    """Coerce a plain number or a pint Quantity to a float magnitude."""
    magnitude = getattr(value, "magnitude", value)
    return float(magnitude)  # type: ignore[arg-type]


def mover_package_count(records: list[list[Any]]) -> int:
    """Return the number of distinct provider/receiver packages in ``records``.

    MVR ``maxpackages`` counts the unique package names referenced as provider or
    receiver. For LAK -> LAK cascades that is exactly one (the single LAK package),
    but we compute it from the records so it stays correct if SFR joins in v2.
    """
    names: set[str] = set()
    for record in records:
        names.add(str(record[0]))  # provider package name (pname1)
        names.add(str(record[2]))  # receiver package name (pname2)
    return len(names)


__all__ = [
    "build_mover_records",
    "mover_package_count",
]
