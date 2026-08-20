"""LakeAbacusManager.load(): emits a TableRecord and registers it once.

Guards that the abacus manager returns the new TableRecord
contract on ``LoadResult.tables`` (not points/fields) and registers the
Path-backed pivot in the catalog exactly once.
"""

from __future__ import annotations

from hydromodpy.data.contracts import TableRecord
from hydromodpy.data.variables.lake_abacus.config import LakeAbacusConfig
from hydromodpy.data.variables.lake_abacus.manager import LakeAbacusManager


class _RecordingCatalog:
    def __init__(self) -> None:
        self.registrations: list[dict] = []

    def register(self, **kwargs) -> int:
        self.registrations.append(kwargs)
        return len(self.registrations)


def test_load_emits_table_record_and_registers_once(tmp_path) -> None:
    src = tmp_path / "lake_abacus_custom_lac0.csv"
    src.write_text(
        "stage,volume,sarea\n85.0,0.0,0.0\n90.0,1.0e6,4.0e5\n",
        encoding="utf-8",
    )
    data_dir = tmp_path / "lake_abacus"
    data_dir.mkdir()

    config = LakeAbacusConfig.from_csv(src, lake_id="lac0")
    catalog = _RecordingCatalog()
    manager = LakeAbacusManager(config=config, catalog=catalog, data_dir=data_dir)

    result = manager.load()

    assert result.has_tables is True
    assert not result.has_points
    assert not result.has_fields
    assert len(result.tables) == 1

    rec = result.tables[0]
    assert isinstance(rec, TableRecord)
    assert rec.variable == "lake_abacus"
    assert rec.table_id == "lac0"
    assert rec.is_file_reference is True

    # The validated Parquet pivot round-trips through the record frame.
    frame = rec.frame
    assert frame["lake_id"].unique().tolist() == ["lac0"]
    assert frame["stage"].tolist() == [85.0, 90.0]

    assert len(catalog.registrations) == 1
    reg = catalog.registrations[0]
    assert reg["variable"] == "lake_abacus"
    assert reg["source"] == "custom"
    assert reg["is_custom"] is True
    assert reg["station_id"] == "lac0"
