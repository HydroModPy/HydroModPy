"""Unit tests for flow model-name resolution helpers."""

from types import SimpleNamespace

from hydromodpy.simulation.adapters.flow.modflow_common import (
    build_preprocess_options,
    resolve_base_model_name,
)


def test_resolve_base_model_name_prefers_setup_value() -> None:
    setup = SimpleNamespace(
        model_name="launcher_name",
    )
    assert resolve_base_model_name(setup) == "launcher_name"


def test_resolve_base_model_name_defaults_when_blank() -> None:
    setup = SimpleNamespace(model_name="")
    assert resolve_base_model_name(setup) == "default"


def test_resolve_base_model_name_defaults_when_missing() -> None:
    setup = SimpleNamespace()
    assert resolve_base_model_name(setup) == "default"


def test_build_preprocess_options_includes_setup_time_grid() -> None:
    time_grid = object()
    state = SimpleNamespace(
        setup=SimpleNamespace(
            settings=SimpleNamespace(box=False, sink_fill=True, check_grid=False),
            time_grid=time_grid,
        )
    )

    options = build_preprocess_options(state)

    assert options.box is False
    assert options.sink_fill is True
    assert options.check_grid is False
    assert options.time_grid is time_grid
