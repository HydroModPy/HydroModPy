"""A sealed run directory with everything a publication copies, leaves out or redacts."""

from __future__ import annotations

import json
import socket
from pathlib import Path

from hydromodpy.results.ledger import sha256_of
from hydromodpy.results.manifest import InputEntry, TrackedInput
from tests.unit.results._run_record_factory import make_record

RUN_NAME = "J0014010-base.v2"


def make_project(tmp_path: Path, *, license: str | None = "etalab-2.0") -> Path:
    """Return a project root inside a workspace, its project.toml declaring the licence."""
    workspace = tmp_path / "workspace"
    (workspace / "data" / "hydrometry").mkdir(parents=True)
    (workspace / "workspace.toml").write_text("[workspace]\n", encoding="utf-8")
    project = workspace / "projects" / "bretagne_k"
    project.mkdir(parents=True)
    table = f'[publication]\nlicense = "{license}"\n' if license else ""
    (project / "project.toml").write_text(table, encoding="utf-8")
    return project


def make_sealed_run(project: Path, *, license: str | None = "etalab-2.0") -> Path:
    """Write a sealed run with derived files, diagnostics and machine state beside the seal."""
    workspace = project.parent.parent
    observed = workspace / "data" / "hydrometry" / "J0014010.csv"
    observed.write_text("datetime,value\n2016-01-01,1.0\n", encoding="utf-8")
    entry = InputEntry(
        variable="discharge_obs",
        provider="hubeau",
        product="hydrometrie",
        request={"stations": ["J0014010"]},
        path="data/hydrometry/J0014010.csv",
        sha256=sha256_of(observed),
        bytes=observed.stat().st_size,
        license="etalab-2.0",
    )
    dem = workspace / "data" / "dem" / "bdalti_25m.tif"
    dem.parent.mkdir(parents=True, exist_ok=True)
    dem.write_bytes(b"II*\x00 a DEM the configuration declared")
    tracked = TrackedInput(
        role="dem",
        category="raster",
        path="data/dem/bdalti_25m.tif",
        declared_path="data/dem/bdalti_25m.tif",
        sha256=sha256_of(dem),
        bytes=dem.stat().st_size,
        portable=True,
    )
    record = make_record(inputs=[entry], tracked_inputs=[tracked])
    run_dir = project / "runs" / RUN_NAME
    run_dir.mkdir(parents=True)
    record.write(run_dir)
    provenance = json.loads((run_dir / "provenance.json").read_text(encoding="utf-8"))
    provenance["platform"] = {
        "hostname": socket.gethostname(),
        "user": "someone",
        "cpu": "x86_64",
    }
    provenance["solver"] = {"name": "mf6", "binary_path": str(workspace / "bin" / "mf6")}
    (run_dir / "provenance.json").write_text(json.dumps(provenance), encoding="utf-8")
    publication = (
        f'[publication]\nlicense = "{license}"\ncreators = ["A. Author"]\n' if license else ""
    )
    (run_dir / "config.toml").write_text(
        f'{publication}[workspace]\nroot = "{workspace}"\ndata_dir = "{workspace / "data"}"\n',
        encoding="utf-8",
    )
    (run_dir / "README.md").write_text(
        f"# {RUN_NAME}\n\nComputed in {project}.\n", encoding="utf-8"
    )
    (run_dir / "figures").mkdir()
    (run_dir / "figures" / "heads.png").write_bytes(b"\x89PNG fake")
    (run_dir / "figures" / "index.json").write_text(
        '{"schema": "hydromodpy.ledger.v1", "entries": []}'
    )
    (run_dir / "exports").mkdir()
    (run_dir / "exports" / "discharge.csv").write_text(
        "site,case_id,value\nJ0014010,J0014010-base,1\n"
    )
    (run_dir / "report").mkdir()
    (run_dir / "report" / "index.html").write_text("<html><body><p>Nancon</p></body></html>")
    (run_dir / "logs").mkdir()
    (run_dir / "logs" / "run.1.log").write_text(f"running on {socket.gethostname()}\n")
    (run_dir / "attempts" / "1").mkdir(parents=True)
    (run_dir / "attempts" / "1" / "outcome.json").write_text("{}")
    (run_dir / ".hmp" / "scratch").mkdir(parents=True)
    (run_dir / ".hmp" / "scratch" / "mfsim.nam").write_text("scratch")
    (run_dir / "outcome.json").write_text('{"status": "completed"}')
    (run_dir / "fields.zarr").mkdir()
    (run_dir / "fields.zarr" / "zarr.json").write_text('{"zarr_format": 3, "node_type": "group"}')
    return run_dir
