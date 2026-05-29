"""Misc baseline benchmarks: GeoParquet, filelock, UUID v7, JSON.

All fixtures are self-contained and avoid any hydromodpy runtime
dependency.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import geopandas as gpd
import numpy as np
import pytest
from filelock import FileLock
from shapely.geometry import Polygon

pytestmark = pytest.mark.performance
uuid_utils = pytest.importorskip("uuid_utils")


def _random_square(rng: np.random.Generator, side: float = 0.01) -> Polygon:
    """Return a small axis-aligned square at a random origin."""
    x0 = float(rng.uniform(0.0, 10.0))
    y0 = float(rng.uniform(40.0, 50.0))
    return Polygon([(x0, y0), (x0 + side, y0), (x0 + side, y0 + side), (x0, y0 + side)])


@pytest.fixture(scope="function")
def geoparquet_path(tmp_path: Path) -> Path:
    """Write a 1000-polygon GeoDataFrame as GeoParquet 1.1."""
    rng = np.random.default_rng(seed=42)
    polys = [_random_square(rng) for _ in range(1000)]
    ids = np.arange(1000, dtype=np.int64)
    gdf = gpd.GeoDataFrame({"id": ids}, geometry=polys, crs="EPSG:4326")
    path = tmp_path / "polys.parquet"
    gdf.to_parquet(path, schema_version="1.1.0")
    return path


@pytest.fixture(scope="function")
def provenance_payload() -> dict:
    """Return a provenance-shaped dict near 10 KB once serialized."""
    return {
        "sim_id": str(uuid_utils.uuid7()),
        "tool": "hydromodpy",
        "version": "2.0.0",
        "created_at": "2026-05-12T10:00:00Z",
        "inputs": [
            {
                "name": f"input_{i}",
                "sha256": "a" * 64,
                "size_bytes": 1024 * i,
                "kind": "forcing" if i % 2 == 0 else "boundary",
                "tags": [f"tag_{j}" for j in range(4)],
            }
            for i in range(40)
        ],
        "params": {f"param_{i}": float(i) * 0.5 for i in range(50)},
        "metrics": {f"metric_{i}": {"mean": float(i), "std": float(i) * 0.1} for i in range(30)},
        "notes": "Self-contained provenance payload for benchmark baseline.",
    }


@pytest.mark.benchmark(group="geoparquet")
def test_geoparquet_roundtrip(benchmark, geoparquet_path: Path) -> None:
    """Read a 1000-polygon GeoParquet 1.1 file."""

    def _read() -> int:
        return len(gpd.read_parquet(geoparquet_path))

    benchmark(_read)


@pytest.mark.benchmark(group="filelock")
def test_filelock_acquire_release(benchmark, tmp_path: Path) -> None:
    """100 sequential acquire+release cycles on a single filelock."""
    lock_path = tmp_path / "guard.lock"

    def _cycle() -> None:
        for _ in range(100):
            with FileLock(str(lock_path)):
                pass

    benchmark(_cycle)


@pytest.mark.benchmark(group="uuid")
def test_uuid7_generation(benchmark) -> None:
    """Generate 10_000 UUID v7 values."""

    def _gen() -> uuid.UUID:
        last = uuid_utils.uuid7()
        for _ in range(9_999):
            last = uuid_utils.uuid7()
        return last

    benchmark(_gen)


@pytest.mark.benchmark(group="json")
def test_json_serialization(benchmark, provenance_payload: dict) -> None:
    """Serialize then parse a ~10 KB provenance dict 1000 times."""

    def _roundtrip() -> dict:
        last: dict = {}
        for _ in range(1000):
            encoded = json.dumps(provenance_payload)
            last = json.loads(encoded)
        return last

    benchmark(_roundtrip)
