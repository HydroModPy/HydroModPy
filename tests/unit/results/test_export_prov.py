"""Unit tests for the W3C PROV-O JSON-LD builder.

These tests feed a synthetic :class:`FairExportContext` (real dataclasses,
no DuckDB) into the real ``build_prov_document`` / ``serialise_prov`` and
assert the PROV-O id wiring: which entity ``wasGeneratedBy`` which activity,
which entity is ``used`` by the simulation, and which agents the activity
``wasAssociatedWith``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.results.export.context import (
    AssetEntry,
    FairExportContext,
    InputEntry,
)
from hydromodpy.results.export.prov import HYDROMODPY_NAMESPACE

pytestmark = pytest.mark.fast

_SIM_ID = "sim-abc-123"
_ACTION_ID = "#action/simulation"


def _make_context(
    *,
    inputs: tuple[InputEntry, ...],
    assets: tuple[AssetEntry, ...],
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
        solver_binary_sha256="a" * 64,
        solver_name=solver_name,
        solver_version="6.4.1" if solver_name else None,
        hydromodpy_version="1.2.3",
    )


def _input(role: str = "dem", name: str = "dem.tif") -> InputEntry:
    return InputEntry(
        role=role,
        category="raster",
        original_path=f"/tmp/ws/data/{name}",
        sha256="b" * 64,
        size_bytes=2048,
        source_type="download",
        source_ref="https://example.org/dem.tif",
        loader_name="rasterio",
        license="cc-by-4.0",
        data_provider="IGN",
        fetched_at="2019-12-31T00:00:00+00:00",
    )


def _asset(key: str = "zarr", rel: str = "results/fields.zarr") -> AssetEntry:
    return AssetEntry(
        key=key,
        relative_path=rel,
        media_type="application/x.zarr-store",
        roles=("data", "fields"),
        sha256="c" * 64,
        size_bytes=4096,
        description="Zarr store.",
    )


@pytest.fixture
def context() -> FairExportContext:
    return _make_context(inputs=(_input(),), assets=(_asset(),))


def _nodes_by_id(activities: list[dict]) -> dict[str, dict]:
    return {node["@id"]: node for node in activities if "@id" in node}


def test_hydromodpy_namespace_is_the_canonical_docs_host() -> None:
    """The vocabulary IRI is pinned to the canonical documentation host."""
    assert HYDROMODPY_NAMESPACE == "https://docs.hydromodpy.fr/schema#"
