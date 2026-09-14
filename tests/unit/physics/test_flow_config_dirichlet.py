from pathlib import Path

import pytest

from hydromodpy.physics.flow.flow_config import FlowConfig


def _build_flow_config(
    flow_section: dict[str, object],
    *,
    base_dir: Path | None = None,
) -> FlowConfig:
    return FlowConfig.from_toml_section(
        flow_section, base_dir=Path(".") if base_dir is None else base_dir
    )


def test_dirichlet_side_key_infers_application_domain() -> None:
    cfg = _build_flow_config(
        {
            "bc": {
                "east_side": {
                    "kind": "dirichlet",
                    "value": 102.0,
                }
            }
        }
    )

    east_side = cfg.bc["east_side"]
    assert east_side.id == "east_side"
    assert east_side.application_domain == "east side"


def test_dirichlet_legacy_boundary_alias_is_rejected() -> None:
    with pytest.raises(ValueError, match="unsupported Dirichlet key 'west_boundary'"):
        _build_flow_config(
            {
                "bc": {
                    "west_boundary": {
                        "kind": "dirichlet",
                        "value": 101.0,
                    }
                }
            }
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


def test_the_flat_drainage_form_is_the_supported_one() -> None:
    """A boundary is keyed by what it is; the kind is an attribute of it."""
    cfg = _build_flow_config(
        {
            "active_bc": ["drainage"],
            "bc": {"drainage": {"value": 1e-6}},
        }
    )

    drainage = cfg.bc["drainage"]
    assert drainage.kind == "cauchy"
    assert drainage.application_domain == "top"
    assert drainage.value == 1e-6


def test_a_drainage_needs_no_table_at_all() -> None:
    """The registry describes it entirely, so active_bc is enough."""
    cfg = _build_flow_config({"active_bc": ["drainage"]})

    assert cfg.bc["drainage"].kind == "cauchy"
    assert cfg.bc["drainage"].value == 0.0


def test_a_drainage_may_be_robin_instead() -> None:
    """cauchy and robin are two surface closures, swapped by a field."""
    cfg = _build_flow_config({"active_bc": ["drainage"], "bc": {"drainage": {"kind": "robin"}}})

    assert cfg.bc["drainage"].kind == "robin"


def test_a_kind_from_another_family_is_refused() -> None:
    with pytest.raises(ValueError, match="not interchangeable"):
        _build_flow_config({"active_bc": ["drainage"], "bc": {"drainage": {"kind": "dirichlet"}}})


def test_param_values_alias_is_rejected() -> None:
    with pytest.raises(ValueError, match="flow\\.param_values"):
        _build_flow_config({"param_values": {}})


def test_boundary_value_accepts_inline_unit() -> None:
    cfg = _build_flow_config(
        {
            "bc": {
                "drainage": {
                    "kind": "cauchy",
                    "value": "10 cm2/day",
                    "application_domain": "top",
                }
            }
        }
    )

    drainage = cfg.bc["drainage"]
    assert drainage.value == pytest.approx(1.0e-3 / 86400.0)
    assert drainage.units == "m2/s"


def test_cauchy_drainage_accepts_kind_key() -> None:
    cfg = _build_flow_config(
        {
            "bc": {
                "drainage": {
                    "kind": "cauchy",
                    "value": "10 cm2/day",
                    "application_domain": "top",
                }
            }
        }
    )

    assert cfg.bc["drainage"].kind == "cauchy"


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
                        "mode": "constant",
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
    assert west_side.forcing.mode == "constant"
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
                        "mode": "constant",
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


def test_dirichlet_side_forcing_csv_resolves_relative_path(tmp_path: Path) -> None:
    csv_path = tmp_path / "boundary.csv"
    csv_path.write_text("date,value\n2003-01-01,10.0\n", encoding="utf-8")

    cfg = _build_flow_config(
        {
            "bc": {
                "east_side": {
                    "kind": "dirichlet",
                    "forcing": {
                        "mode": "csv",
                        "path_file": "boundary.csv",
                    },
                }
            }
        },
        base_dir=tmp_path,
    )

    east_side = cfg.bc["east_side"]
    assert east_side.forcing is not None
    assert east_side.forcing.path_file == csv_path.resolve()


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
                            "mode": "constant",
                            "value": 99.0,
                        },
                    }
                }
            }
        )


def test_ocean_forcing_is_rejected() -> None:
    with pytest.raises(ValueError, match="only supported for side Dirichlet boundaries"):
        _build_flow_config(
            {
                "bc": {
                    "ocean": {
                        "kind": "dirichlet",
                        "forcing": {
                            "mode": "constant",
                            "value": 0.0,
                        },
                    }
                }
            }
        )
