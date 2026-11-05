"""The data-cache Protocol is structural, and the overview state starts empty."""

from __future__ import annotations

from hydromodpy.core.contracts.data_cache_backend import DataCacheBackend
from hydromodpy.core.contracts.overview import DataOverviewState


def test_a_class_with_the_six_methods_is_a_cache_backend() -> None:
    names = ("register", "find_cached", "list_entries", "table_names", "invalidate", "close")
    backend = type("Backend", (), {name: lambda self, *a, **k: None for name in names})()

    assert isinstance(backend, DataCacheBackend)
    assert not isinstance(object(), DataCacheBackend)


def test_a_new_overview_state_holds_only_the_config() -> None:
    state = DataOverviewState(cfg="config")

    assert state.cfg == "config"
    assert state.config_path is None
    assert state.workspace is None
    assert state.geographic is None
    assert DataOverviewState(cfg=None).loaded_data is not state.loaded_data
