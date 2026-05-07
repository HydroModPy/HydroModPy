"""Shared constrained config types."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

IdentifierStr = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$")]

__all__ = ["IdentifierStr"]
