"""``[geographic.capped_breach]`` sets the limits of ``capped_breach``, and only of it."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hydromodpy.spatial.geographic.core.flow_products import capped_breach_of
from hydromodpy.spatial.geographic.geographic_config import CappedBreachConfig, GeographicConfig
from hydromodpy.spatial.terrain import CappedBreach


def _config(**overrides) -> GeographicConfig:
    return GeographicConfig(source_mode="synthetic", **overrides)


def test_the_defaults_are_half_a_metre_and_two_hundred_metres() -> None:
    section = CappedBreachConfig()

    assert section.max_depth == 0.5
    assert section.max_distance == 200.0


def test_fill_stays_the_default_and_carries_no_section() -> None:
    config = _config()

    assert config.dem_correc_type == "fill"
    assert config.capped_breach is None
    assert capped_breach_of(config) is None


def test_the_method_without_a_section_uses_the_defaults() -> None:
    config = _config(dem_correc_type="capped_breach")

    assert capped_breach_of(config) == CappedBreach(max_depth_m=0.5, max_distance_m=200.0)


def test_a_declared_section_sets_the_limits_in_metres() -> None:
    config = _config(
        dem_correc_type="capped_breach",
        capped_breach={"max_depth": "1 m", "max_distance": "0.3 km"},
    )

    assert capped_breach_of(config) == CappedBreach(max_depth_m=1.0, max_distance_m=300.0)


@pytest.mark.parametrize("method", ["fill", "breach"])
def test_the_section_with_another_method_is_refused_and_says_why(method) -> None:
    with pytest.raises(ValidationError, match="has none"):
        _config(dem_correc_type=method, capped_breach={"max_depth": 1.0})


def test_the_section_without_a_method_is_refused() -> None:
    with pytest.raises(ValidationError, match="capped_breach"):
        _config(capped_breach={"max_depth": 1.0})


@pytest.mark.parametrize("key", ["max_depth", "max_distance"])
def test_a_limit_that_bounds_nothing_is_refused(key) -> None:
    with pytest.raises(ValidationError):
        _config(dem_correc_type="capped_breach", capped_breach={key: 0.0})


def test_a_key_the_section_does_not_know_is_refused() -> None:
    with pytest.raises(ValidationError):
        _config(dem_correc_type="capped_breach", capped_breach={"max_cost": 1.0})


def test_a_sealed_config_reads_back_what_it_wrote() -> None:
    for config in (_config(), _config(dem_correc_type="capped_breach")):
        assert GeographicConfig.model_validate(config.model_dump(mode="json")) == config


def test_the_description_names_the_three_methods_and_what_each_changes() -> None:
    description = GeographicConfig.model_fields["dem_correc_type"].description or ""

    for method in ("'fill'", "'breach'", "'capped_breach'"):
        assert method in description
    assert "only raises" in description
    assert "mostly lowers" in description
    assert "raising single-cell pits" in description
    assert "lowers and raises" in description
    assert "[geographic.capped_breach]" in description
