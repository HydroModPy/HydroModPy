"""``DataRequest``: the ``installed`` member and the bounds of the description.

A source a third party ships is named in ``installed`` with its options. A name this
installation does not resolve, a shipped source, an unknown or missing option, and a
constructor that refuses its options are all refused or reported by name.
"""

from __future__ import annotations

from typing import ClassVar

import pytest

from hydromodpy.core.exceptions import DataRequestError
from hydromodpy.data.request.model import DataRequest
from hydromodpy.data.source import registry

BOX = {"bbox": [-1.85, 48.05, -1.55, 48.25], "crs": "EPSG:4326"}
NETWORK = {"hydrography": {"sources": [{"source": "bdtopage"}]}}


class AcmeRadarSource:
    """A conforming source a third party ships, named in no file of this tree."""

    source_id: ClassVar[str] = "acme-radar"
    section: ClassVar[str] = "acme-weather"
    payload_kind: ClassVar[str] = "fields"
    extent_crs: ClassVar[str] = "EPSG:3035"
    selectors: ClassVar[tuple[str, ...]] = ("extent",)
    period_need: ClassVar[str] = "required"
    hosts: ClassVar[tuple[str, ...]] = ("radar.acme.example",)
    writes_out_dir: ClassVar[bool] = False

    def __init__(self, *, sweep: str = "long") -> None:
        self.sweep = sweep
        self.variables: tuple[str, ...] = ("radar_rainfall",)

    def fetch(self, request: object) -> None:  # pragma: no cover - never fetched here
        raise AssertionError("this test double is resolved, never run")


def _asking(name: str, **options: object) -> dict:
    return {"installed": [{"name": name, "options": options}], "extent": dict(BOX)}


def test_installed_source_is_accepted(isolated_registry) -> None:
    registry.data_sources.register(AcmeRadarSource)

    request = DataRequest.model_validate(_asking("acme-radar", sweep="short"))

    assert request.installed[0].options == {"sweep": "short"}


def test_unknown_name_is_refused() -> None:
    with pytest.raises(ValueError, match="acme-radar"):
        DataRequest.model_validate(_asking("acme-radar"))


@pytest.mark.parametrize("name", ["bdtopage", "euhydro", "osm"])
def test_shipped_source_is_refused(name: str) -> None:
    with pytest.raises(ValueError, match="ships"):
        DataRequest.model_validate(_asking(name))


def test_unknown_option_is_refused(
    isolated_registry,
) -> None:
    registry.data_sources.register(AcmeRadarSource)

    with pytest.raises(ValueError, match="resolution_m"):
        DataRequest.model_validate(_asking("acme-radar", resolution_m=25))


def test_missing_argument_is_refused(
    isolated_registry,
) -> None:
    class DemandingSource(AcmeRadarSource):
        source_id: ClassVar[str] = "acme-demanding"

        def __init__(self, *, licence_key: str) -> None:
            super().__init__()
            self.licence_key = licence_key

    registry.data_sources.register(DemandingSource)

    with pytest.raises(ValueError, match="licence_key"):
        DataRequest.model_validate(_asking("acme-demanding"))


def test_constructor_refusal_is_reported(isolated_registry, tmp_path) -> None:
    from hydromodpy.data.request.engine import run_request

    class TypedSource(AcmeRadarSource):
        source_id: ClassVar[str] = "acme-typed"

        def __init__(self, *, sweeps: int = 4) -> None:
            self.buffer = [0] * sweeps
            self.variables: tuple[str, ...] = ("radar_rainfall",)

    registry.data_sources.register(TypedSource)
    request = DataRequest.model_validate(_asking("acme-typed", sweeps="four"))

    report = run_request(request, tmp_path / "out")

    (failure,) = report.failures
    assert isinstance(failure.exception, DataRequestError)
    assert "acme-typed" in failure.error


def test_description_is_bounded() -> None:
    schema = DataRequest.model_json_schema()
    assert isinstance(schema["properties"]["installed"]["maxItems"], int)
    with pytest.raises(ValueError):
        DataRequest.model_validate({"data": NETWORK, "extent": {"station_ids": ["A", "A"]}})
