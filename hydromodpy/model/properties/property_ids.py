"""The one table of the ids of ``[flow.param.<id>]``.

Every reader of a hydraulic property goes through these ids: the solvers, the
calibration, the units of a field. A vertical conductivity is ``Kv`` everywhere. An
id that is not here is free: a plugin can read it, and no built-in solver does.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FlowPropertyId:
    """One hydraulic property: its id, its unit, the name it is written under."""

    id: str
    unit: str
    output: str
    label: str
    conductivity: bool = False


FLOW_PROPERTY_IDS: tuple[FlowPropertyId, ...] = (
    FlowPropertyId("K", "m/s", "hk", "Hydraulic conductivity", conductivity=True),
    FlowPropertyId("Kv", "m/s", "kv", "Vertical hydraulic conductivity", conductivity=True),
    FlowPropertyId("Sy", "-", "sy", "Specific yield"),
    FlowPropertyId("Ss", "1/m", "ss", "Specific storage"),
    FlowPropertyId(
        "K22",
        "m/s",
        "k22",
        "Hydraulic conductivity along the second tensor axis",
        conductivity=True,
    ),
    FlowPropertyId(
        "angle1",
        "deg",
        "angle1",
        "Turn of the first K axis from east towards north (degrees)",
    ),
    FlowPropertyId(
        "angle2",
        "deg",
        "angle2",
        "Rise of the first K axis above the horizontal (degrees)",
    ),
    FlowPropertyId(
        "angle3",
        "deg",
        "angle3",
        "Rotation of the K tensor about its first axis (degrees)",
    ),
)
"""The properties a built-in solver reads, in the order they are mapped."""

OLD_PROPERTY_IDS: dict[str, str] = {
    "k": "K",
    "kv": "Kv",
    "K33": "Kv",
    "k33": "Kv",
    "SY": "Sy",
    "sy": "Sy",
    "S": "Sy",
    "s": "Sy",
    "SS": "Ss",
    "ss": "Ss",
    "k22": "K22",
}
"""Other spellings a solver read as one of the ids above. The migration rewrites them."""

NEVER_READ_IDS: dict[str, str] = {"Kz": "Kv", "Kx": "K", "Ky": "K22"}
"""Ids that no solver ever read, with the id that does the job. A file is refused.

Rewriting one would start to read a number no run has used. So it stays a refusal, and
the person who wrote it decides.
"""

CONDUCTIVITY_IDS: tuple[str, ...] = tuple(p.id for p in FLOW_PROPERTY_IDS if p.conductivity)


def default_unit_of(param_id: str) -> str:
    """Return the unit a number takes under *param_id*, ``-`` for a free id."""
    for prop in FLOW_PROPERTY_IDS:
        if prop.id == param_id:
            return prop.unit
    return "-"


def refusal_of_a_retired_id(param_id: str) -> str | None:
    """Return why ``flow.param.<param_id>`` is refused, or None for an id that is allowed."""
    if param_id in OLD_PROPERTY_IDS:
        return (
            f"flow.param.{param_id} is now flow.param.{OLD_PROPERTY_IDS[param_id]}. "
            "`hmp doctor --fix-config <file>` rewrites the file."
        )
    if param_id in NEVER_READ_IDS:
        return (
            f"flow.param.{param_id} has never been read by a solver, so the runs of this file "
            f"did not use it. Write flow.param.{NEVER_READ_IDS[param_id]} to set it, or remove "
            "the table."
        )
    return None


__all__ = [
    "CONDUCTIVITY_IDS",
    "FLOW_PROPERTY_IDS",
    "NEVER_READ_IDS",
    "OLD_PROPERTY_IDS",
    "FlowPropertyId",
    "default_unit_of",
    "refusal_of_a_retired_id",
]
