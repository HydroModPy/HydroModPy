"""A cached station chronicle keeps its unit and frequency without ``cache.duckdb``.

The disk is the truth and the index is derived. A downloaded chronicle's
sidecar carries its variable, unit, source unit, frequency and period; the
manager reads it before the index row, so deleting ``data/cache.duckdb`` and
indexing the file again from disk alone loses nothing.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.data.provenance.sidecars import sidecar_path_for
from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB
from hydromodpy.data.variables.hydrometry.manager import HydrometryManager

PERIOD = (datetime(2020, 1, 1), datetime(2020, 1, 10))


def _record() -> PointRecord:
    dates = pd.date_range(*PERIOD, freq="D")
    return PointRecord(
        station_id="J1234567",
        variable="hydrometry",
        source="hubeau",
        unit="m3/s",
        frequency="D",
        data=pd.DataFrame({"datetime": dates, "value": range(len(dates))}),
        date_start=PERIOD[0],
        date_end=PERIOD[1],
        source_unit="L/s",
    )


def _manager(catalog: DataCatalogDuckDB, data_dir: Path) -> HydrometryManager:
    return HydrometryManager(config=None, catalog=catalog, project_period=PERIOD, data_dir=data_dir)


def test_the_unit_and_frequency_survive_a_deleted_index(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    data_dir = data_root / "hydrometry"
    index = data_root / "cache.duckdb"

    with DataCatalogDuckDB(index) as catalog:
        _manager(catalog, data_dir)._persist_api_records([_record()], "hubeau")
        entry = catalog.find_cached(variable="hydrometry", source="hubeau", station_id="J1234567")
        chronicle = catalog.resolve_path(entry.file_path, variable="hydrometry")

    payload = json.loads(sidecar_path_for(chronicle).read_text(encoding="utf-8"))
    assert payload["unit"] == "m3/s"
    assert payload["frequency"] == "D"
    assert payload["source_unit"] == "L/s"
    assert payload["variable"] == "hydrometry"
    assert payload["date_start"].startswith("2020-01-01")

    index.unlink()
    with DataCatalogDuckDB(index) as catalog:
        catalog.register(
            variable="hydrometry",
            source="hubeau",
            station_id="J1234567",
            file_path=chronicle,
        )
        cached = _manager(catalog, data_dir)._load_cached_api_record(
            source="hubeau", station_id="J1234567"
        )
        row = catalog.find_cached(variable="hydrometry", source="hubeau", station_id="J1234567")

    assert row.unit is None, "anti-vacuity: the rebuilt row must not know the unit"
    assert cached is not None
    # The record reads as a fresh download does: discharge, not the family name.
    assert cached.variable == "discharge"
    assert cached.unit == "m3/s"
    assert cached.frequency == "D"
    assert cached.source_unit == "L/s"


def _persisted_chronicle(tmp_path: Path) -> tuple[Path, Path]:
    data_root = tmp_path / "data"
    index = data_root / "cache.duckdb"
    with DataCatalogDuckDB(index) as catalog:
        _manager(catalog, data_root / "hydrometry")._persist_api_records([_record()], "hubeau")
        entry = catalog.find_cached(variable="hydrometry", source="hubeau", station_id="J1234567")
        return index, catalog.resolve_path(entry.file_path, variable="hydrometry")


def _index_again_from_disk(index: Path, chronicle: Path) -> dict:
    index.unlink()
    with DataCatalogDuckDB(index) as catalog:
        catalog.register(
            variable="hydrometry", source="hubeau", station_id="J1234567", file_path=chronicle
        )
    return json.loads(sidecar_path_for(chronicle).read_text(encoding="utf-8"))


def test_a_rewritten_file_does_not_inherit_the_old_unit(tmp_path: Path) -> None:
    index, chronicle = _persisted_chronicle(tmp_path)
    chronicle.write_text(chronicle.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    payload = _index_again_from_disk(index, chronicle)

    assert "unit" not in payload
    assert "frequency" not in payload


def test_an_unreadable_sidecar_is_rewritten_without_the_unit(tmp_path: Path) -> None:
    index, chronicle = _persisted_chronicle(tmp_path)
    sidecar_path_for(chronicle).write_text("{not json", encoding="utf-8")

    payload = _index_again_from_disk(index, chronicle)

    assert "unit" not in payload
    assert payload["source"] == "hubeau"


def test_a_file_that_is_no_chronicle_keeps_its_sidecar_keys(tmp_path: Path) -> None:
    raster = tmp_path / "data" / "dem" / "dem_custom_tile.tif"
    raster.parent.mkdir(parents=True)
    raster.write_bytes(b"not really a tiff")

    with DataCatalogDuckDB(tmp_path / "data" / "cache.duckdb") as catalog:
        catalog.register(variable="dem", source="custom", file_path=raster, is_custom=True)

    payload = json.loads(sidecar_path_for(raster).read_text(encoding="utf-8"))
    assert set(payload) == {"bbox", "crs", "fetched_at", "license", "notes", "sha256", "source"}
