"""A request without a store caches in the scratch of its call, never in the user cache."""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.data.request import engine
from hydromodpy.data.request.engine import run_request
from hydromodpy.data.request.model import DataRequest


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


def test_the_scratch_goes_with_the_call(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stores = _spy_on_the_store(monkeypatch)

    run_request(_request(), tmp_path / "out")

    (store,) = stores
    assert not store.data_root.exists()
