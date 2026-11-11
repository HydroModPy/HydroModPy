"""A run exports every file format of the port, and the views that need the annex say so.

The permanent island is played once, with its piezometer station. Then ``hmp export``
writes the discharge series as ``csv`` and the head field as ``netcdf``, ``geotiff``,
``geopackage``, ``shapefile`` and ``vtu``, each to a folder of its own. Every format
must give at least one non-empty file with its suffix, and the NetCDF head of the last
step must hold the bits of ``run.read("head")``. ``csv`` takes the series because it
writes only series and tables. Last, STAC and the standalone PROV view need
``hydromodpy_annex`` while RO-Crate stays in the wheel. Every simulated series of the
run, the piezometer series included, carries the unit of its descriptor.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tomllib
from pathlib import Path

import numpy as np
import pytest

from tests.scenarios.factory import island_files
from tests.scenarios.launcher import Scenario, isolated_env, play, tree_root

# The module fixture plays the project once, so every test of the file runs
# on the worker that played it.
pytestmark = [pytest.mark.xdist_group(name="export_formats")]

MF6_FILES = ("mf6", "libmf6.so")
ENTRY_POINT_GROUP = "hydromodpy.export.format"
ANNEX_ENTRY_POINTS = {
    "stac": "hydromodpy_annex.export.stac:StacItemView",
    "prov": "hydromodpy_annex.export.prov:ProvView",
}
RUN = "calage"
# One row per format: the variable it exports and the suffix of its files.
FORMATS = (
    ("csv", "discharge", ".csv"),
    ("netcdf", "head", ".nc"),
    ("geotiff", "head", ".tif"),
    ("geopackage", "head", ".gpkg"),
    ("shapefile", "head", ".shp"),
    ("vtu", "head", ".vtu"),
)


@pytest.fixture(scope="module")
def steady_island(tmp_path_factory: pytest.TempPathFactory, scenario_cache: Path):
    """Play the permanent island once, for the cases that export or read its run."""
    base = tmp_path_factory.mktemp("export_formats")
    env = isolated_env(base / "home", scenario_cache, base / "state", base / "tmp")
    files = dict(island_files("calage"))
    del files["calib.toml"]
    scenario = Scenario(
        name="steady_island",
        covers="the export port on the permanent island, every file format and the annex views",
        files=files,
        argv=("run", "project.toml"),
        needs=MF6_FILES,
    )
    played = play(scenario, base / "play", env, scenario_cache)
    assert played.returncode == 0, played.log.read_text(encoding="utf-8")[-2000:]
    assert (played.root / "runs" / RUN).is_dir()
    return played, env


def _export(played, env: dict[str, str], variable: str, file_format: str):
    """Run ``hmp export`` of one variable to the folder ``as_<format>`` of the run."""
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "hydromodpy",
            "export",
            RUN,
            variable,
            "--as",
            file_format,
            "--to",
            f"as_{file_format}",
        ],
        cwd=played.root,
        env=env,
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize(("file_format", "variable", "suffix"), FORMATS)
def test_a_run_exports_a_file_in_each_format(steady_island, file_format, variable, suffix) -> None:
    played, env = steady_island

    done = _export(played, env, variable, file_format)

    assert done.returncode == 0, done.stdout[-1000:] + done.stderr[-1000:]
    folder = played.root / "runs" / RUN / "exports" / f"as_{file_format}"
    written = sorted(folder.rglob(f"*{suffix}"))
    assert written, f"no {suffix} file under {folder}"
    assert all(path.stat().st_size > 0 for path in written)


def test_the_netcdf_head_holds_the_bits_of_the_run(steady_island) -> None:
    import xarray as xr

    import hydromodpy as hmp

    played, env = steady_island
    done = _export(played, env, "head", "netcdf")
    assert done.returncode == 0, done.stdout[-1000:] + done.stderr[-1000:]
    folder = played.root / "runs" / RUN / "exports" / "as_netcdf"
    (path,) = sorted(folder.rglob("*.nc"))

    with xr.open_dataset(path) as dataset:
        last = dataset["head"]
        if "time" in last.dims:
            last = last.isel(time=-1)
        written = np.asarray(last.values).ravel()
    read = np.asarray(hmp.open(played.root / "runs" / RUN).read("head", time=-1)).ravel()

    assert written.size == read.size
    assert np.array_equal(written, read, equal_nan=True)


def test_every_simulated_series_carries_the_unit_of_its_descriptor(steady_island) -> None:
    import hydromodpy as hmp
    from hydromodpy.core.scope import SIMULATED
    from hydromodpy.results import field_registry

    played, _ = steady_island
    table = hmp.open(played.root / "runs" / RUN).table("timeseries")
    simulated = table[table["source"] == SIMULATED]
    pairs = set(zip(simulated["variable"], simulated["unit"], strict=True))

    assert "groundwater_level" in {variable for variable, _ in pairs}
    for variable, unit in sorted(pairs):
        if variable in field_registry.TIME_SERIES_REGISTRY:
            expected = field_registry.series_unit(variable)
        else:
            expected = field_registry.get(variable).units
        assert unit == expected, (
            f"{variable} is stored in {unit!r}, its descriptor says {expected!r}"
        )


def _read_entry_points(root: Path) -> dict[str, str]:
    """Read [project.entry-points."hydromodpy.export.format"] from pyproject.toml if present."""
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        group = data.get("project", {}).get("entry-points", {}).get(ENTRY_POINT_GROUP, {})
        if group:
            return dict(group)
    return dict(ANNEX_ENTRY_POINTS)


def _write_dist_info(target_dir: Path, entries: dict[str, str]) -> Path:
    """Create a .dist-info directory publishing the export formats on ENTRY_POINT_GROUP."""
    dist_info = target_dir / "hydromodpy_annex_probe-0.1.0.dist-info"
    dist_info.mkdir(parents=True, exist_ok=True)
    (dist_info / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: hydromodpy-annex-probe\nVersion: 0.1.0\n",
        encoding="utf-8",
    )
    lines = [f"[{ENTRY_POINT_GROUP}]"]
    for name, target in sorted(entries.items()):
        lines.append(f"{name} = {target}")
    lines.append("")
    (dist_info / "entry_points.txt").write_text("\n".join(lines), encoding="utf-8")
    return dist_info


def test_export_views_need_the_annex(tmp_path: Path, steady_island) -> None:
    root = tree_root()
    played, scenario_env = steady_island
    run_name = RUN
    run_dir = played.root / "runs" / run_name

    entries = _read_entry_points(root)
    probe_site = tmp_path / "probe_site"
    _write_dist_info(probe_site, entries)

    # 1. Without hydromodpy_annex on sys.path: wheel only
    wheel_only = tmp_path / "wheel_only"
    wheel_only.mkdir(parents=True, exist_ok=True)
    hmp_link = wheel_only / "hydromodpy"
    if not hmp_link.exists():
        hmp_link.symlink_to(root / "hydromodpy")

    env_without_annex = dict(scenario_env)
    env_without_annex["PYTHONPATH"] = f"{probe_site}{os.pathsep}{wheel_only}"

    res_stac_fail = subprocess.run(
        [sys.executable, "-m", "hydromodpy", "export", run_name, "all", "--as", "stac"],
        cwd=played.root,
        env=env_without_annex,
        capture_output=True,
        text=True,
    )
    assert res_stac_fail.returncode != 0
    combined_err = res_stac_fail.stdout + res_stac_fail.stderr
    assert "hydromodpy_annex.export.stac" in combined_err

    res_rocrate_ok = subprocess.run(
        [sys.executable, "-m", "hydromodpy", "export", run_name, "all", "--as", "rocrate"],
        cwd=played.root,
        env=env_without_annex,
        capture_output=True,
        text=True,
    )
    assert res_rocrate_ok.returncode == 0, res_rocrate_ok.stderr
    assert (run_dir / "ro-crate-metadata.json").is_file()

    # 2. With hydromodpy_annex on sys.path: root of repository
    env_with_annex = dict(scenario_env)
    env_with_annex["PYTHONPATH"] = f"{probe_site}{os.pathsep}{root}"

    res_stac_ok = subprocess.run(
        [sys.executable, "-m", "hydromodpy", "export", run_name, "all", "--as", "stac"],
        cwd=played.root,
        env=env_with_annex,
        capture_output=True,
        text=True,
    )
    assert res_stac_ok.returncode == 0, res_stac_ok.stderr
    assert (run_dir / "stac-item.json").is_file()

    res_rocrate_ok2 = subprocess.run(
        [sys.executable, "-m", "hydromodpy", "export", run_name, "all", "--as", "rocrate"],
        cwd=played.root,
        env=env_with_annex,
        capture_output=True,
        text=True,
    )
    assert res_rocrate_ok2.returncode == 0, res_rocrate_ok2.stderr
