"""Where the warnings of a validator go while a check collects them.

A validator that warns about a document calls :func:`say` instead of
``warnings.warn``. With no sink open, ``say`` warns as before, so a script and
the command line see what they always saw. Inside ``with collecting() as said:``
the text is kept in the list and nothing reaches the warning machinery.

The sink is a ``ContextVar`` made once when the module is imported. A thread
sets and reads its own value, so two checks in two threads, or a check beside a
run, never see each other's warnings, and the filters of the process are never
touched (rule 15).
"""

from __future__ import annotations

import warnings
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Said:
    """One warning a validator gave, with the category it chose."""

    text: str
    category: type[Warning]


_SINK: ContextVar[list[Said] | None] = ContextVar("hmp_said_sink", default=None)


def say(text: str, category: type[Warning] = UserWarning, *, stacklevel: int = 1) -> None:
    """Keep *text* in the open sink, or warn when no sink is open.

    *stacklevel* counts from the caller of ``say``, as it does for
    ``warnings.warn`` from its own caller.
    """
    sink = _SINK.get()
    if sink is None:
        warnings.warn(text, category, stacklevel=stacklevel + 1)
        return
    sink.append(Said(text, category))


@contextmanager
def collecting() -> Iterator[list[Said]]:
    """Open a sink for this thread and yield its list.

    Sinks nest: the inner one takes what is said inside it, and the outer one
    comes back when it closes, also after an exception.
    """
    said: list[Said] = []
    token = _SINK.set(said)
    try:
        yield said
    finally:
        _SINK.reset(token)
