"""Unit tests for flow model-name resolution helpers."""

from types import SimpleNamespace

from hydromodpy.simulation.adapters.flow.modflow_common import resolve_base_model_name


def test_resolve_base_model_name_prefers_setup_value() -> None:
    setup = SimpleNamespace(
        model_name="launcher_name",
        settings=SimpleNamespace(model_name="legacy_name"),
    )
    assert resolve_base_model_name(setup) == "launcher_name"


def test_resolve_base_model_name_falls_back_to_legacy_settings() -> None:
    setup = SimpleNamespace(
        model_name="",
        settings=SimpleNamespace(model_name="legacy_name"),
    )
    assert resolve_base_model_name(setup) == "legacy_name"


def test_resolve_base_model_name_defaults_when_missing() -> None:
    setup = SimpleNamespace(model_name="", settings=SimpleNamespace(model_name=""))
    assert resolve_base_model_name(setup) == "default"
