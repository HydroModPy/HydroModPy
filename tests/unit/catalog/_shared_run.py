"""A sealed run of a workspace that read a user station file, a Hub'Eau series and a DEM.

The Hub'Eau series sits in ``data/hydrometry/`` with its sidecar, its row in
``hydrometry_hubeau_LOC.csv``, the cache row the sidecar holds; the user
series has its row in ``hydrometry_custom_LOC.csv``; the DEM is a file the
configuration declared. The folder ``data/hydrometry`` also holds a station
the run never read.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

from hydromodpy.results.record.manifest import InputEntry, TrackedInput
from tests._helpers.run_records import make_record

RUN_NAME = "nancon_step5_export"
PROJECT_NAME = "nancon"
HUBEAU_FILE = "hydrometry_hubeau_J0014010_20000101_20021231_D.csv"
CUSTOM_FILE = "hydrometry_custom_NANCON_20000101_20021231_D.csv"
UNREAD_FILE = "hydrometry_custom_OTHER_20000101_20021231_D.csv"
HUBEAU_LOC = "id,x,y,crs\nJ0014010,-1.19645,48.37558,EPSG:4326\n"
CUSTOM_LOC = "id,x,y,crs,unit\nNANCON,389285.9,6816518.7,EPSG:2154,m3/s\nOTHER,1,2,EPSG:2154,m3/s\n"
SERIES = "datetime,value\n2000-01-01,0.5\n2000-01-02,0.6\n"


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_workspace(root: Path, *, project: str = PROJECT_NAME) -> Path:
    """Return the project folder of a scaffolded workspace at *root*."""
    (root / "data").mkdir(parents=True, exist_ok=True)
    folder = root / "projects" / project
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "project.toml").write_text("", encoding="utf-8")
    return folder


def make_shared_run(root: Path) -> Path:
    """Write the workspace and its sealed run; return the run directory."""
    project = make_workspace(root)
    hydrometry = root / "data" / "hydrometry"
    hydrometry.mkdir(parents=True)
    hubeau = hydrometry / HUBEAU_FILE
    hubeau.write_text(SERIES, encoding="utf-8")
    (hydrometry / "hydrometry_hubeau_LOC.csv").write_text(HUBEAU_LOC, encoding="utf-8")
    custom = hydrometry / CUSTOM_FILE
    custom.write_text(SERIES, encoding="utf-8")
    (hydrometry / UNREAD_FILE).write_text(SERIES, encoding="utf-8")
    (hydrometry / "hydrometry_custom_LOC.csv").write_text(CUSTOM_LOC, encoding="utf-8")
    dem = root / "data" / "dem" / "dem.tif"
    dem.parent.mkdir(parents=True)
    dem.write_bytes(b"II*\x00 a DEM the configuration declared")
    _record_hubeau(root, hubeau)
    run_dir = project / "runs" / RUN_NAME
    run_dir.mkdir(parents=True)
    record = make_record(
        inputs=[
            InputEntry(
                variable="hydrometry:discharge",
                provider="hubeau",
                request={"station": "J0014010", "period": ["2000-01-01T00:00:00", None]},
                path=f"data/hydrometry/{HUBEAU_FILE}",
                sha256=sha256_of(hubeau),
                bytes=hubeau.stat().st_size,
                license="etalab-2.0",
            ),
            InputEntry(
                variable="hydrometry:discharge",
                provider="file",
                request={"station": "NANCON"},
                path=f"data/hydrometry/{CUSTOM_FILE}",
                sha256=sha256_of(custom),
                bytes=custom.stat().st_size,
                license="LicenseRef-undetermined",
            ),
        ],
        tracked_inputs=[
            TrackedInput(
                role="dem",
                category="data",
                path="data/dem/dem.tif",
                declared_path="dem.tif",
                sha256=sha256_of(dem),
                bytes=dem.stat().st_size,
                portable=True,
            ),
            TrackedInput(
                role="hydrometry",
                category="data",
                path="data/hydrometry",
                declared_path="hydrometry",
                sha256="f" * 64,
                portable=True,
            ),
        ],
    )
    record.write(run_dir)
    (run_dir / "config.toml").write_text("[flow]\n", encoding="utf-8")
    (run_dir / "README.md").write_text(f"# {RUN_NAME}\n", encoding="utf-8")
    return run_dir


def _record_hubeau(root: Path, hubeau: Path) -> None:
    """Write the sidecar of the Hub'Eau series, as the variable does when it fetches."""
    from hydromodpy.data.provenance.sidecars import CacheIndex

    CacheIndex(root / "data").record(
        hubeau,
        variable="hydrometry",
        source="hubeau",
        station_id="J0014010",
        bbox=(-1.19645, 48.37558, -1.19645, 48.37558),
        crs="EPSG:4326",
        date_start=datetime(2000, 1, 1),
        date_end=datetime(2002, 12, 31),
        frequency="D",
        unit="m3/s",
        asked_window=("2000-01-01T00:00:00", "2002-12-31T00:00:00"),
    )
    sidecar = hubeau.with_name(hubeau.name + ".json")
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    assert payload["source"] == "hubeau"
