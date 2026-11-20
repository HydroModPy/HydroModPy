"""Root configuration wrapper and migration callables.

Carries the root configuration model class and migration functions down to core
and loader helpers without depending on ``hydromodpy.config``.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel


@dataclass(frozen=True, slots=True)
class RootConfig:
    """Root configuration model class and its layer and merged migrations."""

    model: type[BaseModel]
    migrate_layers: Callable[[Sequence[tuple[str | Path | None, Any]]], list[str]]
    migrate_merged: Callable[[dict[str, Any], Sequence[tuple[str | Path | None, Any]]], list[str]]


def model_of(root: type[BaseModel] | RootConfig) -> type[BaseModel]:
    """Return the model class behind *root*: itself, or the one the wrapper holds.

    The section walkers and the schema exporters take either form, so a caller
    that holds the full ``RootConfig`` passes it on and one that holds only the
    class passes that.
    """
    return root.model if isinstance(root, RootConfig) else root


__all__ = ["RootConfig", "model_of"]
