"""Where a named calibration protocol is resolved.

One place holds the registered methods, so a file names one and never imports
one, and an unknown name is refused with the list of what exists.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from hydromodpy.calibration.protocols.base import CalibrationProtocol
from hydromodpy.calibration.protocols.matching_hydrographic_network import (
    MatchingHydrographicNetwork,
)

_PROTOCOLS: dict[str, CalibrationProtocol] = {
    protocol.name: protocol for protocol in (MatchingHydrographicNetwork(),)
}

_WRITTEN_SECTIONS = ("phases", "objective_blocks")


def available_protocols() -> tuple[str, ...]:
    """Return every registered protocol name, sorted."""
    return tuple(sorted(_PROTOCOLS))


def get_protocol(name: str) -> CalibrationProtocol:
    """Return the registered protocol, or refuse with the list of what exists."""
    protocol = _PROTOCOLS.get(name)
    if protocol is None:
        joined = ", ".join(available_protocols())
        raise ValueError(f"Unknown calibration protocol {name!r}. Registered: {joined}.")
    return protocol


def expand_calibration_protocol(document: Mapping[str, Any]) -> dict[str, Any]:
    """Return the document with the named protocol's assembly written into it.

    A document that names no protocol is returned unchanged. The input is never
    mutated, and the ``protocol`` table stays in place: the run records which
    method produced its stages.
    """
    calibration = document.get("calibration")
    if not isinstance(calibration, Mapping):
        return dict(document)
    declaration = calibration.get("protocol")
    if declaration is None:
        return dict(document)

    if isinstance(declaration, str):
        name, options = declaration, {}
    elif isinstance(declaration, Mapping):
        options = dict(declaration)
        raw_name = options.pop("name", None)
        if not raw_name:
            joined = ", ".join(available_protocols())
            raise ValueError(
                f"[calibration.protocol] needs a 'name'. Registered protocols: {joined}."
            )
        name = str(raw_name)
    else:
        raise ValueError(
            "[calibration.protocol] must be a protocol name or a table carrying one, "
            f"got {type(declaration).__name__}."
        )

    already_written = [key for key in _WRITTEN_SECTIONS if calibration.get(key)]
    if already_written:
        joined = ", ".join(f"[calibration].{key}" for key in already_written)
        raise ValueError(
            f"[calibration].protocol = {name!r} writes {joined}, and this file already "
            "declares them. Keep one: drop the protocol to write the stages by hand, or "
            "drop the stages to let the protocol write them."
        )

    expanded = get_protocol(name).expand(options, document)
    normalized = copy.deepcopy(dict(document))
    normalized.update(expanded)
    return normalized


def protocol_options_away_from_the_recipe(
    name: str, declared: object
) -> tuple[dict[str, Any], ...]:
    """Return every adjustable option a file set to something other than the recipe's value.

    A protocol keeps its identity when an option moves, and the reader comparing a
    number to the publication is exactly the one who has to know that it moved.
    Nothing else records it: the recipe describes its own defaults, and the
    declaration describes only what the file wrote.
    """
    protocol = get_protocol(name)
    recipe = type(declared).model_validate({"name": protocol.name})
    changed: list[dict[str, Any]] = []
    for key in sorted(protocol.adjustable):
        if not hasattr(recipe, key):
            continue
        here = getattr(declared, key)
        published = getattr(recipe, key)
        if here == published:
            continue
        changed.append({"key": key, "here": here, "recipe": published})
    return tuple(changed)


def protocol_record(name: str, declared: object | None = None) -> dict[str, Any]:
    """Return what a run persists about the protocol it followed.

    A calibrated value that came out of a published method carries the method
    with it: the report, the session and anyone reading either can then say what
    the number rests on without going back to the file. The version is part of
    that: a number which informed a decision must be replayable with the recipe of
    its era, not with whatever the recipe became.
    """
    protocol = get_protocol(name)
    record: dict[str, Any] = {
        "name": protocol.name,
        "version": protocol.version,
        "title": protocol.title,
        "summary": protocol.summary,
        "stages": list(protocol.stages),
        "references": [reference.cite() for reference in protocol.references],
        "support": dict(protocol.support),
        "deviations": [
            {
                "key": deviation.key,
                "paper": deviation.paper,
                "here": deviation.here,
                "why": deviation.why,
            }
            for deviation in protocol.deviations
        ],
        "reference_values": dict(protocol.reference_values),
    }
    if declared is not None:
        record["options_away_from_the_recipe"] = [
            dict(item) for item in protocol_options_away_from_the_recipe(name, declared)
        ]
    return record


def assert_version_is_available(name: str, version: str | None) -> None:
    """Refuse a pinned version this registry does not hold.

    Approximating it with the current recipe is the one thing a pin exists to
    prevent: a file that pins 1.0 and silently gets 1.1 has lost the guarantee it
    asked for.
    """
    if version is None:
        return
    protocol = get_protocol(name)
    if str(version) != str(protocol.version):
        raise ValueError(
            f"[calibration.protocol] pins {name!r} at version {version!r}, and this "
            f"installation carries {protocol.version!r}. A pin exists so a result stays "
            "replayable, so it is refused rather than approximated: install the version "
            "this file was written against, or drop the pin to run the one that is here."
        )


__all__ = [
    "assert_version_is_available",
    "available_protocols",
    "expand_calibration_protocol",
    "get_protocol",
    "protocol_options_away_from_the_recipe",
    "protocol_record",
]
