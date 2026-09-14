"""What this project exposes to a calibration.

A parameter is declared by a dotted path into the configuration, which means
writing one required knowing the Pydantic tree by heart. The question a
hydrogeologist asks runs the other way: what does THIS model carry that a search
could move, what is it worth now, and in what unit.

The catalogue answers from the resolved configuration rather than from a
hand-written inventory. A list typed by hand is an assertion about the code that
nothing keeps true; walking the configuration that the run itself validated
cannot drift from it, and it names the boundaries and parameters this project
actually declares instead of everything the schema could hold.

What is left out is deliberate. A boolean is a switch, not a value to search
between two bounds. An index, a count and an identifier are not physical
quantities. A field the user profile does not show is a knob of the numerical
scheme, and searching over a substep count optimises the solver rather than the
model. The mesh is refused by :mod:`hydromodpy.calibration.optim.parameters` for
its own reasons and is not offered here either.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from numbers import Real
from typing import Any

from pydantic import BaseModel

from hydromodpy.core.config_kit.introspect import extract_profile
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.spatial.field.core.physical_bounds import PHYSICAL_BOUNDS

WALKED_SECTIONS: tuple[str, ...] = ("flow",)
"""Configuration sections the catalogue walks.

Flow carries the hydraulic properties, the boundaries and the sinks and sources,
which is what a groundwater calibration moves. Transport joins this list the day
its solutes are calibrated the same way.
"""

NON_PHYSICAL_FIELDS: frozenset[str] = frozenset(
    {
        "id",
        "layer",
        "row",
        "col",
        "cell_id",
        "nper",
        "nlay",
        "iface",
        "boundnames",
        "substeps_per_period",
        "seed",
        "verbose",
        "listunit",
        "maxiterout",
        "iprnwt",
        "ibotav",
        "linmeth",
        "backflag",
        "itmuni",
    }
)
"""Leaf names that are numeric without being a physical quantity."""


@dataclass(frozen=True)
class CalibrationTarget:
    """One value this configuration exposes to a search."""

    path: str
    """Dotted path to write in ``[calibration.parameters.<name>].path``."""

    instance: str | None
    """The declared entry this value belongs to: a parameter id, a boundary id, a lake."""

    current: float | None
    """What the configuration holds today, which is where a bound is usually centred."""

    units: str | None
    """The unit a sibling field declares, when one does."""

    physical_bounds: tuple[float, float] | None
    """The range the physical registry enforces, or ``None`` when it knows this id not."""

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly record for the CLI and the report."""
        return {
            "path": self.path,
            "instance": self.instance,
            "current": self.current,
            "units": self.units,
            "physical_bounds": list(self.physical_bounds) if self.physical_bounds else None,
        }


def calibration_targets(config: Any) -> list[CalibrationTarget]:
    """Return every value ``config`` exposes to a calibration, in path order."""
    found: list[CalibrationTarget] = []
    for section in WALKED_SECTIONS:
        node = getattr(config, section, None)
        if node is None:
            continue
        _walk(node, prefix=section, instance=None, units=None, found=found)
    return sorted(found, key=lambda target: target.path)


def targets_by_path(targets: list[CalibrationTarget]) -> dict[str, CalibrationTarget]:
    """Index a catalogue by its dotted paths."""
    return {target.path: target for target in targets}


def _walk(
    node: Any,
    *,
    prefix: str,
    instance: str | None,
    units: str | None,
    found: list[CalibrationTarget],
) -> None:
    if isinstance(node, BaseModel):
        node_units = _declared_units(node) or units
        for field_name, field_info in type(node).model_fields.items():
            # A field the user profile does not show is a knob of the numerical
            # scheme, not a property of the aquifer. Searching over a substep
            # count would optimise the solver rather than the model.
            if extract_profile(field_info) is not Profile.USER:
                continue
            _walk(
                getattr(node, field_name, None),
                prefix=f"{prefix}.{field_name}",
                instance=instance,
                units=node_units,
                found=found,
            )
        return
    if isinstance(node, Mapping):
        for key, value in node.items():
            _walk(
                value,
                prefix=f"{prefix}.{key}",
                # The dict key IS the declared entry: a parameter id, a boundary
                # id, a lake. It is also what the physical registry is keyed on.
                instance=str(key),
                units=units,
                found=found,
            )
        return
    leaf = prefix.rsplit(".", 1)[-1]
    if not _is_a_physical_number(node) or leaf in NON_PHYSICAL_FIELDS:
        return
    found.append(
        CalibrationTarget(
            path=prefix,
            instance=instance,
            current=float(node),
            units=units,
            physical_bounds=_physical_bounds_for(instance, leaf),
        )
    )


def _is_a_physical_number(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if not isinstance(value, Real):
        return False
    return bool(float(value) == float(value))  # NaN is not a value to search from


def _declared_units(node: BaseModel) -> str | None:
    """Return the unit a node declares, under either spelling the schema uses."""
    for attribute in ("units", "unit"):
        value = getattr(node, attribute, None)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _physical_bounds_for(instance: str | None, leaf: str) -> tuple[float, float] | None:
    for candidate in (instance, leaf):
        if not candidate:
            continue
        bound = PHYSICAL_BOUNDS.get(str(candidate).lower())
        if bound is not None:
            return (bound.lo, bound.hi)
    return None


__all__ = [
    "NON_PHYSICAL_FIELDS",
    "WALKED_SECTIONS",
    "CalibrationTarget",
    "calibration_targets",
    "targets_by_path",
]
