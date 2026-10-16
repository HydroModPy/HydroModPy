"""The data exports of a run read its directory: a run store exports without the index.

The export step writes the ``[[export]]`` blocks with the store of the run,
before the index knows the run. The names a run can export, the layers of
its mesh and the default resolution of a GeoTIFF are read from the run
directory, so the export succeeds while ``Catalog`` cannot be opened.
"""

from __future__ import annotations

import pytest

from hydromodpy.core.config_kit.export_spec import ExportKind, load_export_requests
from hydromodpy.results.catalog import Catalog
from hydromodpy.results.exporters.request import export_data_requests
from hydromodpy.results.exporters.vocabulary import list_exportable
from hydromodpy.results.identity import read_identity_from
from hydromodpy.results.run import Run
from hydromodpy.results.storage.run_store import RunStore
from tests._helpers.sealed_run import seal_demo_run


@pytest.fixture
def store(tmp_path, monkeypatch):
    run_dir, _sim_id = seal_demo_run(tmp_path / "project")

    def refuse(*_args, **_kwargs):
        raise AssertionError("an export of a run store opened the index")

    monkeypatch.setattr(Catalog, "__init__", refuse)
    with RunStore.open(run_dir) as opened:
        yield opened


def test_the_listing_reads_the_run_directory(store) -> None:
    held = list_exportable(Run(store.sim_id, store))

    assert held["head"] is ExportKind.field
    assert held["discharge"] is ExportKind.series
    assert held["watershed"] is ExportKind.vector
    assert held["budget"] is ExportKind.table
    assert "mesh_family_faces" not in held


def test_the_data_requests_write_under_the_run_without_the_index(store) -> None:
    requests = load_export_requests(
        [
            {"variables": "watershed"},
            {"variables": "mesh_cell_area", "format": "geotiff"},
            {"variables": "all", "format": "rocrate"},
        ]
    )

    written = export_data_requests(store, store.sim_id, requests)

    exports = store.run_dir / "exports"
    assert sorted(path.name for path in written) == ["mesh_cell_area.tif", "watershed.gpkg"]
    for path in written:
        assert path.parent == exports
        identity = read_identity_from(path)
        assert identity is not None
        assert identity.sim_id == store.sim_id
