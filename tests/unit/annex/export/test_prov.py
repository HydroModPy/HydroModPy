"""PROV document of a run: JSON-LD context, activity graph, and the export view that writes it."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hydromodpy.results.export.context import (
    AssetEntry,
    FairExportContext,
    InputEntry,
)
from hydromodpy.results.export.prov import HYDROMODPY_NAMESPACE
from hydromodpy.results.exporters.port import RUN_VIEW, ExportWriter
from hydromodpy_annex.export.prov import PROV_CONTEXT, ProvView, serialise_prov

pytestmark = pytest.mark.fast

_SIM_ID = "sim-abc-123"
_ACTION_ID = "#action/simulation"


def _make_context(
    *,
    inputs: tuple[InputEntry, ...] = (),
    assets: tuple[AssetEntry, ...] = (),
    solver_name: str | None = "modflow6",
    creator_name: str | None = "Jane Doe",
) -> FairExportContext:
    return FairExportContext(
        sim_id=_SIM_ID,
        sim_row={
            "sim_id": _SIM_ID,
            "project": "demo",
            "started_at": "2020-01-01T00:00:00+00:00",
            "ended_at": "2020-01-01T01:00:00+00:00",
        },
        runs_env={
            "hostname": "node-01",
            "git_commit": "deadbeef",
            "rng_seed": 7,
        },
        workspace_meta={},
        workspace_path=Path("/tmp/ws"),
        license_url="https://creativecommons.org/licenses/by/4.0/",
        creator_name=creator_name,
        creator_email="jane@example.org" if creator_name else None,
        assets=assets,
        inputs=inputs,
        lockfile_path=None,
        solver_binary_sha256="aa" * 32,
        solver_name=solver_name,
        solver_version="6.4.1",
        hydromodpy_version="2.0.0-test",
    )


@pytest.fixture
def context() -> FairExportContext:
    return _make_context(
        inputs=(
            InputEntry(
                role="dem",
                category="spatial",
                original_path="dem.tif",
                sha256="11" * 32,
                size_bytes=1024,
                source_type="file",
                source_ref=None,
                license="CC-BY-4.0",
                data_provider="IGN",
                loader_name="dem_loader",
                fetched_at="2020-01-01T00:00:00Z",
            ),
        ),
        assets=(
            AssetEntry(
                key="head",
                relative_path="head.nc",
                media_type="application/x-netcdf",
                roles=("model_output",),
                sha256="22" * 32,
                size_bytes=2048,
                description="Simulated heads.",
            ),
        ),
    )


def test_context_namespaces() -> None:
    assert PROV_CONTEXT["hydromodpy"] == HYDROMODPY_NAMESPACE
    assert PROV_CONTEXT["prov"] == "http://www.w3.org/ns/prov#"


def test_document_is_json(context: FairExportContext) -> None:
    doc = serialise_prov(context)
    parsed = json.loads(json.dumps(doc))
    assert parsed["@context"]["prov"] == "http://www.w3.org/ns/prov#"
    assert parsed["@graph"][0]["@type"] == ["CreateAction", "prov:Activity"]


def test_view_members_and_protocol() -> None:
    view = ProvView()
    assert isinstance(view, ExportWriter)
    assert view.name == "prov"
    assert view.suffix == ".jsonld"
    assert RUN_VIEW in view.writes
    assert view.natural == ()
    assert view.instants == "many"
    assert view.reprojects is False
    assert view.help
