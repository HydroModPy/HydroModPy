"""Where a named calibration protocol is resolved.

One place holds the registered methods, so a file names one and never imports
one, and an unknown name is refused with the list of what exists.
"""

from __future__ import annotations

import copy
import functools
from collections.abc import Mapping
from typing import Any

from pydantic import TypeAdapter, ValidationError

from hydromodpy.calibration.config import (
    CalibObjectiveBlockDecl,
    CalibPhaseDecl,
    fold_a_legacy_regime,
)
from hydromodpy.calibration.protocols.base import CalibrationProtocol
from hydromodpy.calibration.protocols.matching_hydrographic_network import (
    MatchingHydrographicNetwork,
)

_PROTOCOLS: dict[str, CalibrationProtocol] = {
    protocol.name: protocol for protocol in (MatchingHydrographicNetwork(),)
}

WRITTEN_SECTIONS = ("objective_blocks", "phases")
"""The ``[calibration]`` keys a protocol owns in full: nothing the file
declares there survives beside what the protocol produces, so a mismatch is a
contradiction (:func:`expand_calibration_protocol`). Public so a caller
unfolding a protocol on its own (``hmp calibrate --expand``) knows which keys
came from the protocol rather than from the file itself.

``outputs`` is deliberately absent: a protocol may add one entry there (the
point output a block reads) beside outputs the file supplies for its own
reasons (a network output's geometry), so the section is never protocol-owned
in full and a whole-section comparison would refuse an ordinary file. What
``--expand`` shows of it is computed separately, by diffing against what the
file already declared (``hydromodpy._api._expand_calibration_section``)."""


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

    A document already carrying those stages is therefore one this package may
    have written itself, and is accepted when they are the ones the protocol
    would write. Only a contradiction is refused, and it names its section.
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

    already_written = [key for key in WRITTEN_SECTIONS if calibration.get(key)]
    try:
        expanded = get_protocol(name).expand(options, document)
    except ValueError as exc:
        if not already_written:
            raise
        joined = ", ".join(f"[calibration].{key}" for key in already_written)
        raise ValueError(
            f"[calibration].protocol = {name!r} writes {joined}, and this file declares "
            "them as well, so they have to be compared against what the protocol would "
            f"write -- which it cannot write here: {exc} Keep one: drop the protocol to "
            "write the stages by hand, or drop the stages to let the protocol write them."
        ) from exc

    folded_calibration = _read_legacy_declaration(calibration, expanded["calibration"])
    contradicted = [
        key
        for key in already_written
        if not _declares_what_the_protocol_writes(
            key, folded_calibration[key], expanded["calibration"].get(key)
        )
    ]
    if contradicted:
        joined = ", ".join(f"[calibration].{key}" for key in contradicted)
        raise ValueError(
            f"[calibration].protocol = {name!r} writes {joined}, and this file declares "
            "something else there. Keep one: drop the protocol to write the stages by "
            "hand, or drop the stages to let the protocol write them."
        )

    normalized = copy.deepcopy(dict(document))
    normalized.update(expanded)
    return normalized


@functools.cache
def _section_adapter(section: str) -> TypeAdapter:
    """Return the validator of one section a protocol writes."""
    return {
        "phases": TypeAdapter(list[CalibPhaseDecl]),
        "objective_blocks": TypeAdapter(list[CalibObjectiveBlockDecl]),
    }[section]


def _declares_what_the_protocol_writes(section: str, declared: Any, produced: Any) -> bool:
    """Say whether *declared* is the assembly the protocol would have written.

    A file this package dumped carries both the ``protocol`` table and the
    stages that table produced -- on purpose, so the run records the method and
    what it ran. Reloading it must not be refused as a contradiction. The two
    sides are compared through the section model rather than raw: the dumped one
    carries every default filled in, the fresh expansion only what the protocol
    spelled out, and nobody wrote the difference.

    *declared* is read here as given: every recognized legacy spelling is
    already folded by :func:`_read_legacy_declaration`, which runs once, on
    the whole ``[calibration]`` table, before this is called per section.
    """
    adapter = _section_adapter(section)
    try:
        here = adapter.dump_python(adapter.validate_python(declared), mode="json")
    except ValidationError:
        return False
    return here == adapter.dump_python(adapter.validate_python(produced or []), mode="json")


