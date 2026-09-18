"""What ``[geographic] write_intermediates`` keeps, and what ``keep`` means.

The preprocessing tree is a rebuildable cache, dropped at the end of whoever
owns the session. Two different reasons keep it: the user asked for the
rasters on disk, or a multi-run session is still reading them.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from hydromodpy.spatial.geographic import store_ingestion
from hydromodpy.workflow.steps.export import step_cleanup_preprocessing


@pytest.fixture
def cleanup_calls(monkeypatch):
    """Record the ``keep`` each call asks for, without touching the disk."""
    kept: list[bool] = []
    monkeypatch.setattr(
        store_ingestion,
        "cleanup_stable_folder",
        lambda geo, *, keep=False: kept.append(keep) or 0,
    )
    return kept


def _ctx(geographic: object, *, write_intermediates: bool) -> SimpleNamespace:
    return SimpleNamespace(
        cfg=SimpleNamespace(geographic=SimpleNamespace(write_intermediates=write_intermediates)),
        setup=SimpleNamespace(workspace=None, geographic=geographic),
    )


@pytest.mark.parametrize("write_intermediates", [True, False])
def test_the_option_that_asked_for_the_rasters_keeps_the_tree(
    cleanup_calls, write_intermediates: bool
) -> None:
    step_cleanup_preprocessing(
        _ctx(SimpleNamespace(stable_folder=None), write_intermediates=write_intermediates)
    )

    assert cleanup_calls == [write_intermediates]


def test_a_session_that_owns_the_tree_keeps_it_whatever_the_option_says(cleanup_calls) -> None:
    """``keep=True`` is a lifetime statement, independent of the option."""
    step_cleanup_preprocessing(
        _ctx(SimpleNamespace(stable_folder=None), write_intermediates=False), keep=True
    )

    assert cleanup_calls == [True]


def test_a_run_without_a_geographic_runtime_cleans_nothing(cleanup_calls) -> None:
    assert step_cleanup_preprocessing(_ctx(None, write_intermediates=True)) == 0
    assert cleanup_calls == []


def test_releasing_the_raster_cache_loses_nothing() -> None:
    """A cached raster is on disk already: the backend writes, then caches."""
    import inspect

    from hydromodpy.spatial.delineation.whitebox_workflows_backend.raster import (
        WhiteboxRasterBackend,
    )

    source = inspect.getsource(WhiteboxRasterBackend._write_raster)
    write_at = source.index("write_raster")
    cache_at = source.index("_raster_cache[path] = raster")
    assert write_at < cache_at, (
        "the raster cache is only ever filled after the file is written; if that "
        "stops being true, dropping the cache starts losing data"
    )
