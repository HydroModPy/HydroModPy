"""Overview of a site as a run: ``runs/<site>/`` claimed, written and sealed.

The overview writes its outcome first, then its panels and page in the run directory.
The seal holds a record without solver tables (``manifest.json`` last, ``README.md``)
and the outcome flips to ``completed``. A second overview of the site takes ``.v2``.
An overview that fails leaves a failed outcome and no manifest.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

import hydromodpy.workflow.overview as overview_module
from hydromodpy.display.overview.location import (
    overview_figures_dir,
    overview_run_dir,
    overview_run_dir_of,
)
from hydromodpy.project.dispatch.workflow import run_overview
from hydromodpy.project.request import request_of
from hydromodpy.results.outcome import effective_status, read_outcome

OVERVIEW_TOML = """\
[site]
name = "nancon"

[workflow]
mode = "overview"

[geographic]
crs_project = "EPSG:2154"

[geographic.catchment]
kind = "from_outlet_coord"
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
    (root / "overview.toml").write_text(OVERVIEW_TOML, encoding="utf-8")
    launcher = overview_module.DataOverviewLauncher
    for phase in (
        "_setup_geographic",
        "_load_data",
    ):
        monkeypatch.setattr(launcher, phase, lambda *args, **kwargs: None)
    monkeypatch.setattr(
        launcher, "_resolve_geographic_inputs", lambda self, state: (None, root / "dem.tif")
    )
    monkeypatch.setattr(launcher, "_write_page", staticmethod(write_index))
    return root


def write_index(run_dir: Path) -> Path:
    index = run_dir / "report" / "index.html"
    index.parent.mkdir(parents=True, exist_ok=True)
    index.write_text("<html></html>", encoding="utf-8")
    return index


def draw_one_panel(monkeypatch: pytest.MonkeyPatch, seen: dict) -> None:
    def generate(state, inventory) -> list[Path]:
        seen["inventory"] = inventory
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


def test_overview_is_sealed_as_a_run(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict = {}
    draw_one_panel(monkeypatch, seen)

    summary = run_overview(request_of(project / "overview.toml"), base=project).to_dict()

    run_dir = project / "runs" / "nancon"
    assert summary["run_dir"] == str(run_dir)
    assert summary["name"] == "nancon"
    assert summary["web_report"] == str(run_dir / "report" / "index.html")
    assert seen["inventory"] == []
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


def test_seal_holds_inventory_and_inputs(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from hydromodpy.results.record.manifest import InputEntry

    draw_one_panel(monkeypatch, {})
    row = {
        "row_kind": "family",
        "family": "recharge",
        "source": "synthetic",
        "item_id": "",
        "name": None,
        "x": None,
        "y": None,
        "crs_epsg": None,
        "first": None,
        "last": None,
        "records": 2,
        "mean_value": 365.25,
        "unit": "mm/year",
    }
    entry = InputEntry(variable="recharge:recharge", provider="synthetic", path="data/r.csv")
    monkeypatch.setattr(overview_module, "inventory_rows", lambda state: [row])
    monkeypatch.setattr(overview_module, "loaded_inputs", lambda state, root: [entry])

    run_overview(request_of(project / "overview.toml"), base=project)

    run_dir = project / "runs" / "nancon"
    table = pd.read_parquet(run_dir / "tables.parquet" / "data_inventory.parquet")
    assert table[["family", "records", "unit"]].to_dict("records") == [
        {"family": "recharge", "records": 2, "unit": "mm/year"}
    ]
    inputs = json.loads((run_dir / "inputs.json").read_text(encoding="utf-8"))
    assert [item["variable"] for item in inputs["inputs"]] == ["recharge:recharge"]


def test_second_overview_takes_next_version(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    draw_one_panel(monkeypatch, {})
    run_overview(request_of(project / "overview.toml"), base=project)

    second = run_overview(request_of(project / "overview.toml"), base=project).to_dict()

    assert second["run_dir"] == str(project / "runs" / "nancon.v2")
    assert overview_run_dir(project, "nancon") == project / "runs" / "nancon.v2"
    assert (project / "runs" / "nancon.v2" / "figures" / "location.png").is_file()


def test_failed_overview_has_no_manifest(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(state, inventory) -> list[Path]:
        raise RuntimeError("no panel today")

    monkeypatch.setattr(
        overview_module.DataOverviewLauncher, "_generate_report", staticmethod(broken)
    )

    with pytest.raises(RuntimeError, match="no panel today"):
        run_overview(request_of(project / "overview.toml"), base=project)

    run_dir = project / "runs" / "nancon"
    outcome = read_outcome(run_dir)
    assert outcome is not None and outcome.status == "failed"
    assert outcome.error is not None and outcome.error.message == "no panel today"
    assert not (run_dir / "manifest.json").exists()
