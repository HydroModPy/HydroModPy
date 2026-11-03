"""A template never writes a value the reload refuses in a section that is off.

``[geographic.crossings]`` is off by default, and its ``kinds`` reached the
template as ``kinds = []``: a key the model fills by itself, labeled
REQUIRED and given an empty placeholder that ``min_length=1`` refuses. A key
filled by a ``default_factory`` is written with that value; a key that is
really required, in a section whose ``enabled`` is false, is written
commented with its form.
"""

from __future__ import annotations

import tomllib
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.toml_io import generator
from hydromodpy.core.toml_io.generator import generate_toml


class _Probe(BaseModel):
    """Probe section."""

    model_config = ConfigDict(extra="forbid")

    enabled: Annotated[bool, Profile.USER] = Field(default=False, description="Switch.")
    target: Annotated[str, Profile.USER] = Field(description="Needed when enabled.")
    kinds: Annotated[list[str], Profile.USER] = Field(
        default_factory=lambda: ["road", "bridge"], min_length=1, description="Kinds."
    )


def test_a_factory_key_carries_its_value_and_a_required_key_stays_commented(monkeypatch) -> None:
    monkeypatch.setattr(generator, "root_sections", lambda: {"probe": _Probe})

    text = generate_toml(modules=["probe"], profile="user")

    assert 'kinds = ["road", "bridge"]' in text
    assert "kinds = []" not in text
    assert '# Type: list[str] | Default: ["road", "bridge"]' in text
    assert '# target = ""' in text
    assert "\ntarget =" not in text
    assert tomllib.loads(text)["probe"] == {"enabled": False, "kinds": ["road", "bridge"]}


def test_the_crossings_section_of_the_template_is_valid_as_written() -> None:
    from hydromodpy.spatial.geographic.crossings_config import CrossingNotchConfig

    section = tomllib.loads(generate_toml(modules=["geographic"], profile="user"))["geographic"]

    assert section["crossings"]["kinds"] == ["road", "railway", "bridge"]
    CrossingNotchConfig.model_validate(section["crossings"])
