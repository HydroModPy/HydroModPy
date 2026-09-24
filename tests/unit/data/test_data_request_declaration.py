"""What the ``data-request`` declaration promises, held against what it serves.

Two of its members are derived rather than written: the hosts it may reach
and the document it reads. Each is compared here to what it was derived from,
and the ``installed`` member is held to its refusals.
"""

from __future__ import annotations

import json
from importlib.resources import files
from typing import ClassVar

import pytest

from hydromodpy.core.exceptions import DataRequestError
from hydromodpy.data.request.job import DATA_REQUEST, REACHED_HOSTS
from hydromodpy.data.request.model import DataRequest
from hydromodpy.data.source import registry
from hydromodpy.schema.capability import HOST_PATTERN
from hydromodpy.schema.sources import source_entry

BOX = {"bbox": [-1.85, 48.05, -1.55, 48.25], "crs": "EPSG:4326"}
NETWORK = {"hydrography": {"sources": [{"source": "bdtopage"}]}}


def _served_slugs() -> set[str]:
    """Every source a [data] section reaches: the managers' tables and the port."""
    from hydromodpy.data.loading._dispatch import VARIABLE_SPECS, get_manager_class

    slugs = {key for name in VARIABLE_SPECS for key in get_manager_class(name).SOURCES}
    return slugs | set(registry.builtin_source_ids())


def test_the_declared_hosts_are_the_hosts_of_the_served_sources() -> None:
    served = set()
    for slug in _served_slugs():
        entry = source_entry(slug)
        assert entry is not None, f"{slug!r} is served and has no entry in schema/sources.py"
        served |= set(entry.hosts)
    assert set(REACHED_HOSTS) == served
    assert DATA_REQUEST.reaches_network == REACHED_HOSTS


def test_every_declared_host_is_a_bare_host_name() -> None:
    import re

    assert all(re.fullmatch(HOST_PATTERN, host) for host in REACHED_HOSTS)


def test_the_published_inputs_are_the_members_of_the_request() -> None:
    document = json.loads(
        files("hydromodpy.schema.processes").joinpath("data-request@1.json").read_text("utf-8")
    )
    schema = DataRequest.model_json_schema()
    assert set(document["inputs"]) == set(schema["properties"])
    required = {name for name, entry in document["inputs"].items() if entry["minOccurs"] == 1}
    assert required == set(schema.get("required", ()))


def test_the_report_is_the_only_artefact_every_run_writes() -> None:
    payload = [output for output in DATA_REQUEST.outputs if output.path.startswith("outputs/")]
    assert [output.path for output in payload] == ["outputs/request.json"]


class AcmeRadarSource:
    """A conforming source a third party ships, named in no file of this tree."""

    source_id: ClassVar[str] = "acme-radar"
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


def test_a_request_names_a_source_this_repository_does_not_name(isolated_registry) -> None:
    registry.register(AcmeRadarSource)

    request = DataRequest.model_validate(_asking("acme-radar", sweep="short"))

    assert request.installed[0].options == {"sweep": "short"}


def test_installing_a_source_does_not_move_what_the_build_declares(isolated_registry) -> None:
    before = tuple(REACHED_HOSTS)
    registry.register(AcmeRadarSource)

    assert tuple(REACHED_HOSTS) == before
    assert "radar.acme.example" not in DATA_REQUEST.reaches_network


def test_a_name_this_installation_does_not_resolve_is_refused() -> None:
    with pytest.raises(ValueError, match="acme-radar"):
        DataRequest.model_validate(_asking("acme-radar"))


@pytest.mark.parametrize("name", ["bdtopage", "euhydro", "osm"])
def test_a_shipped_source_is_refused_through_installed(name: str) -> None:
    with pytest.raises(ValueError, match="ships"):
        DataRequest.model_validate(_asking(name))


def test_an_option_the_installed_source_cannot_take_is_refused_by_name(
    isolated_registry,
) -> None:
    registry.register(AcmeRadarSource)

    with pytest.raises(ValueError, match="resolution_m"):
        DataRequest.model_validate(_asking("acme-radar", resolution_m=25))


def test_an_argument_the_installed_source_demands_is_refused_when_missing(
    isolated_registry,
) -> None:
    class DemandingSource(AcmeRadarSource):
        source_id: ClassVar[str] = "acme-demanding"

        def __init__(self, *, licence_key: str) -> None:
            super().__init__()
            self.licence_key = licence_key

    registry.register(DemandingSource)

    with pytest.raises(ValueError, match="licence_key"):
        DataRequest.model_validate(_asking("acme-demanding"))


def test_a_constructor_that_refuses_its_options_is_a_fault_of_the_request(
    isolated_registry, tmp_path
) -> None:
    from hydromodpy.data import run_request

    class TypedSource(AcmeRadarSource):
        source_id: ClassVar[str] = "acme-typed"

        def __init__(self, *, sweeps: int = 4) -> None:
            self.buffer = [0] * sweeps
            self.variables: tuple[str, ...] = ("radar_rainfall",)

    registry.register(TypedSource)
    request = DataRequest.model_validate(_asking("acme-typed", sweeps="four"))

    report = run_request(request, tmp_path / "out")

    (failure,) = report.failures
    assert isinstance(failure.exception, DataRequestError)
    assert "acme-typed" in failure.error


def test_a_request_bounds_what_a_description_must_count() -> None:
    schema = DataRequest.model_json_schema()
    assert isinstance(schema["properties"]["installed"]["maxItems"], int)
    with pytest.raises(ValueError):
        DataRequest.model_validate({"data": NETWORK, "extent": {"station_ids": ["A", "A"]}})
