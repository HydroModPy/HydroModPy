"""Stand-ins for ``os``, set on one module at a time.

``WindowsOs`` reads as Windows. ``PatchedOs`` replaces some functions, for
example an ``os.link`` or an ``os.replace`` that fails as Windows does. Set it on the module under test only, for example
``monkeypatch.setattr(filesystem, "os", WindowsOs())``. ``pathlib`` and the
rest of the process keep the real ``os``, so paths still work on Linux. Not
public API.
"""

from __future__ import annotations

import os
from typing import Any


class WindowsOs:
    """``os`` with ``name == "nt"``; every other attribute is read from ``os``."""

    name = "nt"

    def __getattr__(self, attr: str) -> Any:
        return getattr(os, attr)


class PatchedOs:
    """``os`` with the functions given as keywords; every other attribute is read from ``os``."""

    def __init__(self, **overrides: Any) -> None:
        self.__dict__.update(overrides)

    def __getattr__(self, attr: str) -> Any:
        return getattr(os, attr)


__all__ = ["PatchedOs", "WindowsOs"]