def _read_legacy_declaration(
    calibration: Mapping[str, Any], produced: Mapping[str, Any]
) -> dict[str, Any]:
    """Return *calibration* with every recognized pre-migration spelling folded.

    Two folds, paired by phase position with what the protocol produces today.

    Regime: a stage sealed before phases said their own ``regime`` spells it
    as ``overrides`` and describes its steady window with dates
    (:func:`fold_a_legacy_regime`). It is read as the regime it states, and
    its description is not compared.

    Cost: a stage sealed before B11 scored itself with ``variable`` +
    ``objective`` on the phase, with no block for it in ``objective_blocks``
    at all -- a spelling that spans two sections of ``[calibration]``, so it
    is folded jointly, here, rather than per section. The block it is short
    of is read off the phase's own declared ``objective`` and only accepted
    when it names the same metric the protocol produces today: a real drift
    in the criterion still differs from it, and is still refused.

    Neither fold changes what the run replays with: :func:`expand_calibration_protocol`
    always overwrites both sections with the fresh expansion. This only
    decides whether the sealed spelling is accepted as that expansion's own,
    or refused as a contradiction of it.
    """
    folded = dict(calibration)
    phases = calibration.get("phases")
    produced_phases = produced.get("phases")
    if not isinstance(phases, list) or not isinstance(produced_phases, list):
        return folded

    blocks_by_name: dict[Any, Mapping[str, Any]] = {
        block.get("name"): block
        for block in produced.get("objective_blocks") or []
        if isinstance(block, Mapping)
    }
    declared_blocks = list(calibration.get("objective_blocks") or [])
    declared_block_names = {
        block.get("name") for block in declared_blocks if isinstance(block, Mapping)
    }

    read: list[Any] = []
    for index, phase in enumerate(phases):
        fresh = produced_phases[index] if index < len(produced_phases) else None
        if not isinstance(phase, Mapping) or not isinstance(fresh, Mapping):
            read.append(phase)
            continue
        current: Mapping[str, Any] = phase
        regime_folded = fold_a_legacy_regime(current, fresh.get("steady_window"))
        if regime_folded is not None:
            regime_folded["description"] = fresh.get("description", "")
            current = regime_folded
        metric_folded, implied_block = _fold_a_legacy_single_metric_stage(
            current, fresh, blocks_by_name
        )
        if metric_folded is not None:
            current = metric_folded
            if implied_block is not None and implied_block not in declared_block_names:
                declared_blocks.append(blocks_by_name[implied_block])
                declared_block_names.add(implied_block)
        read.append(current)

    folded["phases"] = read
    if "objective_blocks" in calibration:
        folded["objective_blocks"] = declared_blocks
    return folded


def _fold_a_legacy_single_metric_stage(
    phase: Mapping[str, Any],
    fresh: Mapping[str, Any],
    blocks_by_name: Mapping[Any, Mapping[str, Any]],
) -> tuple[dict[str, Any] | None, Any]:
    """Return a phase read as scoring the block its ``variable``/``objective`` imply.

    Only when the phase carries the pre-B11 single-metric spelling, the phase
    it pairs with today names exactly one block, and that block's metric is
    the one the phase's own ``objective`` already names: a phase whose
    objective differs is a real drift, not this spelling, and is left
    unfolded so the normal comparison refuses it.

    Returns the folded phase and the name of the block it was found to imply,
    or ``(None, None)`` when this is not that spelling.
    """
    if phase.get("variable") is None and phase.get("objective") is None:
        return None, None
    if phase.get("objective_blocks"):
        return None, None
    fresh_blocks = fresh.get("objective_blocks")
    if not isinstance(fresh_blocks, list) or len(fresh_blocks) != 1:
        return None, None
    name = fresh_blocks[0]
    block = blocks_by_name.get(name)
    if not isinstance(block, Mapping) or str(block.get("metric")) != str(phase.get("objective")):
        return None, None
    folded = dict(phase)
    folded["objective_blocks"] = [name]
    folded["variable"] = None
    folded["objective"] = None
    folded["observed_station_id"] = None
    return folded, name


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
                "paper_value": deviation.paper_value,
            }
            for deviation in protocol.deviations
        ],
    }
    if declared is not None:
        record["options_away_from_the_recipe"] = [
            dict(item) for item in protocol_options_away_from_the_recipe(name, declared)
        ]
    return record


__all__ = [
    "WRITTEN_SECTIONS",
    "available_protocols",
    "expand_calibration_protocol",
    "get_protocol",
    "protocol_options_away_from_the_recipe",
    "protocol_record",
]
