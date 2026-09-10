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


def protocol_record(name: str) -> dict[str, Any]:
    """Return what a run persists about the protocol it followed.

    A calibrated value that came out of a published method carries the method
    with it: the report, the session and anyone reading either can then say what
    the number rests on without going back to the file.
    """
    protocol = get_protocol(name)
    return {
        "name": protocol.name,
        "title": protocol.title,
        "summary": protocol.summary,
        "stages": list(protocol.stages),
        "references": [reference.cite() for reference in protocol.references],
    }


__all__ = [
    "available_protocols",
    "expand_calibration_protocol",
    "get_protocol",
    "protocol_record",
]
