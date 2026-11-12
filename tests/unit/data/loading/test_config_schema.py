"""The ``[data]`` section: the types a run lists, and the sections those types need."""

from __future__ import annotations

import pytest

from hydromodpy.data.loading.config_schema import DataConfig


@pytest.mark.fast
def test_a_listed_type_without_its_section_is_refused(tmp_path):
    with pytest.raises(ValueError, match=r"lists 'hydrometry'.*no \[data.hydrometry\]"):
        DataConfig.from_toml_section({"types": ["hydrometry"]}, base_dir=tmp_path)


@pytest.mark.fast
def test_geology_listed_alone_takes_its_default_section(tmp_path):
    config = DataConfig.from_toml_section({"types": ["geology"]}, base_dir=tmp_path)

    assert config.geology is not None


def test_resolved_types_inject_the_default_geology_section() -> None:
    resolved = DataConfig(types=[]).with_resolved_types(["geology"])

    assert resolved.types == ["geology"]
    assert resolved.geology is not None
