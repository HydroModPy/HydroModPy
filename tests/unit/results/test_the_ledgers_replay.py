"""The ledgers of a run replay: the exports and the figures are written again as recorded.

``exports/index.json`` and ``figures/index.json`` name every derived file of a
run with the options it was written with. Deleting the files and replaying
the ledger writes the same files again, with the same entries and the same
identity block. The exports replay on the store of the run, the index never
opened; the figures replay on the run read through the catalog.
"""

from __future__ import annotations

import pytest

from hydromodpy.core.exceptions import ExportError
from hydromodpy.display.config import DisplayConfig
from hydromodpy.display.runs import figures_dir_of, regen_figures, render_figures_for_run
from hydromodpy.results.catalog import Catalog
from hydromodpy.results.exporters.export_spec import load_export_requests
from hydromodpy.results.exporters.request import (
    export_data_requests,
    regen_exports,
    run_export_target,
)
from hydromodpy.results.identity import read_identity_from
from hydromodpy.results.ledger import Ledger
from hydromodpy.results.storage.run_store import RunStore
from tests._helpers.sealed_run import seal_demo_run


def _entries(directory) -> dict[str, tuple[str, dict, str | None]]:
    return {
        entry.file: (entry.producer, entry.options, entry.identity.sim_id)
        for entry in Ledger.read(directory).entries
    }


def test_the_export_ledger_replays_without_the_index(tmp_path, monkeypatch) -> None:
    run_dir, sim_id = seal_demo_run(tmp_path / "project")

    def refuse(*_args, **_kwargs):
        raise AssertionError("the export ledger replay opened the index")

    monkeypatch.setattr(Catalog, "__init__", refuse)
    requests = load_export_requests(
        [{"variables": "watershed"}, {"variables": "mesh_cell_area", "format": "geotiff"}]
    )
    with RunStore.open(run_dir) as store:
        written = export_data_requests(store, sim_id, requests)
        exports = run_dir / "exports"
        recorded = _entries(exports)
        for path in written:
            path.unlink()

        replayed = regen_exports(store, sim_id, run_export_target(store, sim_id))

    assert sorted(replayed) == sorted(written)
    assert _entries(exports) == recorded
    for path in replayed:
        identity = read_identity_from(path)
        assert identity is not None
        assert identity.sim_id == sim_id


def test_an_empty_export_ledger_is_refused(tmp_path) -> None:
    run_dir, sim_id = seal_demo_run(tmp_path / "project")

    with (
        RunStore.open(run_dir) as store,
        pytest.raises(ExportError, match="records no export to write again"),
    ):
        regen_exports(store, sim_id, run_export_target(store, sim_id))


def test_the_figure_ledger_replays(tmp_path) -> None:
    run_dir, sim_id = seal_demo_run(tmp_path / "project")
    figures = figures_dir_of(run_dir)
    with Catalog(tmp_path / "project") as catalog:
        run = catalog[sim_id]
        report = render_figures_for_run(
            run, DisplayConfig(figures=["water_budget"]), output_dir=figures
        )
        assert report.written
        recorded = _entries(figures)
        for path in report.written:
            path.unlink()

        replayed = regen_figures(run, run_dir)

    assert sorted(replayed.written) == sorted(report.written)
    assert _entries(figures) == recorded
    for path in replayed.written:
        identity = read_identity_from(path)
        assert identity is not None
        assert identity.sim_id == sim_id
