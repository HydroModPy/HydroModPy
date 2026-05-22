"""TOML writing helpers backed by tomli-w."""

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
