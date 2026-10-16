"""Shared fixtures for the FAIR exports integration tier.

A view renders a sealed run directory and nothing else: the fixture writes a
complete seal (``tests/unit/results/_run_record_factory.py``) beside an empty
field store and a parameters table, and builds the export context from that
directory alone.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pyproj import Transformer

from hydromodpy.results.export.context import FairExportContext
from hydromodpy.results.export.directory import context_from_directory
from tests.unit.results._run_record_factory import SIM_ID, make_record

NATIVE_BBOX = (340000.0, 6790000.0, 360000.0, 6810000.0)
"""Bounding box the seal records, in EPSG:2154."""


def wgs84_bbox() -> list[float]:
    """Return the WGS84 box a view must write for :data:`NATIVE_BBOX`."""
    transformer = Transformer.from_crs(2154, 4326, always_xy=True)
    xmin, ymin, xmax, ymax = NATIVE_BBOX
    return list(transformer.transform_bounds(xmin, ymin, xmax, ymax))


def sealed_run(root: Path) -> Path:
    """Write a sealed run directory under *root* and return it."""
    record = make_record()
    run_dir = root / record.run.rel_dir
    (run_dir / "fields.zarr").mkdir(parents=True)
    (run_dir / "fields.zarr" / "zarr.json").write_text(
        '{"zarr_format": 3, "node_type": "group", "attributes": {}}', encoding="utf-8"
    )
    record.write(run_dir)
    return run_dir


@pytest.fixture
def fair_run(tmp_path: Path) -> Path:
    """A sealed run directory."""
    return sealed_run(tmp_path / "project")


@pytest.fixture
def fair_context(fair_run: Path) -> FairExportContext:
    """The export context of :func:`fair_run`, read from the directory alone."""
    return context_from_directory(fair_run)


__all__ = ["NATIVE_BBOX", "SIM_ID", "fair_context", "fair_run", "sealed_run", "wgs84_bbox"]
