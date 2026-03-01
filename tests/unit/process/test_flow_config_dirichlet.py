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


def test_dirichlet_legacy_boundary_alias_is_canonicalized() -> None:
    cfg = _build_flow_config(
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

    assert "west_boundary" not in cfg.bc
    assert cfg.bc["west_side"]["application_domain"] == "west side"


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


def test_dirichlet_duplicate_aliases_raise() -> None:
    with pytest.raises(ValueError, match="Duplicate Dirichlet entry"):
        _build_flow_config(
            {
                "bc": {
                    "dirichlet": {
                        "south_side": {"value": 99.0},
                        "south_boundary": {"value": 98.0},
                    }
                }
            }
        )
