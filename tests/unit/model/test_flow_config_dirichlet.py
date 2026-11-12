from pathlib import Path

import pytest

from hydromodpy.model.flow_config import FlowConfig


def _build_flow_config(
    flow_section: dict[str, object],
    *,
    base_dir: Path | None = None,
) -> FlowConfig:
    return FlowConfig.from_toml_section(
        flow_section, base_dir=Path(".") if base_dir is None else base_dir
    )


def test_dirichlet_mismatched_application_domain_raises() -> None:
    with pytest.raises(ValueError, match="does not match inferred domain"):
        _build_flow_config(
            {
                "bc": {
                    "north_side": {
                        "kind": "dirichlet",
                        "value": 100.0,
                        "application_domain": "south side",
                    }
                }
            }
        )


def test_a_boundary_keyed_by_its_family_is_refused() -> None:
    """[flow.bc.<kind>.<id>] said the kind twice and let the two disagree.

    It replaced the duplicate-entry test: a flat mapping cannot hold the same
    id twice, so the collision that guard watched can no longer be written.
    """
    with pytest.raises(ValueError, match="no longer supported"):
        _build_flow_config(
            {
                "bc": {
                    "dirichlet": {"south_side": {"value": 99.0}},
                }
            }
        )


def test_param_values_alias_is_rejected() -> None:
    with pytest.raises(ValueError, match="flow\\.param_values"):
        _build_flow_config({"param_values": {}})


def test_boundary_value_accepts_inline_unit() -> None:
    cfg = _build_flow_config(
        {
            "bc": {
                "drainage": {
                    "kind": "drain",
                    "value": "10 cm2/day",
                    "application_domain": "top",
                }
            }
        }
    )

    drainage = cfg.bc["drainage"]
    assert drainage.kind == "drain"
    assert drainage.value == pytest.approx(1.0e-3 / 86400.0)
    assert drainage.units == "m2/s"


def test_boundary_value_rejects_conflicting_units() -> None:
    with pytest.raises(ValueError, match="conflicting units"):
        _build_flow_config(
            {
                "bc": {
                    "ocean": {
                        "kind": "dirichlet",
                        "value": "1.0 m",
                        "unit": "cm",
                    }
                }
            }
        )


def test_dirichlet_side_forcing_constant_is_accepted_without_value() -> None:
    cfg = _build_flow_config(
        {
            "bc": {
                "west_side": {
                    "kind": "dirichlet",
                    "forcing": {
                        "kind": "constant",
                        "value": 99.0,
                    },
                }
            }
        }
    )

    west_side = cfg.bc["west_side"]
    assert west_side.value is None
    assert west_side.units == "m"
    assert west_side.forcing is not None
    assert west_side.forcing.kind == "constant"
    assert west_side.forcing.value == pytest.approx(99.0)
    assert west_side.forcing.units == "m"


def test_dirichlet_value_is_converted_to_meters() -> None:
    cfg = _build_flow_config(
        {
            "bc": {
                "west_side": {
                    "kind": "dirichlet",
                    "value": "100 cm",
                }
            }
        }
    )

    west_side = cfg.bc["west_side"]
    assert west_side.value == pytest.approx(1.0)
    assert west_side.units == "m"


def test_dirichlet_side_forcing_preserves_normalized_source_unit() -> None:
    cfg = _build_flow_config(
        {
            "bc": {
                "west_side": {
                    "kind": "dirichlet",
                    "unit": "centimeter",
                    "forcing": {
                        "kind": "constant",
                        "value": 120.0,
                    },
                }
            }
        }
    )

    west_side = cfg.bc["west_side"]
    assert west_side.value is None
    assert west_side.units == "m"
    assert west_side.forcing is not None
    assert west_side.forcing.units == "cm"


def test_boundary_value_rejects_unknown_units() -> None:
    with pytest.raises(ValueError, match="Unsupported length unit"):
        _build_flow_config(
            {
                "bc": {
                    "ocean": {
                        "kind": "dirichlet",
                        "value": "1.0 qblorp",
                    }
                }
            }
        )


def test_dirichlet_side_forcing_rejects_value_plus_forcing() -> None:
    with pytest.raises(
        ValueError, match="value and flow.bc.west_side.forcing are mutually exclusive"
    ):
        _build_flow_config(
            {
                "bc": {
                    "west_side": {
                        "kind": "dirichlet",
                        "value": 100.0,
                        "forcing": {
                            "kind": "constant",
                            "value": 99.0,
                        },
                    }
                }
            }
        )


def test_ocean_forcing_is_accepted() -> None:
    """A tide moves, and the backends already read the ocean head per period."""
    config = _build_flow_config(
        {
            "bc": {
                "ocean": {
                    "kind": "dirichlet",
                    "forcing": {
                        "kind": "constant",
                        "value": 0.0,
                    },
                }
            }
        }
    )
    assert config.bc["ocean"].forcing is not None


def test_a_lake_written_under_flow_bc_is_sent_to_the_sinks_and_sources() -> None:
    with pytest.raises(ValueError, match=r"A lake and a stream network are declared under"):
        _build_flow_config({"bc": {"lake": {"value": 1.0}}})
