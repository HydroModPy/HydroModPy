"""Annotated string types that clean a configuration value before validation.

A text is stripped of its outer spaces, and a text that is empty after that is refused.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from hydromodpy.core.config_kit.types import NonEmptyStr


class Named(BaseModel):
    name: NonEmptyStr


def test_a_name_is_stripped() -> None:
    assert Named(name="  lake  ").name == "lake"


def test_a_blank_name_is_refused() -> None:
    with pytest.raises(ValidationError, match="value cannot be empty"):
        Named(name="   ")
