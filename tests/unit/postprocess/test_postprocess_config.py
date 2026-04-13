"""Unit tests for postprocess TOML configuration schema."""

import pytest
from pydantic import ValidationError

from hydromodpy.analysis.postprocess.postprocess_config import PostprocessConfig


def test_postprocess_config_defaults_keep_feature_disabled() -> None:
    cfg = PostprocessConfig()

    assert cfg.enabled is False
    assert cfg.flow.enabled is True
    assert cfg.transport.enabled is True
    assert cfg.flow.netcdf.enabled is False
    assert cfg.transport.netcdf.enabled is False
    assert cfg.flow.intermittency.monthly is True
    assert cfg.transport.intermittency.monthly is True
    assert cfg.flow.native_mesh_png is False
    assert cfg.profile == "standard"


def test_postprocess_config_accepts_nested_overrides() -> None:
    cfg = PostprocessConfig.model_validate(
        {
            "enabled": True,
            "flow": {
                "display": False,
                "matching_streams": False,
                "timeseries": {"enabled": False},
                "netcdf": {"enabled": True, "datetime_format": False},
                "intermittency": {"monthly": False, "yearly": True},
                "native_mesh_vtu": True,
                "native_mesh_png": True,
            },
            "transport": {
                "display_particles": False,
                "timeseries": {"suffix_name": "custom_suffix"},
                "netcdf": {"enabled": True, "mass_accumulated": False},
                "intermittency": {"daily": True},
            },
        }
    )

    assert cfg.enabled is True
    assert cfg.flow.display is False
    assert cfg.flow.matching_streams is False
    assert cfg.flow.timeseries.enabled is False
    assert cfg.flow.netcdf.enabled is True
    assert cfg.flow.netcdf.datetime_format is False
    assert cfg.flow.intermittency.monthly is False
    assert cfg.flow.intermittency.yearly is True
    assert cfg.flow.native_mesh_vtu is True
    assert cfg.flow.native_mesh_png is True
    assert cfg.transport.display_particles is False
    assert cfg.transport.timeseries.suffix_name == "custom_suffix"
    assert cfg.transport.netcdf.enabled is True
    assert cfg.transport.netcdf.mass_accumulated is False
    assert cfg.transport.intermittency.daily is True


def test_postprocess_config_rejects_legacy_timeseries_intermittency_keys() -> None:
    with pytest.raises(ValidationError):
        PostprocessConfig.model_validate(
            {
                "enabled": True,
                "flow": {
                    "timeseries": {
                        "intermittency_monthly": False,
                        "intermittency_yearly": True,
                    }
                },
                "transport": {
                    "timeseries": {
                        "intermittency_daily": True,
                    }
                },
            }
        )


def test_postprocess_solver_only_profile_disables_expensive_exports() -> None:
    cfg = PostprocessConfig.model_validate(
        {
            "enabled": True,
            "profile": "solver_only",
            "flow": {
                "display": True,
                "matching_streams": True,
                "native_mesh_npz": True,
                "native_mesh_csv": True,
                "native_mesh_vtu": True,
                "native_mesh_png": True,
                "timeseries": {"enabled": True},
                "netcdf": {"enabled": True},
            },
            "transport": {
                "display_particles": True,
                "display_transport": True,
                "timeseries": {"enabled": True},
                "netcdf": {"enabled": True},
            },
        }
    )

    assert cfg.profile == "solver_only"
    assert cfg.flow.display is False
    assert cfg.flow.matching_streams is False
    assert cfg.flow.native_mesh_npz is False
    assert cfg.flow.native_mesh_csv is False
    assert cfg.flow.native_mesh_vtu is False
    assert cfg.flow.native_mesh_png is False
    assert cfg.flow.timeseries.enabled is False
    assert cfg.flow.netcdf.enabled is False
    assert cfg.transport.display_particles is False
    assert cfg.transport.display_transport is False
    assert cfg.transport.timeseries.enabled is False
    assert cfg.transport.netcdf.enabled is False
