"""A run shared with its data is imported by a colleague and replays with the same heads.

Example 04 is installed in a first workspace (``hmp example add 04`` from this
checkout) and step 5 runs there: it reads the regional DEM, the mapped network
of a GeoPackage and the station series of discharge, recharge and runoff. The
run is published as a tar with its inputs and its results. Under a second
disposable HOME, in a workspace that holds none of these files, the tar is
imported into an empty project, the run is replayed from its frozen
configuration and compared with the copy: the parameters are identical, the
metrics differ by the solve time only, and the head field comes out the same,
to the 16-bit rounding of the stored fields. Every command runs from outside
the project, through ``-w``.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import zarr

from tests.e2e._step1_minimal import REPO, disposable_env, hmp

pytestmark = pytest.mark.e2e

FIELD_PRECISION_RTOL = 2.0**-10
"""Relative step of a float32 rounded to 16 significant bits (see tests/TOLERANCES.md)."""

EXAMPLE = "04_streamflow_intermittence_in_transient"
RUN_NAME = "nancon_step5_export"
READ_FILES = (
    "data/dem/DEM_armorican_massif.tif",
    "data/hydrography/nancon_stream_network.gpkg",
    "data/hydrometry/hydrometry_custom_NANCON_19820201_20220125_D.csv",
    "data/recharge/recharge_custom_NANCON_20000101_20021231_M.csv",
    "data/runoff/runoff_custom_NANCON_20000101_20021231_M.csv",
)


def _heads(run_dir: Path) -> np.ndarray:
    root = zarr.open_group(str(run_dir / "fields.zarr"), mode="r", use_consolidated=False)
    return np.asarray(root["head"])


def _ok(result, what: str) -> None:
    assert result.returncode == 0, f"{what}: {result.stderr[-4000:]}"


def test_a_run_shared_with_its_data_replays_elsewhere_with_the_same_heads(tmp_path) -> None:
    first = disposable_env(tmp_path / "home_first")
    first["HMP_EXAMPLES_SOURCE"] = REPO.as_uri()
    source = tmp_path / "author"
    _ok(hmp("workspace", "init", str(source), cwd=tmp_path, env=first), "workspace init")
    _ok(hmp("example", "add", "04", "-w", str(source), cwd=tmp_path, env=first), "example add")
    project = source / "projects" / EXAMPLE
    _ok(hmp("run", "step5_export.toml", cwd=project, env=first), "run step 5")
    archive = tmp_path / "sim.tar"
    _ok(
        hmp(
            "publish",
            RUN_NAME,
            "--to",
            str(archive),
            "--container",
            "tar",
            "-w",
            str(project),
            cwd=tmp_path,
            env=first,
        ),
        "publish",
    )

    second = disposable_env(tmp_path / "home_second")
    colleague = tmp_path / "colleague"
    _ok(hmp("workspace", "init", str(colleague), cwd=tmp_path, env=second), "workspace init")
    lab = colleague / "projects" / "lab"
    lab.mkdir()
    (lab / "project.toml").write_text("", encoding="utf-8")
    for relative in READ_FILES:
        assert not (colleague / relative).exists(), relative

    imported = hmp("catalog", "import", str(archive), "-w", str(lab), cwd=tmp_path, env=second)
    _ok(imported, "catalog import")
    for relative in READ_FILES:
        assert (colleague / relative).read_bytes() == (source / relative).read_bytes(), relative
    assert f"hmp catalog rerun {RUN_NAME}" in imported.stdout

    _ok(hmp("catalog", "rerun", RUN_NAME, "-w", str(lab), cwd=tmp_path, env=second), "rerun")
    diff = hmp(
        "diff",
        RUN_NAME,
        f"{RUN_NAME}.v2",
        "-w",
        str(lab),
        "--format",
        "json",
        cwd=tmp_path,
        env=second,
    )
    _ok(diff, "diff")
    compared = json.loads(diff.stdout)["data"]
    assert compared["params"] == []
    # Only the solve time differs, and a runtime number is no score.
    assert compared["metrics"] == [], compared["metrics"]

    replay = lab / "runs" / f"{RUN_NAME}.v2"
    manifest = json.loads((replay / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["lineage"]["kind"] == "rerun"
    np.testing.assert_allclose(
        _heads(replay), _heads(lab / "runs" / RUN_NAME), rtol=FIELD_PRECISION_RTOL
    )
