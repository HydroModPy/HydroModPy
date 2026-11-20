"""Active-lake definition lookup shared by the LAK builder modules.

Pure payload accessors read by the other ``_lake_*`` helpers and the public
``lake`` facade. Keeping them in a leaf module breaks the import cycle that would
form if the geometry / outlet helpers reached back into ``lake``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def _scalar(value: object) -> float:
    """Coerce a plain number or a pint Quantity to a float magnitude."""
    magnitude = getattr(value, "magnitude", value)
    return float(magnitude)  # type: ignore[arg-type]


def _active_lake_definitions(model) -> dict[str, dict[str, Any]]:
    """Return the active lake definitions ``{lake_id: {polygon, bedleak, abacus}}``.

    A lake is active when its table is declared and not switched off, which
    ``Model.boundaries`` says as ``lake``. Geometry, bedleak and abacus are surfaced by the data /
    model layers; this helper only normalizes the lookup so the orchestrator
    stays grid-focused.
    """
    inputs = model.inputs
    if not inputs.boundaries.is_active("lake") or not inputs.lakes:
        return {}
    lakes = inputs.lakes

    definitions: dict[str, dict[str, Any]] = {}
    for lake_id, payload in lakes.items():
        definitions[str(lake_id)] = {
            "polygon": _lake_attr(payload, "polygon"),
            "bedleak": _lake_attr(payload, "bedleak"),
            "bedleak_unit": _lake_attr(payload, "bedleak_unit"),
            "abacus": _lake_attr(payload, "abacus"),
            "bathymetry": _lake_attr(payload, "bathymetry"),
            "bed_reconstruction": _lake_attr(payload, "bed_reconstruction"),
            "initial_stage": _lake_attr(payload, "initial_stage"),
            "steady_stage_hold": _lake_attr(payload, "steady_stage_hold"),
            "occupied_layers": _lake_attr(payload, "occupied_layers"),
            "fill_enclosed_cells": _lake_attr(payload, "fill_enclosed_cells"),
            "cutoff_wall_line": _lake_attr(payload, "cutoff_wall_line"),
            "cutoff_wall_shore": _lake_attr(payload, "cutoff_wall_shore"),
            "surfdep": _lake_attr(payload, "surfdep"),
            "outlets": _lake_attr(payload, "outlets"),
            "rainfall": _lake_attr(payload, "rainfall"),
            "evaporation": _lake_attr(payload, "evaporation"),
            "runoff": _lake_attr(payload, "runoff"),
            "runoff_rate": _lake_attr(payload, "runoff_rate"),
            "inflow": _lake_attr(payload, "inflow"),
            "withdrawal": _lake_attr(payload, "withdrawal"),
        }
    return definitions


def _lake_attr(payload: object, name: str) -> object:
    if isinstance(payload, Mapping):
        return payload.get(name)
    return getattr(payload, name, None)
