"""The keywords of ``Project.simulate``, as changes of the configuration of the run.

``simulate(K=3.3e-3, first_clim="first")`` is shorthand for dotted paths, the
grammar of ``--set``. A name is the one ``hmp config targets`` lists for this
project, so a run and a calibration call a value alike, and a number is read in
the unit the configuration declares for it, as in the file. The changes are what
the run applies to its configuration before its plan is built, what it seals in
``config.toml`` and what ``lineage.overrides`` records.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from hydromodpy.core.exceptions import ConfigError

_NOT_A_TARGET: dict[str, str] = {"first_clim": "flow.sinks_sources.recharge.first_clim"}
"""Keywords that are no value a search moves: a rule that takes a word or a number."""


def override_changes(config: Any, overrides: Mapping[str, Any]) -> dict[str, Any]:
    """Return the dotted paths and values the keyword *overrides* of a run stand for.

    A name nothing answers to is refused with the names this project offers.
    """
    if not overrides:
        return {}
    from hydromodpy.calibration.targets import calibration_targets, targets_by_name

    targets = targets_by_name(calibration_targets(config))
    changes: dict[str, Any] = {}
    for name, value in overrides.items():
        if name in _NOT_A_TARGET:
            changes[_NOT_A_TARGET[name]] = value
        elif name in targets:
            changes[targets[name].path] = value
        else:
            raise ConfigError(_unknown_override(config, name, targets))
    return changes


def _unknown_override(config: Any, name: str, targets: Mapping[str, Any]) -> str:
    """Say why *name* is no override of this project, and what it can write instead."""
    if name == "thickness":
        kind = config.domain.depth_model.kind
        return (
            f"thickness overrides domain.depth_model.thickness, and depth_model kind "
            f"{kind!r} has no thickness. Change [domain.depth_model] in the "
            "configuration instead."
        )
    available = ", ".join(sorted({*targets, *_NOT_A_TARGET}))
    return f"Unknown parameter '{name}'. Available: {available}"


__all__ = ["override_changes"]
