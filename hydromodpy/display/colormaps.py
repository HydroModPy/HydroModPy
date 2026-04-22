"""Colormap policy.

A short list of perceptually-broken colormaps is banned across the whole
display corpus. :func:`get_cmap` is the single entry point — it rejects
a banned name up-front so misuse fails loudly at figure construction
time, not later in a CI pipeline. The ``check_no_banned_in_call`` helper
is used by the unit-test that scans the figures directory for direct
matplotlib calls.
"""

from __future__ import annotations

from typing import Iterable

BANNED_CMAPS: frozenset[str] = frozenset(
    {
        "jet",
        "rainbow",
        "hsv",
        "nipy_spectral",
        "gist_rainbow",
    }
)

PREFERRED_CMAPS: dict[str, str] = {
    "sequential": "viridis",
    "diverging": "RdBu_r",
    "cyclic": "twilight",
    "categorical": "tab10",
}


def get_cmap(name: str | None = None, kind: str = "sequential"):
    """Return a matplotlib colormap.

    ``name`` may be ``None``; in that case the preferred cmap for ``kind``
    is used. Any banned name is rejected.
    """
    import matplotlib as mpl

    if name is None:
        name = PREFERRED_CMAPS.get(kind, "viridis")
    if name in BANNED_CMAPS:
        raise ValueError(
            f"colormap '{name}' is banned (non-perceptual). "
            f"Use one of the preferred cmaps: {sorted(PREFERRED_CMAPS.values())}."
        )
    return mpl.colormaps.get_cmap(name)


def check_no_banned_in_call(call_args: Iterable[str]) -> list[str]:
    """Return the subset of ``call_args`` that are banned colormap names.

    Used by the test that statically inspects figure source files to make
    sure no figure hard-codes a banned cmap via a literal string.
    """
    return [arg for arg in call_args if arg in BANNED_CMAPS]


__all__ = [
    "BANNED_CMAPS",
    "PREFERRED_CMAPS",
    "get_cmap",
    "check_no_banned_in_call",
]
