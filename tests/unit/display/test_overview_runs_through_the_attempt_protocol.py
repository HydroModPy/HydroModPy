"""An overview is a run: claimed, pulsed, written in its directory, sealed completed.

The overview claims ``runs/<site>/`` through the attempt protocol: its outcome
is written before anything else, its panels and pages land in the run
directory, the seal holds a record without solver tables (``manifest.json``
last, ``README.md``), the outcome flips to ``completed`` and ``.hmp/`` of the
run is gone. A second overview of the same site takes ``.v2``; an overview
that fails leaves a failed outcome and no manifest.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import hydromodpy.workflow.pipelines.overview as overview_module
from hydromodpy.display.overview.location import (
    overview_figures_dir,
    overview_run_dir,
    overview_run_dir_of,
)
from hydromodpy.project.dispatch.workflow import run_overview
from hydromodpy.results.outcome import effective_status, read_outcome

_TOML = """\
[site]
name = "nancon"

[workflow]
mode = "overview"

[geographic]
crs_project = "EPSG:2154"

[geographic.catchment]
kind = "from_outlet_coord"
dem_init_path = "dem.tif"
x_outlet = 389285.9
y_outlet = 6816518.7
snap_dist = "150 m"
buff_area = "10%"

[overview]
name = "identity card"
date_start = "2010-01-01"
date_end = "2012-12-31"
"""


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "proj"
    (root / "data").mkdir(parents=True)
    (root / "project.toml").write_text("", encoding="utf-8")
    (root / "dem.tif").write_bytes(b"never read: the phases are replaced")
    (root / "overview.toml").write_text(_TOML, encoding="utf-8")
    launcher = overview_module.DataOverviewLauncher
    for phase in (
        "_bootstrap_dem",
        "_bootstrap_crossings",
        "_setup_geographic",
        "_load_data",
    ):
        monkeypatch.setattr(launcher, phase, lambda *args, **kwargs: None)
    monkeypatch.setattr(launcher, "_resolve_network_map", lambda self, state: None)
    return root


def _draw_one_panel(monkeypatch: pytest.MonkeyPatch, seen: dict) -> None:
    def generate(state) -> list[Path]:
        run_dir = overview_run_dir_of(state)
        seen["outcome"] = read_outcome(run_dir)
        figures = overview_figures_dir(run_dir)
        figures.mkdir(parents=True, exist_ok=True)
        panel = figures / "location.png"
        panel.write_bytes(b"png")
        return [panel]

    monkeypatch.setattr(
        overview_module.DataOverviewLauncher, "_generate_report", staticmethod(generate)
    )


def test_an_overview_claims_writes_and_seals_its_run_directory(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict = {}
    _draw_one_panel(monkeypatch, seen)

    summary = run_overview(project / "overview.toml").to_dict()

    run_dir = project / "runs" / "nancon"
    assert summary["run_dir"] == str(run_dir)
    assert summary["name"] == "nancon"
    assert seen["outcome"] is not None and seen["outcome"].status == "running"
    assert (run_dir / "figures" / "location.png").is_file()
    assert effective_status(run_dir) == "completed"
    outcome = read_outcome(run_dir)
    assert outcome is not None and outcome.status == "completed"
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["run"]["solver"] == "overview"
    assert manifest["site"]["name"] == "nancon"
    assert manifest["config"]["file"] == "config.toml"
    assert (run_dir / "README.md").is_file()
    assert (run_dir / "config.toml").is_file()
    assert not (run_dir / ".hmp").exists()
    assert not (run_dir / "fields.zarr").exists()


def test_a_second_overview_of_the_same_site_takes_the_next_version(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _draw_one_panel(monkeypatch, {})
    run_overview(project / "overview.toml")

    second = run_overview(project / "overview.toml").to_dict()

    assert second["run_dir"] == str(project / "runs" / "nancon.v2")
    assert overview_run_dir(project, "nancon") == project / "runs" / "nancon.v2"
    assert (project / "runs" / "nancon.v2" / "figures" / "location.png").is_file()


def test_a_failed_overview_leaves_a_failed_outcome_and_no_manifest(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(state) -> list[Path]:
        raise RuntimeError("no panel today")

    monkeypatch.setattr(
        overview_module.DataOverviewLauncher, "_generate_report", staticmethod(broken)
    )

    with pytest.raises(RuntimeError, match="no panel today"):
        run_overview(project / "overview.toml")

    run_dir = project / "runs" / "nancon"
    outcome = read_outcome(run_dir)
    assert outcome is not None and outcome.status == "failed"
    assert outcome.error is not None and outcome.error.message == "no panel today"
    assert not (run_dir / "manifest.json").exists()
