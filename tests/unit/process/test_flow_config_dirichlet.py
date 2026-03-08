from pathlib import Path

import pytest

from hydromodpy.process.flow.flow_config import FlowConfig


def _build_flow_config(flow_section: dict[str, object]) -> FlowConfig:
    return FlowConfig.from_toml_section(flow_section, base_dir=Path("."))


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
    assert east_side["id"] == "east_side"
    assert east_side["application_domain"] == "east side"


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
                        "type": "cauchy",
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
                        "value": "1e-6 m2/s",
                        "application_domain": "top",
                    }
                }
            }
        }
    )

    drainage = cfg.bc["drainage"]
    assert drainage["value"] == pytest.approx(1e-6)
    assert drainage["units"] == "m2/s"


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
