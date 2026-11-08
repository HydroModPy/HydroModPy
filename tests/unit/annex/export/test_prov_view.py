"""Unit tests for the PROV view helpers and ``ProvView`` in the annex."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hydromodpy.results.export.context import (
    AssetEntry,
    FairExportContext,
    InputEntry,
)
from hydromodpy.results.export.prov import (
    HYDROMODPY_NAMESPACE,
    build_prov_document,
)
from hydromodpy.results.exporters.port import RUN_VIEW, ExportWriter
from hydromodpy.schema.generated_views import PROV_VIEW_FILENAME
from hydromodpy_annex.export.prov import (
    PROV_CONTEXT,
    ProvView,
    serialise_prov,
    write_prov,
    write_prov_view,
)

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
    """Build a fully synthetic context with one run row and env."""
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


def test_prov_context_contains_hydromodpy_namespace() -> None:
    """The PROV context points at the documentation schema IRI."""
    assert PROV_CONTEXT["hydromodpy"] == HYDROMODPY_NAMESPACE
    assert PROV_CONTEXT["prov"] == "http://www.w3.org/ns/prov#"


def test_serialise_prov_graph_head_is_action(context: FairExportContext) -> None:
    """serialise_prov wraps the doc with PROV context and puts the action first."""
    doc = serialise_prov(context)
    assert doc["@context"] == PROV_CONTEXT
    graph = doc["@graph"]
    assert isinstance(graph, list)
    assert graph[0]["@id"] == _ACTION_ID

    built = build_prov_document(context)
    assert len(graph) == 1 + len(built["activities"])
    graph_ids = {node["@id"] for node in graph if "@id" in node}
    for node in built["activities"]:
        assert node["@id"] in graph_ids


def test_serialise_prov_is_json_serialisable(context: FairExportContext) -> None:
    """The full document round-trips through json without custom encoders."""
    doc = serialise_prov(context)
    parsed = json.loads(json.dumps(doc))
    assert parsed["@context"]["prov"] == "http://www.w3.org/ns/prov#"
    assert parsed["@graph"][0]["@type"] == ["CreateAction", "prov:Activity"]


def test_prov_view_members_and_protocol() -> None:
    """ProvView declares the ExportWriter members on the export port."""
    view = ProvView()
    assert isinstance(view, ExportWriter)
    assert view.name == "prov"
    assert view.suffix == ".jsonld"
    assert RUN_VIEW in view.writes
    assert view.natural == ()
    assert view.instants == "many"
    assert view.reprojects is False
    assert view.help


def test_write_prov_and_view(tmp_path: Path, context: FairExportContext) -> None:
    """write_prov and write_prov_view write the jsonld document."""
    from tests._helpers.run_records import make_record

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    make_record().write(run_dir)

    out_file = write_prov(context, tmp_path / "out.jsonld")
    assert out_file.is_file()
    assert json.loads(out_file.read_text(encoding="utf-8"))["@context"]["prov"]

    out_view = write_prov_view(run_dir)
    assert out_view == run_dir / PROV_VIEW_FILENAME
    assert out_view.is_file()

    view = ProvView()
    written = view.write(None, None, run_dir)
    assert written == [run_dir / PROV_VIEW_FILENAME]


def test_prov_view_refuses_variable_and_time_selectors(isolated_export_formats) -> None:
    from pydantic import ValidationError

    from hydromodpy.results.exporters.export_spec import ExportRequest

    isolated_export_formats.register(ProvView)
    with pytest.raises(ValidationError, match='Write variables = "all"'):
        ExportRequest(variables="head", format="prov")
    with pytest.raises(ValidationError, match="time selects nothing"):
        ExportRequest(variables="all", format="prov", time="last")
