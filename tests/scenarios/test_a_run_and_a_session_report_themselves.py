"""A run and a calibration session report themselves, and ``hmp show`` reads the session.

On the transient island with two piezometry stations, ``hmp run`` draws three figures.
They are drawn after the seal, so each footer carries the label, its rule and its day.
``hmp show <run> --report`` then writes the three-level report, and the one-page
sheet in French. ``hmp calibrate`` of three trials writes the report of its session
by itself, and ``hmp show <session>`` prints the rows of the summary.

The commands run one after the other in one child process, which keeps the solver
and the DEM backend out of the pytest worker. Each result lands in ``commands.json``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hydromodpy.display.png_metadata import read_png_metadata
from tests.scenarios.factory import island_files
from tests.scenarios.launcher import Scenario, play

SESSION = "calage_sy.v2"
"""The run of ``hmp run`` took the name, so the session of the calibration is its second version."""
FIGURES = ("watershed_id_card", "seepage_map", "flux_timeseries")
NEEDS_A_GAUGE_OR_A_NETWORK = {
    "downslope_distance_map",
    "flow_intermittence_map",
    "flow_persistence_map",
    "hydrograph_sim_obs",
    "hydrographic_network_permanence",
    "network_extent_bounds_map",
    "seepage_network_confusion_map",
    "simulated_active_network_reference_overlay",
}
SECOND_STATION_LOC = "id,x,y\nW1,305.0,305.0\nW2,295.0,295.0\n"
SECOND_STATION_RECORD = "datetime,value\n2003-02-28,2.1\n2003-03-31,2.1\n"

COMMANDS = (
    ("run", "run", "project.toml"),
    ("research", "show", "calage_sy", "--report"),
    ("sheet", "show", "calage_sy", "--report", "--preset", "management", "--lang", "fr"),
    ("calibrate", "calibrate", "calib.toml"),
    ("show", "show", "calage_sy.v2", "--format", "json"),
)

SCRIPT = f"""\
import json, subprocess, sys
commands = {COMMANDS!r}
done = {{}}
for key, *argv in commands:
    result = subprocess.run(
        [sys.executable, "-m", "hydromodpy", *argv], capture_output=True, text=True
    )
    done[key] = {{"code": result.returncode, "out": result.stdout, "err": result.stderr[-3000:]}}
    if result.returncode:
        break
open("commands.json", "w", encoding="utf-8").write(json.dumps(done))
"""


def _files() -> dict[str, str]:
    files = dict(island_files("calage_sy"))
    files["project.toml"] = files["project.toml"].replace(
        "[display]\nenabled = false",
        f"[display]\nenabled = true\nfigures = {list(FIGURES)!r}".replace("'", '"'),
        1,
    )
    files["data/piezometry/piezometry_custom_LOC.csv"] = SECOND_STATION_LOC
    files["data/piezometry/piezometry_custom_W2_D.csv"] = SECOND_STATION_RECORD
    return files


@pytest.fixture
def played(tmp_path: Path, scenario_env, scenario_cache) -> tuple[Path, dict]:
    scenario = Scenario(
        name="reports",
        covers="a run and a calibration session write their own reports",
        files=_files(),
        python=SCRIPT,
        expected_s=120.0,
    )
    result = play(scenario, tmp_path / "play", scenario_env, scenario_cache)
    log = result.log.read_text(encoding="utf-8", errors="replace")[-3000:]
    assert result.returncode == 0, log
    commands = json.loads((result.root / "commands.json").read_text(encoding="utf-8"))
    assert set(commands) == {key for key, *_ in COMMANDS}, commands
    for key, outcome in commands.items():
        assert outcome["code"] == 0, f"{key}: {outcome['err']}"
    return result.root, commands


def test_the_figures_of_a_run_carry_the_label_of_the_seal(played) -> None:
    root, _ = played
    drawn = sorted((root / "runs" / "calage_sy" / "figures").glob("*.png"))

    # The report draws more figures here, after the three the run asked for.
    assert set(FIGURES) <= {path.stem for path in drawn}
    for path in drawn:
        identity = json.loads(read_png_metadata(path)["hydromodpy.identity"])
        assert identity.get("label"), path.name
        assert identity.get("rule_version"), path.name
        assert identity.get("label_date"), path.name


def test_the_research_report_lists_what_it_misses_and_names_the_figures_of_the_run(played) -> None:
    root, _ = played
    out = root / "runs" / "calage_sy" / "report"
    document = json.loads((out / "report.json").read_text(encoding="utf-8"))

    assert (out / "index.html").is_file()
    assert (out / "review" / "audit" / "index.html").is_file()
    # The island has no discharge gauge and no reference network, so the figures
    # that read them stay empty frames. Nothing else is missing.
    assert document["missing"] == sorted(document["missing"])
    assert set(document["missing"]) <= NEEDS_A_GAUGE_OR_A_NETWORK, document["missing"]
    for name in FIGURES:
        assert document["figures"][name]["file"] == f"{name}.png"


def test_the_french_sheet_carries_the_label_sentence_in_french(played) -> None:
    root, _ = played
    sheet = root / "runs" / "calage_sy" / "report" / "sheet-fr"
    text = (sheet / "index.html").read_text(encoding="utf-8")

    assert (sheet / "report.json").is_file()
    assert "Étiquette" in text
    assert "Méthode" in text


def test_the_calibration_writes_its_session_report_and_show_reads_it(played) -> None:
    root, commands = played
    session = root / "sessions" / SESSION
    page = session / "report" / "index.html"

    assert page.is_file()
    assert any((session / "figures").glob("calibration_*.png"))
    data = json.loads(commands["show"]["out"])["data"]
    assert data["name"] == SESSION
    assert data["trials_by_status"] == {"completed": 3}
    assert data["report"] == str(page)
