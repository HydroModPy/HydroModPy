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

Each target also carries the name a TOML writes to reach it, so a file names a
quantity instead of an address into the Pydantic tree. The name is derived here
and nowhere else, from the entries the walk crosses and from what the field
itself declares.

What is left out is deliberate. A boolean is a switch, not a value to search
between two bounds. An index, a count, a coordinate and an identifier are not
physical quantities. A field the user profile does not show is a knob of the numerical
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

from hydromodpy.core.config_kit.calibrable import Calibrable
from hydromodpy.core.config_kit.introspect import extract_profile
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.spatial.field.core.physical_bounds import PHYSICAL_BOUNDS

WALKED_SECTIONS: tuple[str, ...] = ("flow",)
"""Configuration sections the catalogue walks.

Flow carries the hydraulic properties, the boundaries and the sinks and sources,
which is what a groundwater calibration moves. Transport joins this list the day
its solutes are calibrated the same way.
"""


@dataclass(frozen=True)
class CalibrationTarget:
    """One value this configuration exposes to a search."""

    path: str
    """Dotted path to write in ``[calibration.parameters.<name>].path``."""

    instance: str | None
    """The outermost declared entry this value belongs to: a parameter id, a
    boundary id, a lake. It is what the physical registry is keyed on."""

    instances: tuple[str, ...]
    """Every declared entry crossed on the way down, outermost first.

    One level for ``flow.param.K``, two for a heterogeneous zone under it
    (``K``, ``zone_1``). The name is built from this chain, so an inner mapping
    key adds to the identity instead of replacing it.
    """

    name: str
    """What a TOML writes under ``[calibration.parameters.<name>]`` to reach this
    value without naming a path."""

    calibrable: Calibrable | None
    """What the field itself declares about being searched, when it declares
    anything: the space to sample in, the prior, the unit. It never decides that
    this target exists; the walk already did."""

    current: float | None
    """What the configuration holds today, which is where a bound is usually centred."""

    units: str | None
    """The unit a sibling field declares, when one does."""

    physical_bounds: tuple[float, float] | None
    """The range the physical registry enforces, or ``None`` when it knows this id not."""

    registry_id: str | None
    """The id the physical range was read under, or ``None``.

    Published because the guard that faces a declared bound with that range has
    no way to recompute it: a dotted path does not say which of its segments was
    a declared entry and which was a schema attribute, and guessing by scanning
    them would hand a well named ``k`` the ceiling of a conductivity."""

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly record for the CLI and the report."""
        return {
            "name": self.name,
            "path": self.path,
            "instance": self.instance,
            "current": self.current,
            "units": self.units,
            "physical_bounds": list(self.physical_bounds) if self.physical_bounds else None,
            "registry_id": self.registry_id,
        }


def calibration_targets(config: Any) -> list[CalibrationTarget]:
    """Return every value ``config`` exposes to a calibration, in path order."""
    found: list[_Found] = []
    for section in WALKED_SECTIONS:
        node = getattr(config, section, None)
        if node is None:
            continue
        _walk(node, prefix=section, instances=(), units=None, found=found)
    found.sort(key=lambda item: item.path)
    return _named(found)


def targets_by_path(targets: list[CalibrationTarget]) -> dict[str, CalibrationTarget]:
    """Index a catalogue by its dotted paths."""
    return {target.path: target for target in targets}


def targets_by_name(targets: list[CalibrationTarget]) -> dict[str, CalibrationTarget]:
    """Index a catalogue by the name a TOML writes.

    Names are unique by construction: a spelling two targets would share is
    given to neither, and both fall back to a longer one.
    """
    return {target.name: target for target in targets}


@dataclass(frozen=True)
class _Found:
    """One leaf the walk kept, before it is given a name."""

    path: str
    instances: tuple[str, ...]
    current: float
    units: str | None
    calibrable: Calibrable | None


def _walk(
    node: Any,
    *,
    prefix: str,
    instances: tuple[str, ...],
    units: str | None,
    found: list[_Found],
    field_info: Any = None,
) -> None:
    if isinstance(node, BaseModel):
        node_units = _declared_units(node) or units
        for field_name, sub_info in type(node).model_fields.items():
            # A field the user profile does not show is a knob of the numerical
            # scheme, not a property of the aquifer. Searching over a substep
            # count would optimise the solver rather than the model.
            if extract_profile(sub_info) is not Profile.USER:
                continue
            _walk(
                getattr(node, field_name, None),
                prefix=f"{prefix}.{field_name}",
                instances=instances,
                units=node_units,
                found=found,
                field_info=sub_info,
            )
        return
    if isinstance(node, Mapping):
        for key, value in node.items():
            _walk(
                value,
                prefix=f"{prefix}.{key}",
                # The dict key IS the declared entry: a parameter id, a boundary
                # id, a lake. It is also what the physical registry is keyed on.
                # It is appended rather than substituted, so a zone under a
                # parameter reads 'K.zone_1' and not 'zone_1'.
                instances=instances + (str(key),),
                units=units,
                found=found,
                field_info=field_info,
            )
        return
    calibrable = declared_calibrable(field_info)
    if not _is_a_physical_number(node) or calibrable is None:
        return
    found.append(
        _Found(
            path=prefix,
            instances=instances,
            current=float(node),
            units=units,
            calibrable=calibrable,
        )
    )


def declared_calibrable(field_info: Any) -> Calibrable | None:
    """Return what a Pydantic field declares about being searched, or None."""
    extra = getattr(field_info, "json_schema_extra", None)
    if not isinstance(extra, dict):
        return None
    hint = extra.get("calibrable")
    return hint if isinstance(hint, Calibrable) else None


def _base_name(item: _Found) -> str:
    """Return the spelling this target asks for, before collisions are settled."""
    leaf = item.path.rsplit(".", 1)[-1]
    if not item.instances:
        # Nothing declared it by name, so the field and what holds it say it:
        # 'flow.sinks_sources.recharge.values' reads 'recharge.values'.
        return ".".join(item.path.split(".")[-2:])
    if item.calibrable is not None and item.calibrable.is_the_value_of_its_instance:
        return ".".join(item.instances)
    return ".".join((*item.instances, leaf))


def _named(found: list[_Found]) -> list[CalibrationTarget]:
    """Give every target its name, and no name to two targets at once."""
    bases = [_base_name(item) for item in found]
    shared = {name for name in bases if bases.count(name) > 1}
    names = [
        # A spelling two targets would answer to is given to neither: the long
        # form is unambiguous, and a collision has to be visible rather than
        # arbitrated.
        ".".join(item.path.split(".")[1:]) if base in shared else base
        for item, base in zip(found, bases, strict=True)
    ]
    if len(set(names)) != len(names):  # pragma: no cover - paths are unique
        names = [".".join(item.path.split(".")[1:]) for item in found]
    return [
        CalibrationTarget(
            path=item.path,
            instance=item.instances[0] if item.instances else None,
            instances=item.instances,
            name=name,
            calibrable=item.calibrable,
            current=item.current,
            units=item.units or (item.calibrable.units if item.calibrable else None),
            physical_bounds=_physical_bounds_for(
                item.instances[0] if item.instances else None,
                item.path.rsplit(".", 1)[-1],
            ),
            registry_id=_registry_id_for(
                item.instances[0] if item.instances else None,
                item.path.rsplit(".", 1)[-1],
            ),
        )
        for item, name in zip(found, names, strict=True)
    ]


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


def _registry_id_for(instance: str | None, leaf: str) -> str | None:
    """Return the registry key this value is known under: its entry, else its leaf."""
    for candidate in (instance, leaf):
        if not candidate:
            continue
        if str(candidate).lower() in PHYSICAL_BOUNDS:
            return str(candidate).lower()
    return None


def _physical_bounds_for(instance: str | None, leaf: str) -> tuple[float, float] | None:
    key = _registry_id_for(instance, leaf)
    if key is None:
        return None
    bound = PHYSICAL_BOUNDS[key]
    return (bound.lo, bound.hi)


__all__ = [
    "WALKED_SECTIONS",
    "CalibrationTarget",
    "calibration_targets",
    "declared_calibrable",
    "targets_by_name",
    "targets_by_path",
]
