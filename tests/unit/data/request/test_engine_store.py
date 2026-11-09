"""A request without a store caches in the scratch of its call, never in the user cache."""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.data import DataRequest, run_request
from hydromodpy.data.request import engine


def _spy_on_the_store(monkeypatch: pytest.MonkeyPatch) -> list:
    stores: list = []

    def serve(variable, section, *, store, **_kwargs):
        stores.append(store)
        return []

    monkeypatch.setattr(engine, "_serve_section", serve)
    return stores


def _request() -> DataRequest:
    return DataRequest.for_variable(
        "hydrometry", station_ids=["J0001"], start="2020-01-01", end="2020-01-31"
    )


def test_the_default_store_has_a_data_folder_in_the_scratch_of_the_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HMP_CACHE_HOME", str(tmp_path / "user-cache"))
    stores = _spy_on_the_store(monkeypatch)

    run_request(_request(), tmp_path / "out")

    (store,) = stores
    assert store.data_root is not None
    assert store.data_root.name == "data"
    assert store.index.data_root == store.data_root
    assert not (tmp_path / "user-cache").exists()
    assert tmp_path not in store.data_root.parents, "the scratch is the temporary folder"


def test_the_scratch_goes_with_the_call(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stores = _spy_on_the_store(monkeypatch)

    run_request(_request(), tmp_path / "out")

    (store,) = stores
    assert not store.data_root.exists()


def test_a_store_that_is_given_is_the_one_used(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hydromodpy.data import DataStore

    stores = _spy_on_the_store(monkeypatch)
    mine = DataStore(data_root=tmp_path / "mine" / "data")

    run_request(_request(), tmp_path / "out", store=mine)

    assert stores == [mine]
