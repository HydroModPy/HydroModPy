"""What a sidecar records when a file is registered in the cache index.

The disk is the truth. A chronicle's sidecar keeps its variable, unit (m3/s), source unit (L/s),
frequency and period, so a new index read from the disk alone gives the record back. The licence
comes from the source registry, a licence given by the caller wins, and a sidecar goes with its file.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from hydromodpy.core.exceptions import DataCacheError
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.data.provenance import sidecars
from hydromodpy.data.provenance.sidecars import (
    CacheIndex,
    Sidecar,
    data_path_for_sidecar,
    load_sidecar,
    sidecar_path_for,
)
from hydromodpy.data.variables.hydrometry.variable import HydrometryVariable

PERIOD = (datetime(2020, 1, 1), datetime(2020, 1, 10))


def _discharge() -> PointRecord:
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
    _variable(index, data_root / "hydrometry")._persist_api_records([_discharge()], "hubeau")
    row = index.find("hydrometry", "hubeau", station_id="J1234567")
    assert row is not None
    return data_root, row.path


def _record_again(data_root: Path, chronicle: Path) -> dict:
    CacheIndex(data_root).record(
        chronicle, variable="hydrometry", source="hubeau", station_id="J1234567"
    )
    return json.loads(sidecar_path_for(chronicle).read_text(encoding="utf-8"))


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


def test_the_same_bytes_keep_the_unit(tmp_path: Path) -> None:
    data_root, chronicle = _persisted_chronicle(tmp_path)

    payload = _record_again(data_root, chronicle)

    assert payload["unit"] == "m3/s"
    assert payload["frequency"] == "D"


def _rewritten(chronicle: Path) -> None:
    chronicle.write_text(chronicle.read_text(encoding="utf-8") + "\n", encoding="utf-8")


def _unreadable_sidecar(chronicle: Path) -> None:
    sidecar_path_for(chronicle).write_text("{not json", encoding="utf-8")


@pytest.mark.parametrize(
    "damage",
    [
        pytest.param(_rewritten, id="rewritten file"),
        pytest.param(_unreadable_sidecar, id="unreadable sidecar"),
    ],
)
def test_the_old_unit_is_not_inherited(tmp_path: Path, damage) -> None:
    data_root, chronicle = _persisted_chronicle(tmp_path)
    damage(chronicle)

    payload = _record_again(data_root, chronicle)

    assert "unit" not in payload
    assert payload["source"] == "hubeau"
    assert "frequency" not in payload


def _geology_file(tmp_path: Path) -> Path:
    path = tmp_path / "data" / "geology" / "geology.gpkg"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"geology")
    return path


def _record_geology(path: Path, source: str, **fields: object) -> Sidecar:
    CacheIndex(path.parents[1]).record(path, variable="geology", source=source, **fields)
    return load_sidecar(path)


def test_a_given_licence_wins(tmp_path: Path) -> None:
    sidecar = _record_geology(_geology_file(tmp_path), "url", license="CC-BY-4.0")

    assert sidecar.license == "CC-BY-4.0"


def test_a_sidecar_that_cannot_be_written_leaves_no_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The sidecar is the row: a record whose sidecar is not written is no record.
    def refuse(*args: object, **kwargs: object) -> None:
        raise OSError("read-only folder")

    path = _geology_file(tmp_path)
    index = CacheIndex(tmp_path / "data")
    monkeypatch.setattr(sidecars, "write_sidecar", refuse)
    with pytest.raises(OSError, match="read-only"):
        index.record(path, variable="geology", source="brgm_1m")
    assert index.rows() == []
    assert not sidecar_path_for(path).exists()


def test_a_user_file_is_no_row_of_the_cache(tmp_path: Path) -> None:
    with pytest.raises(DataCacheError, match="user file"):
        _record_geology(_geology_file(tmp_path), "file")


@pytest.mark.parametrize("name", ["foo.json", "foo.v1.2.json", "foo.gpkg", "foo.gpkg.bak"])
def test_other_names_are_not_sidecars(name: str) -> None:
    assert data_path_for_sidecar(Path("/d") / name) is None
