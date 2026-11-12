"""``hmp show`` on sealed runs: the README with its annotations, the profile block, the ranking, the report.

The runs are sealed directories under ``runs/``. ``show`` reads them and never builds the index.
Ranking follows the direction of the metric (nse is higher is better, rmse and pbias lower).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from hydromodpy.calibration.criteria.series import HIGHER_IS_BETTER, METRICS
from hydromodpy.core.scoring.metric_table import METRIC_SENSE
from hydromodpy.core.state.layout import catalog_path_for
from hydromodpy.results.annotations import add_note, add_tag
from hydromodpy.results.catalog.indexer import rebuild_index
from hydromodpy.results.storage.run_profile import Profile, ProfileLine, write_profile
from hydromodpy.results.storage.sealing import seal_completed
from tests._helpers.cli_runner import CliRunner
from tests._helpers.metric_rows import headline_row
from tests._helpers.run_stores import open_run_store
from tests._helpers.sealed_runs import SITE, make_project, seal_run, write_session_dir

from ._hmp import run_main as _run

README = "# alpha\n\nRun `alpha` of project `demo`, status **completed**.\n"

# (kind, name, duration in s, reused from, store key) of the steps of one attempt.
PROFILE_LINES = (
    ("step", "build_mesh", 1.5, "no", None),
    ("step", "run_solver", 9.0, "no", None),
    ("solve", "flow_main::modflow6", 8.5, "no", None),
    ("step", "build_geographic", 2.0, "store", "terrain/ab12"),
)

# Three completed runs a, b, c scored on nse, rmse and pbias.
SCORES = {
    "a": {"nse": 0.6, "rmse": 2.0, "pbias": -20.0},
    "b": {"nse": 0.9, "rmse": 0.5, "pbias": 5.0},
    "c": {"nse": 0.3, "rmse": 3.0, "pbias": 30.0},
}

RANKINGS = [
    pytest.param("nse", ["b", "a", "c"], ["c", "a", "b"], id="nse"),
    pytest.param("rmse", ["b", "a", "c"], ["c", "a", "b"], id="rmse"),
    pytest.param("pbias", ["b", "a", "c"], ["c", "a", "b"], id="pbias"),
]


def sealed_demo(tmp_path: Path, *, readme: bool = True) -> Path:
    project = make_project(tmp_path / "demo")
    seal_run(project, "alpha")
    if readme:
        (project / "runs" / "alpha" / "README.md").write_text(README, encoding="utf-8")
    return project


def make_profile() -> Profile:
    at = datetime(2026, 11, 10, 9, 0, tzinfo=UTC)
    lines = tuple(
        ProfileLine(
            kind=kind,
            name=name,
            attempt=1,
            started_at=at,
            duration_s=seconds,
            max_rss_mb=512.0,
            reused=reused,
            key=key,
        )
        for kind, name, seconds, reused, key in PROFILE_LINES
    )
    return Profile(lines=lines, process_age_s={1: 6.5})


@pytest.fixture
def ranked_workspace(tmp_path) -> Path:
    root = tmp_path / "p"
    for name, metrics in SCORES.items():
        store = open_run_store(root, name, create_zarr=False)
        for metric, value in {**metrics, "unknown_score": 1.0}.items():
            store.write_metric(
                store.sim_id, headline_row(metric, value, station=SITE, variable="head")
            )
        seal_completed(store)
    rebuild_index(root)
    return root


def ranked_names(stdout: str) -> list[str]:
    return [line.split()[1] for line in stdout.splitlines() if "#" in line.split()[0]]


def test_the_readme_comes_with_the_annotations(monkeypatch, capsys, tmp_path) -> None:
    project = sealed_demo(tmp_path)
    run_dir = project / "runs" / "alpha"
    add_tag(run_dir, "pinned")
    add_note(run_dir, "K hits its upper bound", now=datetime(2026, 10, 16, 8, 0, tzinfo=UTC))

    code = _run(monkeypatch, ["hmp", "show", "alpha", "-w", str(project)])

    assert code == 0
    out = capsys.readouterr().out
    assert out.startswith(README.rstrip())
    assert "tags: pinned" in out
    assert "2026-10-16 08:00 K hits its upper bound" in out
    assert "hmp show alpha --detail" in out
    assert not catalog_path_for(project).exists(), "show never builds the index"


@pytest.mark.parametrize("view", ["readme", "detail"])
def test_the_profile_block_ends_the_output(monkeypatch, capsys, tmp_path, view) -> None:
    project = sealed_demo(tmp_path)
    write_profile(project / "runs" / "alpha", make_profile())
    argv = ["hmp", "show", "alpha", "-w", str(project)]
    if view == "detail":
        rebuild_index(project)
        argv.append("--detail")

    code = _run(monkeypatch, argv)

    assert code == 0
    out = capsys.readouterr().out
    block = out[out.index("\nProfile\n") :]
    assert "  total      : 12.5 s over 1 attempt(s)" in block
    assert "  start-up   : 6.5 s" in block
    assert "  solve      : flow_main::modflow6 8.5 s" in block
    assert "  longest    : run_solver 9.0 s, build_geographic 2.0 s, build_mesh 1.5 s" in block
    assert "  reused     : build_geographic (store terrain/ab12, attempt 1)" in block
    assert "  peak memory: 512 MiB" in block


def test_a_run_without_a_profile_says_so(monkeypatch, capsys, tmp_path) -> None:
    project = sealed_demo(tmp_path)

    code = _run(monkeypatch, ["hmp", "show", "alpha", "-w", str(project)])

    assert code == 0
    assert "\nProfile\n  no profile.json, solve time from the seal: unknown\n" in (
        capsys.readouterr().out
    )


def test_last_with_dash_w_does_not_repeat_the_hint(monkeypatch, capsys, tmp_path) -> None:
    project = make_project(tmp_path / "demo")

    code = _run(monkeypatch, ["hmp", "show", "@last", "-w", str(project)])

    assert code == 10
    assert "with -w" not in capsys.readouterr().err


@pytest.mark.parametrize(("metric", "best_first", "worst_first"), RANKINGS)
def test_top_and_bottom_follow_the_metric(
    ranked_workspace, metric, best_first, worst_first
) -> None:
    common = ["show", ".", "--rank", metric, "-n", "3", "--workspace", str(ranked_workspace)]

    top = CliRunner().invoke(common)
    bottom = CliRunner().invoke([*common, "--worst"])

    assert top.exit_code == 0, top.stderr
    assert ranked_names(top.stdout) == best_first
    assert bottom.exit_code == 0, bottom.stderr
    assert ranked_names(bottom.stdout) == worst_first


def test_a_metric_without_direction_is_refused(ranked_workspace) -> None:
    result = CliRunner().invoke(
        ["show", ".", "--rank", "unknown_score", "--workspace", str(ranked_workspace)]
    )

    assert result.exit_code == 10
    assert "no declared direction" in result.stderr


def test_every_calibration_metric_has_a_direction() -> None:
    # A criterion turns a score into a cost: its metric is either max or min.
    for name in METRICS:
        assert METRIC_SENSE.get(name) in {"max", "min"}, name
    assert {name for name in METRICS if METRIC_SENSE[name] == "max"} == HIGHER_IS_BETTER


def test_report_writes_the_session_report_and_opens_it(monkeypatch, tmp_path, capsys) -> None:
    root = make_project(tmp_path / "p")
    write_session_dir(root, "session-1", trials=0, best_trial=None)
    html = tmp_path / "report.html"
    html.write_text("<html></html>", encoding="utf-8")
    calls: dict[str, object] = {}

    def fake_report(directory: Path, **_options):
        calls["session_dir"] = directory
        return html

    def fake_open(uri: str) -> bool:
        calls["opened"] = uri
        return True

    monkeypatch.setattr("hydromodpy.project.report.report_session", fake_report)
    monkeypatch.setattr("webbrowser.open", fake_open)

    code = _run(
        monkeypatch, ["hmp", "show", "session-1", "--report", "--workspace", str(root), "--open"]
    )

    assert code == 0
    assert Path(calls["session_dir"]).name == "session-1"
    assert calls["opened"] == html.as_uri()
    assert f"wrote {html}" in capsys.readouterr().err
