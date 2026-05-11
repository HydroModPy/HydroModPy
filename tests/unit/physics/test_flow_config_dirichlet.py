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
                "dirichlet": {
                    "east_side": {
                        "value": 102.0,
                    }
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
                    "dirichlet": {
                        "west_boundary": {
                            "value": 101.0,
                        }
                    }
                }
            }
        )


def test_dirichlet_mismatched_application_domain_raises() -> None:
    with pytest.raises(ValueError, match="does not match inferred domain"):
        _build_flow_config(
            {
                "bc": {
                    "dirichlet": {
                        "north_side": {
                            "value": 100.0,
                            "application_domain": "south side",
                        }
                    }
                }
            }
        )


def test_duplicate_dirichlet_entries_raise() -> None:
    with pytest.raises(ValueError, match="Duplicate boundary condition entry"):
        _build_flow_config(
            {
                "bc": {
                    "dirichlet": {
                        "south_side": {"value": 99.0},
                    },
                    "south_side": {"value": 98.0},
                }
            }
        )


def test_top_level_drainage_alias_is_rejected() -> None:
    with pytest.raises(ValueError, match="flow.bc.drainage is no longer supported"):
        _build_flow_config(
            {
                "bc": {
                    "drainage": {
                        "value": 1e-6,
                        "kind": "cauchy",
                        "application_domain": "top",
                    }
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
                "cauchy": {
                    "drainage": {
                        "value": "10 cm2/day",
                        "application_domain": "top",
                    }
                }
            }
        }
    )

    drainage = cfg.bc["drainage"]
    assert drainage.value == pytest.approx(1.0e-3 / 86400.0)
    assert drainage.units == "m2/s"


def test_boundary_value_rejects_conflicting_units() -> None:
    with pytest.raises(ValueError, match="conflicting units"):
        _build_flow_config(
            {
                "bc": {
                    "dirichlet": {
                        "ocean": {
                            "value": "1.0 m",
                            "unit": "cm",
                        }
                    }
                }
            }
        )


def test_dirichlet_side_forcing_constant_is_accepted_without_value() -> None:
    cfg = _build_flow_config(
        {
            "bc": {
                "dirichlet": {
                    "west_side": {
                        "forcing": {
                            "mode": "constant",
                            "value": 99.0,
                        }
                    }
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
                "dirichlet": {
                    "west_side": {
                        "value": "100 cm",
                    }
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
                "dirichlet": {
                    "west_side": {
                        "unit": "centimeter",
                        "forcing": {
                            "mode": "constant",
                            "value": 120.0,
                        },
                    }
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
                    "dirichlet": {
                        "ocean": {
                            "value": "1.0 qblorp",
                        }
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
                "dirichlet": {
                    "east_side": {
                        "forcing": {
                            "mode": "csv",
                            "path_file": "boundary.csv",
                        }
                    }
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
        ValueError, match="value and flow.bc.dirichlet.west_side.forcing are mutually exclusive"
    ):
        _build_flow_config(
            {
                "bc": {
                    "dirichlet": {
                        "west_side": {
                            "value": 100.0,
                            "forcing": {
                                "mode": "constant",
                                "value": 99.0,
                            },
                        }
                    }
                }
            }
        )


def test_ocean_forcing_is_rejected() -> None:
    with pytest.raises(ValueError, match="only supported for side Dirichlet boundaries"):
        _build_flow_config(
            {
                "bc": {
                    "dirichlet": {
                        "ocean": {
                            "forcing": {
                                "mode": "constant",
                                "value": 0.0,
                            }
                        }
                    }
                }
            }
        )
