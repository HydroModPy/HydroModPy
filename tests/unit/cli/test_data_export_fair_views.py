"""``hmp data export --format`` routes the FAIR sidecars, no catalog needed.

``rocrate``, ``stac`` and ``prov`` are generated views of the sealed run
(:func:`~hydromodpy.results.export.directory.write_views`): with no explicit
``--output`` they must land inside the run directory, beside the seal, and
never under ``share/``. Naming ``--output`` keeps the promise the verb
already makes for every other format: the sidecar is then built from the
catalog and written there instead.

These tests build a real sealed run directory by hand and a minimal fake
catalog, so the routing is checked without a DuckDB index.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from hydromodpy.cli._workers.data import _emit_fair_formats, export_simulation_results
from hydromodpy.schema.generated_views import (
    PROV_VIEW_FILENAME,
    RO_CRATE_VIEW_FILENAME,
    STAC_ITEM_VIEW_FILENAME,
)

pytestmark = pytest.mark.fast

SIM_ID = "4b18da07-43bc-4b02-a7a8-41884e88f39e"


def _seal_run_directory(root: Path) -> Path:
    """The minimal sealed run manifest a directory view can be rendered from."""
    run_dir = root / "runs" / "demo_run"
    run_dir.mkdir(parents=True)
    manifest = {
        "manifest_version": 1,
        "sealed_at": "2026-09-11T00:40:16.903833+00:00",
        "run": {"sim_id": SIM_ID, "name": "demo_run", "project": "demo"},
        "geometry": {"n_cells": 10, "n_layers": 1, "crs_epsg": 2154, "bbox": None},
        "period": {"start": None, "end": None, "n_timesteps": 1},
        "inputs": [],
        "artifacts": [],
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return run_dir


class FakeCatalog:
    """Only the surface ``_emit_fair_formats``/``export_simulation_results`` touch."""

    def __init__(self, run_dir: Path) -> None:
        self._run_dir = run_dir
        self.export_calls: list[tuple[str, Path]] = []

    def run_dir_for(self, sim_id: str) -> Path:
        return self._run_dir

    def export_package(self, sim_id: str, archive: Path) -> Path:
        self.export_calls.append((sim_id, archive))
        archive.write_bytes(b"hmp")
        return archive

    def record_export(self, sim_id: str, *, kind: str, path: Path) -> None:
        del sim_id, kind, path

    def export(self, sim_id: str, spec: Any) -> Path:
        del sim_id
        spec.dest.write_text("csv", encoding="utf-8")
        return spec.dest


def test_generated_views_default_to_the_run_directory(tmp_path: Path) -> None:
    run_dir = _seal_run_directory(tmp_path)
    catalog = FakeCatalog(run_dir)
    share_dir = tmp_path / "share" / "demo_run"
    notes: list[str] = []

    written = _emit_fair_formats(
        catalog,
        SIM_ID,
        share_dir,
        ("rocrate", "stac", "prov"),
        notes,
        output_is_explicit=False,
    )

    assert not notes
    assert {p.name for p in written} == {
        RO_CRATE_VIEW_FILENAME,
        STAC_ITEM_VIEW_FILENAME,
        PROV_VIEW_FILENAME,
    }
    assert all(p.parent == run_dir for p in written)
    assert not share_dir.exists()


def test_explicit_output_keeps_the_verbs_promise(tmp_path: Path, monkeypatch) -> None:
    run_dir = _seal_run_directory(tmp_path)
    catalog = FakeCatalog(run_dir)
    output_dir = tmp_path / "somewhere_else"
    output_dir.mkdir()
    calls: dict[str, Any] = {}

    def _fake_build_context(catalog: Any, sim_id: str) -> str:
        calls["build_context"] = sim_id
        return "ctx"

    def _fake_write_ro_crate(catalog: Any, sim_id: str, out: Path, *, context: Any) -> Path:
        calls["rocrate"] = (out, context)
        dest = out / RO_CRATE_VIEW_FILENAME
        dest.write_text("{}", encoding="utf-8")
        return dest

    def _fake_write_stac_item(catalog: Any, sim_id: str, out: Path, *, context: Any) -> Path:
        calls["stac"] = (out, context)
        dest = out / STAC_ITEM_VIEW_FILENAME
        dest.write_text("{}", encoding="utf-8")
        return dest

    def _fake_write_prov(catalog: Any, sim_id: str, out: Path, *, context: Any) -> Path:
        calls["prov"] = (out, context)
        dest = out / PROV_VIEW_FILENAME
        dest.write_text("{}", encoding="utf-8")
        return dest

    import hydromodpy.results.export as export_mod
    import hydromodpy.results.export.prov as prov_mod

    monkeypatch.setattr(export_mod, "build_context", _fake_build_context)
    monkeypatch.setattr(export_mod, "write_ro_crate", _fake_write_ro_crate)
    monkeypatch.setattr(export_mod, "write_stac_item", _fake_write_stac_item)
    monkeypatch.setattr(prov_mod, "write_prov", _fake_write_prov)

    notes: list[str] = []
    written = _emit_fair_formats(
        catalog,
        SIM_ID,
        output_dir,
        ("rocrate", "stac", "prov"),
        notes,
        output_is_explicit=True,
    )

    assert not notes
    assert all(p.parent == output_dir for p in written)
    assert calls["rocrate"][0] == output_dir
    assert calls["stac"][0] == output_dir
    assert calls["prov"][0] == output_dir
    # the run directory itself must stay untouched
    assert list(run_dir.iterdir()) == [run_dir / "manifest.json"]


def test_export_simulation_results_splits_views_from_the_rest(tmp_path: Path) -> None:
    """The verb keeps writing everything else into ``output_dir``.

    ``csv``/``netcdf``/``geotiff``/``vtu`` and the ``hmp`` archive are
    unaffected by this change: only the generated views move. With no
    variable format requested, the verb still defaults to a CSV export, so
    ``output_dir`` exists regardless; what matters is that the RO-Crate view
    is not inside it.
    """
    run_dir = _seal_run_directory(tmp_path)
    catalog = FakeCatalog(run_dir)
    share_dir = tmp_path / "share" / "demo_run"

    result = export_simulation_results(
        catalog,
        SIM_ID,
        "demo_run",
        share_dir,
        var=None,
        csv=False,
        netcdf=False,
        geotiff=False,
        vtu=False,
        resolution=None,
        fair_formats=("hmp", "rocrate"),
        output_is_explicit=False,
    )

    assert not result["notes"]
    assert (share_dir / "timeseries.csv").is_file()
    assert (share_dir / f"{share_dir.name}.hmp").is_file()
    assert not (share_dir / RO_CRATE_VIEW_FILENAME).exists()
    assert (run_dir / RO_CRATE_VIEW_FILENAME).is_file()
