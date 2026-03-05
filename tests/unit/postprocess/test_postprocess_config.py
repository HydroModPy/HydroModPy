"""Unit tests for postprocess TOML configuration schema."""

from hydromodpy.postprocess.postprocess_config import PostprocessConfig


def test_postprocess_config_defaults_keep_feature_disabled() -> None:
    cfg = PostprocessConfig()

    assert cfg.enabled is False
    assert cfg.flow.enabled is True
    assert cfg.transport.enabled is True
    assert cfg.flow.intermittency.monthly is True
    assert cfg.transport.intermittency.monthly is True


def test_postprocess_config_accepts_nested_overrides() -> None:
    cfg = PostprocessConfig.model_validate(
        {
            "enabled": True,
            "flow": {
                "display": False,
                "matching_streams": False,
                "timeseries": {"enabled": False},
                "intermittency": {"monthly": False, "yearly": True},
            },
            "transport": {
                "display_particles": False,
                "timeseries": {"suffix_name": "custom_suffix"},
                "intermittency": {"daily": True},
            },
        }
    )

    assert cfg.enabled is True
    assert cfg.flow.display is False
    assert cfg.flow.matching_streams is False
    assert cfg.flow.timeseries.enabled is False
    assert cfg.flow.intermittency.monthly is False
    assert cfg.flow.intermittency.yearly is True
    assert cfg.transport.display_particles is False
    assert cfg.transport.timeseries.suffix_name == "custom_suffix"
    assert cfg.transport.intermittency.daily is True


def test_postprocess_config_migrates_legacy_timeseries_intermittency_keys() -> None:
    cfg = PostprocessConfig.model_validate(
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

    assert cfg.flow.intermittency.monthly is False
    assert cfg.flow.intermittency.yearly is True
    assert cfg.transport.intermittency.daily is True
