"""``hmp dev doctor`` - same diagnostics as ``hmp doctor``, exposed under ``dev``.

Both ``hmp doctor`` and ``hmp dev doctor`` share the exact same implementation
(:mod:`hydromodpy.cli.commands.doctor`). The top-level form remains as a
convenient shortcut for fresh installs; the ``dev`` form keeps the diagnostic
verb grouped alongside the other developer-only commands.
"""

from __future__ import annotations

from hydromodpy.cli.commands.doctor import (
    HELP,
    NAME,
    register,
    run,
)

__all__ = ("NAME", "HELP", "register", "run")
