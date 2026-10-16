"""Every file that leaves a run carries the identity block of that run.

The run is sealed by the run store (three monthly periods on four Lambert-93
cells, a head field, a discharge series, the catchment outline, the budget),
indexed, and read through the catalog. Each export format is opened as a
reader would open it and the block is looked for in it: the GeoPackage in its
``gpkg_metadata`` table, every other export in its ``.meta.json`` sidecar, the
CSV also in its ``site`` and ``case_id`` columns, the NetCDF also in its
global attributes, a figure in its PNG text chunk, the Zarr store in its root
attributes and every Parquet table in its schema metadata.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from hydromodpy.core.config_kit.export_spec import ExportRequest
from hydromodpy.display.config import DisplayConfig
from hydromodpy.display.runs import figures_dir_of, render_figures_for_run
from hydromodpy.results.catalog import Catalog
from hydromodpy.results.exporters.request import export_run
from hydromodpy.results.identity import ZARR_IDENTITY_ATTR, Identity, read_identity_from
from hydromodpy.results.ledger import Ledger
from tests._helpers.sealed_run import RUN_NAME, seal_demo_run

REQUESTS = {
    "csv": {"variables": "discharge"},
    "budget_csv": {"variables": "budget"},
    "netcdf": {"variables": "head"},
    "geotiff": {"variables": "head", "time": "2000-02-15"},
    "geopackage_field": {"variables": "head", "time": "first", "format": "geopackage"},
    "geopackage_layer": {"variables": "watershed"},
    "shapefile": {"variables": "head", "time": "first", "format": "shapefile"},
    "vtu": {"variables": "head", "time": "first", "format": "vtu"},
}


@pytest.fixture(scope="module")
def exported(tmp_path_factory) -> tuple[Path, dict[str, list[Path]], list[Path]]:
    project = tmp_path_factory.mktemp("identity") / "project"
    run_dir, sim_id = seal_demo_run(project)
    written: dict[str, list[Path]] = {}
    with Catalog(project) as catalog:
        for key, payload in REQUESTS.items():
            written[key] = export_run(catalog, sim_id, ExportRequest.model_validate(payload))
        report = render_figures_for_run(
            catalog[sim_id],
            DisplayConfig(figures=["water_budget"]),
            output_dir=figures_dir_of(run_dir),
        )
    return run_dir, written, list(report.written)


def _sim_id(run_dir: Path) -> str:
    from hydromodpy.results.outcome import read_outcome

    return read_outcome(run_dir).sim_id


def _identity(run_dir: Path) -> Identity:
    identity = read_identity_from(run_dir / "fields.zarr")
    assert identity is not None
    return identity


@pytest.mark.parametrize("key", sorted(REQUESTS))
def test_each_export_format_carries_the_block(exported, key) -> None:
    run_dir, written, _figures = exported
    assert written[key]
    for path in written[key]:
        found = read_identity_from(path)
        assert found is not None, path.name
        assert found.sim_id == _sim_id(run_dir)
        assert found.case_id == RUN_NAME


def test_a_geopackage_holds_the_block_in_its_metadata_table(exported) -> None:
    import sqlite3

    run_dir, written, _figures = exported
    (gpkg,) = written["geopackage_layer"]
    assert not gpkg.with_name(gpkg.name + ".meta.json").exists()
    with sqlite3.connect(gpkg) as connection:
        (payload,) = connection.execute("SELECT metadata FROM gpkg_metadata").fetchone()
    assert Identity.from_json(payload).sim_id == _sim_id(run_dir)


def test_every_csv_row_names_its_site_and_case(exported) -> None:
    run_dir, written, _figures = exported
    for path in written["csv"] + written["budget_csv"]:
        frame = pd.read_csv(path)
        assert list(frame.columns[:2]) == ["site", "case_id"]
        assert set(frame["case_id"]) == {RUN_NAME}


def test_a_netcdf_carries_the_block_in_its_global_attributes(exported) -> None:
    import xarray as xr

    run_dir, written, _figures = exported
    (netcdf,) = written["netcdf"]
    with xr.open_dataset(netcdf) as dataset:
        assert Identity.from_json(dataset.attrs[ZARR_IDENTITY_ATTR]).sim_id == _sim_id(run_dir)


def test_every_export_is_recorded_in_the_ledger(exported) -> None:
    run_dir, written, _figures = exported
    exports = run_dir / "exports"
    recorded = {entry.file for entry in Ledger.read(exports).entries}
    files = {path.relative_to(exports).as_posix() for paths in written.values() for path in paths}
    assert recorded == files


def test_a_figure_carries_the_block_and_its_ledger_entry(exported) -> None:
    run_dir, _written, figures = exported
    assert figures
    ledger = Ledger.read(figures_dir_of(run_dir))
    for path in figures:
        found = read_identity_from(path)
        assert found is not None
        assert found.sim_id == _sim_id(run_dir)
        assert ledger.entry_for(path.name) is not None


def test_the_field_store_and_the_tables_carry_the_block(exported) -> None:
    run_dir, _written, _figures = exported
    assert _identity(run_dir).sim_id == _sim_id(run_dir)
    tables = sorted((run_dir / "tables.parquet").glob("*.parquet"))
    assert tables
    for table in tables:
        found = read_identity_from(table)
        assert found is not None, table.name
        assert found.sim_id == _sim_id(run_dir)
