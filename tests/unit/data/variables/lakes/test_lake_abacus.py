"""Lake abacus (stage m, volume m3, surface area m2) read in place from a CSV file."""

from __future__ import annotations

from hydromodpy.data.contracts.table import TableRecord
from hydromodpy.data.provenance.sidecars import CacheIndex, sidecar_path_for
from hydromodpy.data.variables.lake_abacus.config import LakeAbacusConfig
from hydromodpy.data.variables.lake_abacus.variable import LakeAbacusVariable


def test_load_emits_a_table_record_and_no_cache_row(tmp_path) -> None:
    src = tmp_path / "lake_abacus_custom_lac0.csv"
    src.write_text("stage,volume,sarea\n85.0,0.0,0.0\n90.0,1.0e6,4.0e5\n", encoding="utf-8")
    data_dir = tmp_path / "lake_abacus"
    data_dir.mkdir()
    index = CacheIndex(tmp_path)
    variable = LakeAbacusVariable(
        config=LakeAbacusConfig.from_csv(src, lake_id="lac0"), index=index, data_dir=data_dir
    )

    result = variable.load()

    assert result.has_tables
    assert not result.has_points
    assert not result.has_fields
    (record,) = result.tables
    assert isinstance(record, TableRecord)
    assert record.variable == "lake_abacus"
    assert record.table_id == "lac0"
    assert record.is_file_reference
    # The validated Parquet pivot round-trips through the record frame.
    assert record.frame["lake_id"].unique().tolist() == ["lac0"]
    assert record.frame["stage"].tolist() == [85.0, 90.0]
    # A user file is no row of the data cache, and nothing writes a sidecar beside it.
    assert index.rows() == []
    assert not sidecar_path_for(src).exists()
