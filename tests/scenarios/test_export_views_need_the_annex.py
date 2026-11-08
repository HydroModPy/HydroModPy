"""STAC and the standalone PROV view need hydromodpy_annex, RO-Crate does not."""

from __future__ import annotations

import os
import subprocess
import sys
import tomllib
from pathlib import Path

from tests.scenarios.factory import CALIB, STATION_LOC, STATION_RECORD, STEADY
from tests.scenarios.launcher import Scenario, play, tree_root

MF6_FILES = ("mf6", "libmf6.so")
ENTRY_POINT_GROUP = "hydromodpy.export.format"
ANNEX_ENTRY_POINTS = {
    "stac": "hydromodpy_annex.export.stac:StacItemView",
    "prov": "hydromodpy_annex.export.prov:ProvView",
}


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


def test_export_views_need_the_annex(
    tmp_path: Path, scenario_env: dict[str, str], scenario_cache: Path
) -> None:
    root = tree_root()
    files = {
        "project.toml": STEADY,
        "calib.toml": CALIB,
        "data/piezometry/piezometry_custom_LOC.csv": STATION_LOC,
        "data/piezometry/piezometry_custom_W1_D.csv": STATION_RECORD,
    }
    scenario = Scenario(
        name="steady_island",
        covers="the export port needs hydromodpy_annex for stac while rocrate stays in the wheel",
        files=files,
        argv=("run", "project.toml"),
        needs=MF6_FILES,
    )
    played = play(scenario, tmp_path / "play", scenario_env, scenario_cache)
    assert played.returncode == 0, played.log.read_text(encoding="utf-8")[-2000:]

    run_name = "calage"
    run_dir = played.root / "runs" / run_name
    assert run_dir.is_dir()

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
