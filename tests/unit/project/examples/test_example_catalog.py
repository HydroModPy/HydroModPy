"""The shipped example catalog, and the guarantee that it cannot drift."""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.project.examples.generate import build_catalog, repo_root
from hydromodpy.project.examples.manifest import (
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


def test_regenerating_the_manifest_reproduces_the_committed_bytes() -> None:
    """A drift between the repository and the shipped catalog fails here."""
    regenerated = render_catalog(build_catalog(repo_root()))
    assert regenerated == catalog_path().read_text(encoding="utf-8"), (
        "hydromodpy/project/examples/catalog.toml is stale. Run `python -m tools.dev examples manifest`."
    )


def test_load_rejects_another_schema_version(tmp_path: Path) -> None:
    other = tmp_path / "catalog.toml"
    other.write_text(f"schema_version = {SCHEMA_VERSION + 1}\n", encoding="utf-8")
    with pytest.raises(FileNotFoundError, match="schema_version"):
        load_catalog(other)


def test_unknown_id_names_the_ids_that_exist() -> None:
    with pytest.raises(FileNotFoundError, match="This build ships: 04"):
        find_entry("99", load_catalog())
