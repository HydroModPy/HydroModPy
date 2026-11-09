"""A data request serves under the bounds of the call, workspace or none.

Two games, offline: a registered variable whose source touches no network is
served under offline bounds, with no workspace to hold a cache (the request
engine builds its in-memory store under the bounds of the call); and a source
that declares a host the bounds do not allow is refused before its provider
is contacted, the refusal named in the report of the request.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import pandas as pd
import pytest

from hydromodpy.core.runtime.bounds import Bounds
from hydromodpy.data import DataRequest, DataStore, run_request
from hydromodpy.data.contracts.location import StationLocation
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.data.source.port import FetchRequest, FetchResult


def _station(station_id: str) -> PointRecord:
    dates = pd.date_range("2019-12-01", periods=61, freq="D")
    return PointRecord(
        station_id=station_id,
        variable="hydrometry",
        source="hubeau",
        unit="m3/s",
        frequency="D",
        data=pd.DataFrame({"datetime": dates, "value": range(61)}),
        date_start=dates[0].to_pydatetime(),
        date_end=dates[-1].to_pydatetime(),
        location=StationLocation(id=station_id, x=-1.7, y=48.1, crs="EPSG:4326"),
    )


def _hubeau_stub(hosts: tuple[str, ...]):
    """The class behind the ``("hydrometry", "hubeau")`` key, answered in memory."""

    class _StubHubeau:
        source_id: ClassVar[str] = "hubeau"
        section: ClassVar[str] = "hydrometry"
        payload_kind: ClassVar[str] = "points"
        extent_crs: ClassVar[str] = "EPSG:4326"
        selectors: ClassVar[tuple[str, ...]] = ("extent", "station_ids")
        period_need: ClassVar[str] = "required"
        writes_out_dir: ClassVar[bool] = False

        def __init__(self) -> None:
            self.variables: tuple[str, ...] = ("hydrometry",)
            self.hosts: tuple[str, ...] = hosts
            self.calls: list[FetchRequest] = []

        def fetch(self, request: FetchRequest) -> FetchResult:
            self.calls.append(request)
            return FetchResult(
                source_id=self.source_id,
                kind=self.payload_kind,
                variables=self.variables,
                points=(_station("J0001"),),
            )

    return _StubHubeau


def test_an_integrated_variable_serves_under_offline_bounds_without_a_workspace(
    tmp_path: Path, isolated_registry
) -> None:
    isolated_registry.register(_hubeau_stub(hosts=()), replace=True)
    request = DataRequest.for_variable(
        "hydrometry", station_ids=["J0001"], start="2019-12-01", end="2019-12-31"
    )

    report = run_request(
        request, tmp_path / "out", bounds=Bounds(allowed_hosts=frozenset())
    ).to_document()

    assert report["failures"] == [], report["failures"]
    entry = report["files"][0]
    table = pd.read_parquet(tmp_path / "out" / entry["path"])
    assert len(table) == 31


def test_a_host_the_bounds_do_not_allow_is_refused_without_a_workspace(
    tmp_path: Path, isolated_registry
) -> None:
    isolated_registry.register(_hubeau_stub(hosts=("villain.example.org",)), replace=True)
    request = DataRequest.for_variable(
        "hydrometry", station_ids=["J0001"], start="2019-12-01", end="2019-12-31"
    )
    allowed = Bounds(allowed_hosts=frozenset({"data.geopf.fr"}))

    report = run_request(request, tmp_path / "out", bounds=allowed).to_document()

    assert len(report["failures"]) == 1, report["files"]
    failure = report["failures"][0]
    assert failure["variable"] == "hydrometry"
    message = str(failure["error"])
    assert "villain.example.org" in message, message
    assert "--allow-host" in message, message
    assert report["files"] == [], report["files"]


def test_a_source_whose_hosts_are_allowed_serves_under_the_same_bounds(
    tmp_path: Path, isolated_registry
) -> None:
    isolated_registry.register(_hubeau_stub(hosts=("villain.example.org",)), replace=True)
    request = DataRequest.for_variable(
        "hydrometry", station_ids=["J0001"], start="2019-12-01", end="2019-12-31"
    )
    allowed = Bounds(allowed_hosts=frozenset({"villain.example.org"}))

    report = run_request(request, tmp_path / "out", bounds=allowed).to_document()

    assert report["failures"] == [], report["failures"]
    assert report["files"], "the allowed host serves the variable"


def test_a_store_the_caller_built_keeps_its_own_bounds(tmp_path: Path, isolated_registry) -> None:
    """A store built under bounds keeps them; a request without its own does not lose them."""
    isolated_registry.register(_hubeau_stub(hosts=("villain.example.org",)), replace=True)
    request = DataRequest.for_variable(
        "hydrometry", station_ids=["J0001"], start="2019-12-01", end="2019-12-31"
    )
    store = DataStore(bounds=Bounds(allowed_hosts=frozenset()))

    report = run_request(request, tmp_path / "out", store=store).to_document()

    assert len(report["failures"]) == 1, report["files"]
    assert "villain.example.org" in str(report["failures"][0]["error"])
