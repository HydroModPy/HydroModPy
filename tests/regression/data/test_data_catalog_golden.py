"""Golden snapshot of DataCatalogDuckDB table contents.

Pins the public side-effects of ``register()``, ``write_artifact()``,
``write_provenance()`` and ``write_failure()`` against a constant
baseline. Any refactor that changes column ordering, sentinel encoding,
or auto-increment IDs must update this snapshot intentionally.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB

pytestmark = pytest.mark.regression


GOLDEN_ENTRIES: list[tuple] = [
    (1, "hydrometry", "hubeau", "ST_A", "station_A.csv", "m3/s", "L/s", 0),
    (2, "hydrometry", "hubeau", "ST_B", "station_B.csv", None, None, 0),
    (3, "precipitation", "sim2", None, "grid.nc", None, None, 0),
]

GOLDEN_ARTIFACTS: list[tuple] = [
    (1, "dem", "/tmp/dem.tif", "a" * 64, 1234, "dem"),
]

GOLDEN_PROVENANCE: list[tuple] = [
    (1, 1, "dem", "ign", "b" * 64, "HTTPClient", "0.5"),
]

GOLDEN_FAILURES: list[tuple] = [
    (1, "piezometry", "hubeau", "NetworkError", "boom"),
]


def _populate(catalog: DataCatalogDuckDB, files: dict) -> None:
    catalog.register(
        variable="hydrometry",
        source="hubeau",
        file_path=files["A"],
        station_id="ST_A",
        date_start=datetime(2020, 1, 1),
        date_end=datetime(2020, 12, 31),
        unit="m3/s",
        source_unit="L/s",
    )
    catalog.register(
        variable="hydrometry",
        source="hubeau",
        file_path=files["B"],
        station_id="ST_B",
        date_start=datetime(2021, 1, 1),
        date_end=datetime(2021, 12, 31),
    )
    catalog.register(
        variable="precipitation",
        source="sim2",
        file_path=files["grid"],
        bbox=(0.0, 43.0, 5.0, 48.0),
        date_start=datetime(2019, 1, 1),
        date_end=datetime(2024, 12, 31),
    )
    aid = catalog.write_artifact(
        artifact_type="dem",
        path="/tmp/dem.tif",
        sha256="a" * 64,
        size_bytes=1234,
        variable="dem",
    )
    catalog.write_provenance(
        artifact_id=aid,
        variable="dem",
        source="ign",
        input_hash="b" * 64,
        tool_name="HTTPClient",
        tool_version="0.5",
        parameters={"bbox": [0, 0, 1, 1]},
    )
    catalog.write_failure(
        variable="piezometry",
        source_ref="hubeau",
        error_type="NetworkError",
        message="boom",
    )


def test_catalog_table_contents_match_golden(tmp_path):
    """Snapshot test pinning the V1 catalog write side effects."""
    db_path = tmp_path / "data" / "cache.duckdb"
    files = {
        "A": tmp_path / "station_A.csv",
        "B": tmp_path / "station_B.csv",
        "grid": tmp_path / "grid.nc",
    }
    for f in files.values():
        f.write_text("payload")

    with DataCatalogDuckDB(db_path) as catalog:
        _populate(catalog, files)

        entries = catalog.connection.execute(
            "SELECT id, variable, source, station_id, file_path, "
            "unit, source_unit, is_custom FROM entries ORDER BY id"
        ).fetchall()
        artifacts = catalog.connection.execute(
            "SELECT id, artifact_type, path, sha256, size_bytes, variable "
            "FROM artifacts ORDER BY id"
        ).fetchall()
        provenance = catalog.connection.execute(
            "SELECT id, artifact_id, variable, source, input_hash, "
            "tool_name, tool_version FROM provenance ORDER BY id"
        ).fetchall()
        failures = catalog.connection.execute(
            "SELECT id, variable, source_ref, error_type, message FROM failures ORDER BY id"
        ).fetchall()

    assert entries == GOLDEN_ENTRIES
    assert artifacts == GOLDEN_ARTIFACTS
    assert provenance == GOLDEN_PROVENANCE
    assert failures == GOLDEN_FAILURES
