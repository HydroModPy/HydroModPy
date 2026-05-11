"""Compute which pipeline step is the earliest affected by a set of overrides.

When a calibration overrides a field deep in the config (e.g.
``flow.param.K.field.value``), only the steps whose
``config_sections`` consume that part of the tree need to re-run. The
earlier (setup) steps give the same result for every trial and can be
executed once, then shared across the ask/tell loop.

``earliest_affected_step`` performs a longest-prefix match between every
override path and every step's declared ``config_sections``. The first
step (lowest index) that owns a matching section wins.

All steps in ``steps[earliest:]`` must re-run, even those with empty
``config_sections``, because they consume the output state produced by
the re-run predecessor.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from hydromodpy.core.exceptions import ConfigError


def _matches(path: str, section: str) -> bool:
    """Return True if ``path`` is ``section`` or a descendant of it.

    A path matches a section when the section is a dotted-prefix of the
    path. Both ``"flow"`` matches ``"flow.param.K.field.value"`` and
    ``"flow.param.K"`` matches ``"flow.param.K.field.value"``. The empty
    section never matches.
    """
    if not section:
        return False
    if path == section:
        return True
    return path.startswith(section + ".")


def earliest_affected_step(
    override_paths: Iterable[str],
    steps: Sequence[Any],
) -> int:
    """Return the lowest step index affected by any of ``override_paths``.

    Parameters
    ----------
    override_paths
        Dotted config paths that the calibration will mutate on each
        trial (e.g. ``{"flow.param.K.field.value"}``).
    steps
        Ordered pipeline steps, each with a ``config_sections`` class
        variable declaring the TOML subtrees it consumes.

    Returns
    -------
    int
        The index of the first step whose ``config_sections`` owns any
        override path. If no override path matches any section, returns
        ``len(steps)`` (nothing needs to re-run).

    Raises
    ------
    ConfigError
        When ``override_paths`` is empty or any step has a falsy
        ``config_sections`` tuple entry.
    """
    paths = [p for p in override_paths if p]
    if not paths:
        raise ConfigError("earliest_affected_step requires at least one override path")

    earliest = len(steps)
    for path in paths:
        for index, step in enumerate(steps):
            sections = getattr(step, "config_sections", ()) or ()
            if any(_matches(path, section) for section in sections):
                if index < earliest:
                    earliest = index
                break
    return earliest


__all__ = ("earliest_affected_step",)
