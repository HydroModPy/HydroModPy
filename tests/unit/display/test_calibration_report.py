from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

import hydromodpy.display.calibration_report as report
from tests._helpers.sealed_runs import write_session_dir


@dataclass
class _Payload:
    session_id: str
    session_name: str
    session: dict
    iterations: list[dict]
    workspace_root: Path
    best_rel_dir: str | None = None
    variable: str = "discharge"


class _Figure:
    def __init__(self, seen: list | None = None) -> None:
        self.seen = seen

    def plot(self, sim, *, save_path: Path, **kwargs) -> None:
        if self.seen is not None:
            self.seen.append((Path(save_path).name, sim, kwargs))
        Path(save_path).write_bytes(b"png")


class _Failing:
    def plot(self, sim, *, save_path: Path, **kwargs) -> None:
        raise ValueError("bad inputs")


class _Silent:
    def plot(self, sim, *, save_path: Path, **kwargs) -> None:
        return None


def _payload(tmp_path: Path, **session) -> _Payload:
    write_session_dir(tmp_path, "s", session_id="abcdef123456")
    return _Payload(
        session_id="abcdef123456",
        session_name="s",
        session={"session_id": "abcdef123456", "method": "grid", **session},
        iterations=[{"trial": 0, "cost": 1.0, "status": "completed", "parameters": {}}],
        workspace_root=tmp_path,
    )


def _index(tmp_path: Path) -> Path:
    return tmp_path / "sessions" / "s" / "report" / "index.html"


@pytest.mark.parametrize(
    ("figure", "requested"),
    [
        (_Figure(), "missing_figure"),
        (_Failing(), "calibration_trace"),
        (_Silent(), "calibration_trace"),
    ],
    ids=["unregistered", "raises", "writes nothing"],
)
def test_a_figure_that_cannot_be_drawn_is_skipped_and_the_page_is_written(
    tmp_path, monkeypatch, figure, requested
) -> None:
    monkeypatch.setattr(report, "_figure_names", lambda: ["calibration_trace"])
    monkeypatch.setattr(report, "_get_figure", lambda name: figure)

    written = report.render_session(
        _payload(tmp_path), figure_names=[requested], session_dir=tmp_path / "sessions" / "s"
    )

    assert written == [_index(tmp_path)]
    assert "No figures rendered." in _index(tmp_path).read_text()


@pytest.mark.parametrize(
    ("variable", "panels"),
    [
        ("discharge", {"hydrograph_sim_obs.png", "scatter_one_to_one.png"}),
        ("lake_level", {"lake_stage_sim_obs.png"}),
    ],
)
def test_the_best_run_is_drawn_by_the_registered_figures_of_its_variable(
    tmp_path, monkeypatch, variable, panels
) -> None:
    seen: list = []
    best = object()
    monkeypatch.setattr(report, "_figure_names", lambda: ["calibration_trace", *_all_panels()])
    monkeypatch.setattr(report, "_get_figure", lambda name: _Figure(seen))
    monkeypatch.setattr(report, "open_run_dir", lambda path: best)
    payload = _payload(tmp_path)
    payload.best_rel_dir, payload.variable = "runs/best", variable

    written = report.render_session(payload, figure_names=["calibration_trace"])

    drawn = {name: (sim, kwargs) for name, sim, kwargs in seen}
    assert set(drawn) == {"calibration_trace.png", *panels}
    assert all(drawn[name][0] is best and drawn[name][1] == {} for name in panels)
    assert {path.name for path in written} == {"calibration_trace.png", *panels, "index.html"}
    page = _index(tmp_path).read_text()
    assert all(f"../figures/{name}" in page for name in panels)


def _all_panels() -> list[str]:
    return [name for names in report._BEST_RUN_FIGURES.values() for name in names]


def test_a_best_run_that_does_not_open_leaves_the_page_without_its_panels(
    tmp_path, monkeypatch
) -> None:
    def refuse(path):
        raise FileNotFoundError(path)

    monkeypatch.setattr(report, "_figure_names", lambda: [*_all_panels()])
    monkeypatch.setattr(report, "_get_figure", lambda name: _Figure())
    monkeypatch.setattr(report, "open_run_dir", refuse)
    payload = _payload(tmp_path)
    payload.best_rel_dir = "runs/gone"

    written = report.render_session(payload, figure_names=[])

    assert written == [_index(tmp_path)]


def test_the_report_hands_the_figures_the_rows_a_session_wrote() -> None:
    """One flattening for both carriers, so one figure gives one reading.

    The figures label the cost panel after the column they resolve, so the same
    figure must name the same quantity from a session journal and from a promoted run.
    """
    from hydromodpy.display.figures._trial_diagnostics import trial_table

    rows = [
        {
            "trial": 0,
            "cost": 0.5,
            "status": "completed",
            "sim_id": "deadbeef",
            "parameters": {
                "K": {"value": 1e-4, "search_space": "log"},
                "bedleak": {"value": 2e-6},
            },
        },
        # parameters as a JSON string, the way DuckDB persists them
        {
            "trial": 1,
            "cost": 0.3,
            "parameters": '{"K": {"value": 5e-5}, "bedleak": {"value": 9e-6}}',
        },
    ]
    stub = report._SessionRunStub(rows)

    assert stub.calibration_iterations == rows

    table = trial_table(stub)
    assert table.parameters == ("K", "bedleak")
    assert table.objective_column() == "cost"
    assert table.parameter_values("K")[1].tolist() == pytest.approx([1e-4, 5e-5])
    assert table.cost_values()[1].tolist() == pytest.approx([0.5, 0.3])
    assert stub.timeseries("cost")["cost"].tolist() == pytest.approx([0.5, 0.3])


def test_the_page_escapes_what_a_session_wrote_and_lands_in_the_session_directory(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(report, "_figure_names", lambda: ["<Figure & Name>"])
    monkeypatch.setattr(report, "_get_figure", lambda name: _Figure())
    payload = _payload(
        tmp_path, project="<Project & Co>", status="<script>alert(1)</script>", n_trials=1
    )
    payload.iterations[0].update(status="<done>", parameters={"b": "<tag>", "a": 1})

    written = report.render_session(payload, figure_names=["<Figure & Name>"])

    page = _index(tmp_path).read_text()
    assert written[-1] == _index(tmp_path)
    for raw in ("<Project & Co>", "<script>alert(1)</script>", "<Figure & Name>", "<done>"):
        assert raw not in page
    assert "&lt;Project &amp; Co&gt;" in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page
    assert '{"a": 1, "b": "&lt;tag&gt;"}' in page
    assert not (tmp_path / "share").exists()
