"""Per-run memo for the heavy rebuilds several figures of one gallery share.

One ``Run`` instance serves a whole gallery, so the run object itself is the
reuse key: identity, never a name. Two different runs can be handed the same
id by a caller, and a cache that answered one with the other's mesh would be a
silent wrong figure.

An object that cannot be weakly referenced simply is not cached. That is a
speed difference and never an answer difference: the value returned is the one
the builder just produced.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable
from typing import Any
from weakref import WeakKeyDictionary


class RunMemo:
    """Memoise one value per (run, knobs) pair, for as long as the run lives."""

    def __init__(self) -> None:
        self._by_run: WeakKeyDictionary = WeakKeyDictionary()

    def get_or_build(self, run: Any, key: Hashable, build: Callable[[], Any]) -> Any:
        """Return the memoised value for ``(run, key)``, building it if absent."""
        try:
            by_knob = self._by_run.get(run)
        except TypeError:
            return build()
        if by_knob is not None and key in by_knob:
            return by_knob[key]
        value = build()
        if by_knob is None:
            self._by_run[run] = {key: value}
        else:
            by_knob[key] = value
        return value


__all__ = ["RunMemo"]
