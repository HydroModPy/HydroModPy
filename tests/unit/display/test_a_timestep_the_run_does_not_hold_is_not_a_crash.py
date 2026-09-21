"""A timestep override beyond the run is an inapplicable figure, not a failure.

Measured on the Nancon. ``[display.overrides.seepage_map] timestep = 33`` names
October of the monthly run that project usually runs, and the steady stage of
its stream-network calibration collapses the same record to one period. Reading
step 33 out of a one-step store raises inside zarr, several frames under the
figure; the display step could only report that as a render failure, and
``on_error = "raise"`` then propagated it, so the promoted run of a phase that
had converged was recorded as failed. The figure is not failing: it does not
apply to a run of that length.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from hydromodpy.display import runs as _runs
from hydromodpy.display.config import DisplayConfig
from hydromodpy.display.runs import _timestep_out_of_range, render_figures_for_run


class _Figure:
    """A figure that is available and must never be asked to draw."""

    spec = SimpleNamespace(required_fields=(), required_tables=(), required_solvers=())

    def unavailable_reason(self, _sim) -> None:
        return None

    def plot(self, _sim, **_opts):
        raise AssertionError("a figure whose timestep the run cannot serve must not draw")


class _Run:
    """The two attributes this decision reads off a run."""

    solver = "modflow6"

    def __init__(self, n_timesteps: int | None) -> None:
        self.n_timesteps = n_timesteps

    def has_field(self, _name: str) -> bool:
        return True

    def has_table(self, _name: str) -> bool:
        return True


@pytest.fixture
def one_step_run(monkeypatch):
    monkeypatch.setattr(_runs, "_get_figure", lambda _name: _Figure())
    return _Run(1)


def test_the_figure_is_skipped_and_says_what_the_run_holds(one_step_run, tmp_path) -> None:
    cfg = DisplayConfig(
        enabled=True,
        figures=["seepage_map"],
        overrides={"seepage_map": {"timestep": 33}},
        on_error="raise",
    )

    report = render_figures_for_run(one_step_run, cfg, output_dir=tmp_path)

    assert report.rendered == ()
    assert [skipped.name for skipped in report.skipped] == ["seepage_map"]
    assert "33" in report.skipped[0].reason
    assert "1 timestep" in report.skipped[0].reason


def test_a_timestep_the_run_holds_still_draws(monkeypatch, tmp_path) -> None:
    drawn: list[dict] = []

    class _Drawing(_Figure):
        def plot(self, _sim, **opts):
            drawn.append(opts)

    monkeypatch.setattr(_runs, "_get_figure", lambda _name: _Drawing())
    cfg = DisplayConfig(
        enabled=True,
        figures=["seepage_map"],
        overrides={"seepage_map": {"timestep": 33}},
        on_error="raise",
    )

    report = render_figures_for_run(_Run(36), cfg, output_dir=tmp_path)

    assert report.rendered == ("seepage_map",)
    assert drawn[0]["timestep"] == 33


def test_the_last_step_counted_from_the_end_is_held(one_step_run) -> None:
    # A negative index is resolved against the same length, so -1 is the only
    # step of a single-period run and not one step before it.
    assert _timestep_out_of_range(one_step_run, {"timestep": -1}) is None
    assert _timestep_out_of_range(one_step_run, {"timestep": -2}) is not None


def test_a_run_that_records_no_length_is_left_alone(monkeypatch) -> None:
    # Nothing to compare against, so nothing is refused here: the figure keeps
    # whatever verdict it has of its own.
    assert _timestep_out_of_range(_Run(None), {"timestep": 33}) is None


def test_a_timestep_a_figure_reads_in_its_own_vocabulary_is_left_alone() -> None:
    # Only an integer index is judged. A date or a label belongs to the figure.
    assert _timestep_out_of_range(_Run(1), {"timestep": "2002-10-15"}) is None
    assert _timestep_out_of_range(_Run(1), {}) is None
