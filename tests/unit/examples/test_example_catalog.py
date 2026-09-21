"""The shipped example catalog, and the guarantee that it cannot drift."""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.examples.generate import WHITELIST, build_catalog, repo_root
from hydromodpy.examples.manifest import (
    SCHEMA_VERSION,
    catalog_path,
    find_entry,
    load_catalog,
    render_catalog,
)

EXPECTED_DATA_FILES = {
    "data/dem/DEM_armorican_massif.tif",
    "data/hydrography/nancon_stream_network.gpkg",
    "data/hydrometry/hydrometry_custom_NANCON_19820201_20220125_D.csv",
    "data/recharge/recharge_custom_NANCON_20000101_20021231_M.csv",
    "data/recharge/recharge_custom_NANCON_REA_19900101_20201231_D.csv",
    "data/runoff/runoff_custom_NANCON_20000101_20021231_M.csv",
    "data/runoff/runoff_custom_NANCON_REA_19900101_20201231_D.csv",
}


def test_catalog_ships_beside_the_module() -> None:
    """The manifest is package data, so `hmp example list` works offline."""
    assert catalog_path().is_file()
    assert catalog_path().parent.name == "examples"


def test_catalog_holds_exactly_the_whitelist() -> None:
    entries = load_catalog()
    assert [entry.id for entry in entries] == [spec.id for spec in WHITELIST]
    assert len(entries) == 1, "the whitelist ships one verified example, see generate.py"


def test_example_04_names_the_seven_data_files_it_reads() -> None:
    entry = find_entry("04", load_catalog())
    assert {item.dest for item in entry.data} == EXPECTED_DATA_FILES
    steps = {f"step{n}" for n in range(1, 6)}
    shipped = {Path(item.dest).stem.split("_")[0] for item in entry.files}
    assert steps <= shipped
    assert entry.entry_config == "step1_minimal.toml"


def test_every_entry_writes_only_under_the_workspace() -> None:
    for entry in load_catalog():
        for item in entry.payload:
            assert not item.dest.startswith("/")
            assert ".." not in Path(item.dest).parts
            assert item.size > 0
            assert len(item.sha256) == 64


def test_the_dem_dominates_the_payload() -> None:
    """The reason the cache is keyed by file and not by example."""
    entry = find_entry("04", load_catalog())
    dem = next(item for item in entry.data if item.dest.endswith("DEM_armorican_massif.tif"))
    assert dem.size / entry.total_size > 0.9


def test_regenerating_the_manifest_reproduces_the_committed_bytes() -> None:
    """A drift between the repository and the shipped catalog fails here."""
    regenerated = render_catalog(build_catalog(repo_root()))
    assert regenerated == catalog_path().read_text(encoding="utf-8"), (
        "hydromodpy/examples/catalog.toml is stale. Run `hmp dev examples manifest`."
    )


def test_load_rejects_another_schema_version(tmp_path: Path) -> None:
    other = tmp_path / "catalog.toml"
    other.write_text(f"schema_version = {SCHEMA_VERSION + 1}\n", encoding="utf-8")
    with pytest.raises(FileNotFoundError, match="schema_version"):
        load_catalog(other)


def test_unknown_id_names_the_ids_that_exist() -> None:
    with pytest.raises(FileNotFoundError, match="This build ships: 04"):
        find_entry("99", load_catalog())
