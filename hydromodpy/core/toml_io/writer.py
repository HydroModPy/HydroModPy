"""Render a plain mapping as TOML text with tomli-w.

A config model is written, with comments and a profile, by
:func:`hydromodpy.core.config_kit.dump.dump_toml_with_comments`. Loading is
covered by ``loader.py`` and :meth:`HydroModPyConfig.from_toml`.

``dumps`` and ``dump`` render a plain mapping. A model with comments is written by
``core/config_kit/dump.py``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

import tomli_w


def dumps(payload: Mapping[str, Any]) -> str:
    """Return *payload* rendered as TOML text."""
    return cast(str, tomli_w.dumps(payload))


def dump(payload: Mapping[str, Any], fp: Any) -> None:
    """Write *payload* to a file object."""
    tomli_w.dump(payload, fp)


__all__ = ["dump", "dumps"]
