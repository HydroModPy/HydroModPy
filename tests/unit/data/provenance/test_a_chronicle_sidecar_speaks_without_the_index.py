"""A cached station chronicle keeps its unit and frequency in its sidecar alone.

The disk is the truth. A downloaded chronicle's sidecar carries its variable,
unit, source unit, frequency and period, so a new index read from the disk
alone gives the record back as it was fetched.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.data.provenance.sidecars import CacheIndex, sidecar_path_for
from hydromodpy.data.variables.hydrometry.variable import HydrometryVariable

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


def _variable(index: CacheIndex, data_dir: Path) -> HydrometryVariable:
    return HydrometryVariable(config=None, index=index, project_period=PERIOD, data_dir=data_dir)


def _persisted_chronicle(tmp_path: Path) -> tuple[Path, Path]:
    data_root = tmp_path / "data"
    index = CacheIndex(data_root)
    _variable(index, data_root / "hydrometry")._persist_api_records([_record()], "hubeau")
    row = index.find("hydrometry", "hubeau", station_id="J1234567")
    assert row is not None
    return data_root, row.path


def test_the_unit_and_frequency_survive_a_new_index(tmp_path: Path) -> None:
    data_root, chronicle = _persisted_chronicle(tmp_path)

    payload = json.loads(sidecar_path_for(chronicle).read_text(encoding="utf-8"))
    assert payload["unit"] == "m3/s"
    assert payload["frequency"] == "D"
    assert payload["source_unit"] == "L/s"
    assert payload["variable"] == "hydrometry"
    assert payload["station_id"] == "J1234567"
    assert payload["date_start"].startswith("2020-01-01")

    fresh = CacheIndex(data_root)
    cached = _variable(fresh, data_root / "hydrometry")._load_cached_api_record(
        source="hubeau", station_id="J1234567"
    )

    assert cached is not None
    # The record reads as a fresh download does: discharge, not the family name.
    assert cached.variable == "discharge"
    assert cached.unit == "m3/s"
    assert cached.frequency == "D"
    assert cached.source_unit == "L/s"


def _record_again(data_root: Path, chronicle: Path) -> dict:
    CacheIndex(data_root).record(
        chronicle, variable="hydrometry", source="hubeau", station_id="J1234567"
    )
    return json.loads(sidecar_path_for(chronicle).read_text(encoding="utf-8"))


def test_a_record_of_the_same_bytes_keeps_the_unit(tmp_path: Path) -> None:
    data_root, chronicle = _persisted_chronicle(tmp_path)

    payload = _record_again(data_root, chronicle)

    assert payload["unit"] == "m3/s"
    assert payload["frequency"] == "D"


def test_a_rewritten_file_does_not_inherit_the_old_unit(tmp_path: Path) -> None:
    data_root, chronicle = _persisted_chronicle(tmp_path)
    chronicle.write_text(chronicle.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    payload = _record_again(data_root, chronicle)

    assert "unit" not in payload
    assert "frequency" not in payload


def test_an_unreadable_sidecar_is_rewritten_without_the_unit(tmp_path: Path) -> None:
    data_root, chronicle = _persisted_chronicle(tmp_path)
    sidecar_path_for(chronicle).write_text("{not json", encoding="utf-8")

    payload = _record_again(data_root, chronicle)

    assert "unit" not in payload
    assert payload["source"] == "hubeau"


def test_a_file_that_is_no_chronicle_keeps_its_sidecar_keys(tmp_path: Path) -> None:
    raster = tmp_path / "data" / "dem" / "dem_ign_tile.tif"
    raster.parent.mkdir(parents=True)
    raster.write_bytes(b"not really a tiff")

    CacheIndex(tmp_path / "data").record(raster, variable="dem", source="ign")

    payload = json.loads(sidecar_path_for(raster).read_text(encoding="utf-8"))
    assert set(payload) == {
        "bbox",
        "bytes",
        "crs",
        "fetched_at",
        "license",
        "notes",
        "sha256",
        "source",
        "variable",
    }
