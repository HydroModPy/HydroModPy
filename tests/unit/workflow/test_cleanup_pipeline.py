from __future__ import annotations

from types import SimpleNamespace

import pytest

from hydromodpy.spatial.geographic import store_ingestion
from hydromodpy.workflow.steps.export import step_cleanup_preprocessing


@pytest.mark.parametrize("write_intermediates", [True, False])
def test_the_cleanup_keeps_the_rasters_the_option_just_wrote(
    monkeypatch, write_intermediates: bool
) -> None:
    """``write_intermediates`` asked for them on disk; the cleanup spends them."""
    dumped: list[object] = []
    kept: list[bool] = []
    monkeypatch.setattr(
        store_ingestion, "dump_cached_rasters_to_disk", lambda geo: dumped.append(geo)
    )
    monkeypatch.setattr(
        store_ingestion,
        "cleanup_stable_folder",
        lambda geo, *, keep=False: kept.append(keep) or 0,
    )

    geographic = SimpleNamespace(stable_folder=None)
    ctx = SimpleNamespace(
        cfg=SimpleNamespace(geographic=SimpleNamespace(write_intermediates=write_intermediates)),
        setup=SimpleNamespace(workspace=None, geographic=geographic),
    )

    step_cleanup_preprocessing(ctx)

    assert kept == [write_intermediates]
    assert dumped == ([geographic] if write_intermediates else [])


def test_a_session_that_owns_the_tree_keeps_it_without_dumping_anything(monkeypatch) -> None:
    """``keep=True`` is a lifetime statement, not a request to write rasters."""
    dumped: list[object] = []
    kept: list[bool] = []
    monkeypatch.setattr(
        store_ingestion, "dump_cached_rasters_to_disk", lambda geo: dumped.append(geo)
    )
    monkeypatch.setattr(
        store_ingestion,
        "cleanup_stable_folder",
        lambda geo, *, keep=False: kept.append(keep) or 0,
    )

    geographic = SimpleNamespace(stable_folder=None)
    ctx = SimpleNamespace(
        cfg=SimpleNamespace(geographic=SimpleNamespace(write_intermediates=False)),
        setup=SimpleNamespace(workspace=None, geographic=geographic),
    )

    step_cleanup_preprocessing(ctx, keep=True)

    assert kept == [True]
    assert dumped == []
