"""Rendering the figures of a run."""

from __future__ import annotations

import logging
import uuid
import warnings
from collections.abc import Callable, Iterator
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from hydromodpy.core.budget.terms import budget_terms_for
from hydromodpy.core.console.progress import MILESTONE_KEY
from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.layout import RUNS_DIRNAME
from hydromodpy.display import runs
from hydromodpy.display import runs as _runs
from hydromodpy.display.config import DisplayConfig
from hydromodpy.display.figure import FigureNotApplicable, FigureSpec
from hydromodpy.display.figures._trial_diagnostics import TrialTable
from hydromodpy.display.runs import log_render_summary, render_figure, render_figures_for_run
from hydromodpy.results.catalog.facade import Catalog
from hydromodpy.results.catalog.indexer import rebuild_index
from hydromodpy.results.derive.config_flags import no_surface_exit_reason
from hydromodpy.results.run.periods import RunPeriods
from hydromodpy.results.run.view import Run
from hydromodpy.results.storage.contract import RUN_FIGURES_DIRNAME
from hydromodpy.results.storage.sealing import seal_completed
from hydromodpy.results.zarr_store.simulation_zarr import SimulationZarr
from tests._helpers.run_stores import open_run_store

# Coverage for ``hydromodpy.display.runs`` - the shared helper used by
# both ``hmp display`` and the pipeline ``DisplayStep``.
#
# These tests exercise policy, not rendering:
#     * ``enabled=False`` or empty ``figures`` must produce zero output.
#     * Unknown figure names are rejected by the config, not at render time.
#     * A figure whose requirements the run does not meet is skipped.
#     * Written files land in ``<output_dir>/<figure>.png``.
#     * ``figures_dir_of`` nests figures in ``runs/<run>/figures``,
#       naming the run directory after the run and falling back to a short
#       sim_id otherwise.


class _StubRun:
    """Minimal Run stand-in - the stubbed figure never reads from it."""

    sim_id = "11111111-2222-3333-4444-555555555555"
    name = "baseline"

    def has_field(self, variable: str, *, subgroup: str | None = None) -> bool:
        del variable, subgroup
        return False


class _StubFigure:
    """Stubbed figure that just writes a placeholder PNG."""

    def __init__(
        self,
        name: str,
        *,
        unavailable: str | None = None,
        required_fields: tuple[str, ...] = (),
    ) -> None:
        self.name = name
        self.calls: list[tuple[Path | None, int]] = []
        self._unavailable = unavailable
        self.spec = FigureSpec(name=name, title=name, required_fields=required_fields)

    def unavailable_reason(self, sim) -> str | None:
        del sim
        return self._unavailable

    def plot(self, sim, *, dpi: int = 150, save_path: Path | None = None, **kw) -> None:
        self.calls.append((save_path, dpi))
        if save_path is not None:
            Path(save_path).write_bytes(b"stub-png")


@pytest.fixture
def runs_module():
    # Import inside the fixture so each test sees the live module instance,
    # even when a sibling test drops `hydromodpy.display.*` from sys.modules.
    import hydromodpy.display.runs as mod

    return mod


@pytest.fixture
def patched_registry(monkeypatch, runs_module):
    """Patch the figure lookup so the test never imports matplotlib."""
    stubs: dict[str, _StubFigure] = {}

    def _fake_get(name: str):
        if name not in stubs:
            if name.startswith("bad_"):
                raise KeyError(name)
            # 'na_' stubs are inapplicable by nature (no such process in the
            # run); 'nd_' stubs miss a field rebuilt from budget terms the run did not keep;
            # 'nb_' stubs miss a raw budget field the budget switch keeps.
            required: tuple[str, ...] = ()
            if name.startswith("nd_"):
                required = ("drain_accumulation_flux",)
            elif name.startswith("nb_"):
                required = ("recharge",)
            stubs[name] = _StubFigure(
                name,
                unavailable=(
                    "stub is not applicable" if name.startswith(("na_", "nd_", "nb_")) else None
                ),
                required_fields=required,
            )
        return stubs[name]

    monkeypatch.setattr(runs_module, "_get_figure", _fake_get)
    return stubs


def test_disabled_config_renders_nothing(tmp_path, patched_registry, runs_module):
    cfg = DisplayConfig(enabled=False, figures=["piezometric_map"])
    out = tmp_path / "figures" / "baseline"
    report = runs_module.render_figures_for_run(_StubRun(), cfg, output_dir=out)
    assert report.written == ()
    assert report.requested == ()
    assert not out.exists()


def test_empty_figures_list_renders_nothing(tmp_path, patched_registry, runs_module):
    cfg = DisplayConfig(enabled=True, figures=[])
    out = tmp_path / "figures" / "baseline"
    report = runs_module.render_figures_for_run(_StubRun(), cfg, output_dir=out)
    assert report.written == ()


def test_writes_one_file_per_figure(tmp_path, patched_registry, runs_module):
    cfg = DisplayConfig(enabled=True, figures=["piezometric_map", "hydrograph"])
    out = tmp_path / "figures" / "baseline"
    report = runs_module.render_figures_for_run(_StubRun(), cfg, output_dir=out)
    assert sorted(p.name for p in report.written) == ["hydrograph.png", "piezometric_map.png"]
    assert all(p.exists() for p in report.written)
    assert report.skipped == ()


@pytest.mark.parametrize("preset", ["default", "print", "dark"])
def test_a_render_leaves_no_global_state_behind(tmp_path, patched_registry, runs_module, preset):
    # One render writes no backend, no style and no figure of the process, so
    # a second render in another thread meets what it would meet alone. A figure
    # that another test left in the worker is not this render's, so only new ones count.
    import matplotlib
    from matplotlib import _pylab_helpers

    backend, rc = matplotlib.get_backend(), dict(matplotlib.rcParams)
    figures_before = set(_pylab_helpers.Gcf.figs)
    cfg = DisplayConfig(enabled=True, figures=["piezometric_map"], preset=preset)
    runs_module.render_figures_for_run(_StubRun(), cfg, output_dir=tmp_path / "figures")
    assert matplotlib.get_backend() == backend
    assert dict(matplotlib.rcParams) == rc
    assert set(_pylab_helpers.Gcf.figs) <= figures_before


def test_a_render_sees_the_style_of_its_preset(tmp_path, patched_registry, runs_module):
    import matplotlib

    seen: list[str] = []

    def plot(sim, *, dpi=150, save_path=None, **kw):
        seen.append(matplotlib.rcParams["axes.facecolor"])

    runs_module._get_figure("hydrograph").plot = plot
    cfg = DisplayConfig(enabled=True, figures=["hydrograph"], preset="dark")
    runs_module.render_figures_for_run(_StubRun(), cfg, output_dir=tmp_path / "figures")
    assert seen == ["#1e1e1e"]


@pytest.mark.parametrize(
    ("snapshot", "expected"),
    [
        (None, None),
        ({"other": 1}, None),
        ({"display": {}}, {}),
        ({"display": {"dpi": 150}}, {}),
        ({"display": {"dpi": 90}}, {"dpi": 90}),
        (
            {"display": {"figures": ["abherve_two_stage_card", "hydrograph"]}},
            {"figures": ["matching_hydrographic_network_card", "hydrograph"]},
        ),
        (
            {"display": {"overrides": {"abherve_two_stage_card": {"parameter": "K"}}}},
            {"overrides": {"matching_hydrographic_network_card": {"parameter": "K"}}},
        ),
    ],
)
def test_a_sealed_display_keeps_what_moved_and_names_a_figure_by_its_current_name(
    snapshot, expected
):
    # A former figure name in a sealed snapshot loads without the renaming
    # warning, which is addressed to the author of a config, not to a reader.
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        written = runs.sealed_display_values(snapshot)
        if written is not None:
            DisplayConfig.model_validate(written)
    assert written == expected


def test_show_gives_the_figures_to_pyplot_and_closes_only_those(monkeypatch):
    import matplotlib.pyplot as plt
    from matplotlib import _pylab_helpers

    from hydromodpy.display.figure import new_subplots

    plt.close("all")  # a figure another test left in the worker is not the user's here
    users = plt.figure()
    mine = [new_subplots()[0], new_subplots()[0]]
    held: list[bool] = []

    def show() -> None:
        figures = [manager.canvas.figure for manager in _pylab_helpers.Gcf.get_all_fig_managers()]
        held.append(all(any(fig is one for one in figures) for fig in mine))

    monkeypatch.setattr(plt, "show", show)
    try:
        runs._show(mine)
        assert held == [True]
        assert plt.get_fignums() == [users.number]
    finally:
        plt.close("all")


def test_unknown_figure_is_rejected_by_config():
    # A typo must fail at config load, where the user can see it, instead of
    # silently producing one figure less at the end of a long run.
    with pytest.raises(ValueError, match="unknown figure"):
        DisplayConfig(enabled=True, figures=["bad_missing", "piezometric_map"])


def test_inapplicable_figure_is_skipped(tmp_path, patched_registry, runs_module):
    # A figure the run cannot feed (no particle process, no calibration) is
    # reported and skipped; the rest of the batch still renders.
    cfg = _skip_config("na_particles", "piezometric_map")
    out = tmp_path / "figures" / "baseline"
    report = runs_module.render_figures_for_run(_StubRun(), cfg, output_dir=out)
    assert [p.name for p in report.written] == ["piezometric_map.png"]
    assert [(s.name, s.reason) for s in report.skipped] == [
        ("na_particles", "stub is not applicable")
    ]


def _skip_config(*figures: str) -> DisplayConfig:
    """Config built with model_construct so stub names bypass the validator."""
    return DisplayConfig.model_construct(
        enabled=True,
        save=True,
        dpi=150,
        preset="default",
        backend="auto",
        show=False,
        on_error="warn",
        cmap="viridis",
        overrides={},
        figures=list(figures),
    )


def test_inapplicable_figure_skip_stays_quiet(
    tmp_path, patched_registry, runs_module, hmp_log_records
):
    # A figure that does not fit the model (no particles, no lake, another
    # solver) is a normal skip: DEBUG only, no console noise.
    runs_module.render_figures_for_run(
        _StubRun(),
        _skip_config("na_particles"),
        output_dir=tmp_path / "figures",
    )
    records = [r for r in hmp_log_records if "na_particles" in r.getMessage()]
    assert [r.levelname for r in records] == ["DEBUG"]


def test_derived_field_without_its_budget_terms_skip_warns(
    tmp_path, patched_registry, runs_module, hmp_log_records
):
    # A derived field is rebuilt on read from budget terms. A run that did not
    # keep them cannot serve it: the skip must be visible, and the message must
    # name the option that keeps the per-cell budget.
    runs_module.render_figures_for_run(
        _StubRun(),
        _skip_config("nd_active_network"),
        output_dir=tmp_path / "figures",
    )
    records = [r for r in hmp_log_records if "nd_active_network" in r.getMessage()]
    assert [r.levelname for r in records] == ["WARNING"]
    assert "[simulation.results] keep_per_cell_budget = true" in records[0].getMessage()


def test_unkept_budget_field_skip_warns(tmp_path, patched_registry, runs_module, hmp_log_records):
    # Re-rendering a gallery on a run that did not keep a raw budget field
    # cannot bring the figure back without a new solve, so the skip names the
    # switch to set instead of vanishing.
    runs_module.render_figures_for_run(
        _StubRun(),
        _skip_config("nb_recharge_map"),
        output_dir=tmp_path / "figures",
    )
    records = [r for r in hmp_log_records if "nb_recharge_map" in r.getMessage()]
    assert [r.levelname for r in records] == ["WARNING"]
    assert "[simulation.results] keep_per_cell_budget = true" in records[0].getMessage()


def test_save_false_skips_filesystem(tmp_path, patched_registry, runs_module):
    cfg = DisplayConfig(enabled=True, save=False, figures=["piezometric_map"])
    out = tmp_path / "figures" / "baseline"
    report = runs_module.render_figures_for_run(_StubRun(), cfg, output_dir=out)
    assert report.written == ()
    # Drawn but not written: the count reports the figure, the filesystem does not.
    assert report.rendered == ("piezometric_map",)
    assert not out.exists()


def test_figure_names_override_shadows_config(tmp_path, patched_registry, runs_module):
    cfg = DisplayConfig(enabled=True, figures=["piezometric_map", "hydrograph"])
    out = tmp_path / "figures" / "baseline"
    report = runs_module.render_figures_for_run(
        _StubRun(),
        cfg,
        output_dir=out,
        figure_names=["hydrograph"],
    )
    assert [p.name for p in report.written] == ["hydrograph.png"]


def test_the_figures_of_a_run_live_in_its_figures_directory(tmp_path, runs_module):
    run_dir = tmp_path / RUNS_DIRNAME / "calib_best"
    assert runs_module.figures_dir_of(run_dir) == run_dir / RUN_FIGURES_DIRNAME


def test_output_dir_is_refused_with_where_figures_go():
    with pytest.raises(ValueError, match=r"runs/<run>/figures/"):
        DisplayConfig(output_dir="plots")


class _PngFigure(_StubFigure):
    """A stub that writes a real PNG, as every figure does."""

    def plot(self, sim, *, dpi: int = 150, save_path: Path | None = None, **kw) -> None:
        from PIL import Image

        self.calls.append((save_path, dpi))
        if save_path is not None:
            Image.new("RGB", (240, 120), "white").save(save_path, format="PNG")


def test_a_figure_of_an_identified_run_is_stamped_and_recorded(tmp_path, monkeypatch, runs_module):
    from datetime import UTC, datetime

    from hydromodpy.results.identity import read_identity_from
    from hydromodpy.results.ledger import Ledger
    from hydromodpy.results.outcome import Outcome, write_outcome

    run_dir = tmp_path / RUNS_DIRNAME / "demo"
    run_dir.mkdir(parents=True)
    write_outcome(
        run_dir,
        Outcome(
            case_id="demo",
            attempt=1,
            attempt_id="a" * 32,
            sim_id="sim-1",
            status="running",
            written_by="worker",
            started_at=datetime.now(UTC),
            host="node",
            pid=1,
        ),
    )
    figures = runs_module.figures_dir_of(run_dir)
    monkeypatch.setattr(runs_module, "_get_figure", lambda name: _PngFigure(name))
    cfg = DisplayConfig(figures=["hydrograph"], show=False, save=True)

    report = runs_module.render_figures_for_run(_StubRun(), cfg, output_dir=figures)

    (written,) = report.written
    identity = read_identity_from(written)
    assert identity is not None and identity.case_id == "demo"
    (entry,) = Ledger.read(figures).entries
    assert (entry.file, entry.producer) == ("hydrograph.png", "display:hydrograph")
    assert entry.identity == identity
    from PIL import Image

    with Image.open(written) as image:
        assert image.size[1] > 120


def test_summary_names_every_requested_figure_that_produced_nothing(
    tmp_path, patched_registry, runs_module
):
    # The per-figure line for an inapplicable figure stays DEBUG, so the batch
    # summary is the only place it can leave a trace. It must name it.
    report = runs_module.render_figures_for_run(
        _StubRun(),
        _skip_config("na_calibration", "piezometric_map"),
        output_dir=tmp_path / "figures",
    )
    summary = report.summary(destination=tmp_path / "figures")

    assert summary.startswith("Rendered 1/2 figure(s)")
    assert "1 skipped: na_calibration (stub is not applicable)" in summary


def test_summary_is_info_when_every_skip_is_inapplicable_by_nature(
    tmp_path, patched_registry, runs_module, hmp_log_records
):
    # A calibration figure on a plain run is not something the user can fix:
    # the showcase lists them on purpose. One milestone line counts them, and
    # the next line, at INFO (--verbose), names each one with its reason.
    report = runs_module.render_figures_for_run(
        _StubRun(),
        _skip_config("na_calibration", "piezometric_map"),
        output_dir=tmp_path / "figures",
    )
    runs_module.log_render_summary(report, destination=tmp_path / "figures")

    records = [r for r in hmp_log_records if "runs" in r.name and r.levelno >= logging.INFO]
    assert [r.levelname for r in records] == ["INFO", "INFO"]
    assert getattr(records[0], MILESTONE_KEY, False) is True
    assert records[0].getMessage().endswith("; 1 not applicable to this run")
    assert getattr(records[1], MILESTONE_KEY, False) is False
    assert "na_calibration (stub is not applicable)" in records[1].getMessage()


def test_summary_is_a_warning_when_a_config_option_would_have_kept_the_figure(
    tmp_path, patched_registry, runs_module, hmp_log_records
):
    # WARNING so the line survives quiet mode: the user can act on it.
    report = runs_module.render_figures_for_run(
        _StubRun(),
        _skip_config("na_calibration", "nd_active_network", "piezometric_map"),
        output_dir=tmp_path / "figures",
    )
    runs_module.log_render_summary(report, destination=tmp_path / "figures")

    assert [s.actionable for s in report.skipped] == [False, True]
    records = [r for r in hmp_log_records if "figure(s)" in r.getMessage()]
    assert [r.levelname for r in records] == ["WARNING"]
    assert "na_calibration" in records[0].getMessage()
    assert "nd_active_network" in records[0].getMessage()


def test_summary_is_a_warning_when_a_figure_failed_to_render(
    tmp_path, patched_registry, runs_module, hmp_log_records
):
    stub = patched_registry.setdefault("piezometric_map", _StubFigure("piezometric_map"))

    def _boom(sim, **kw):
        raise RuntimeError("no data")

    stub.plot = _boom
    report = runs_module.render_figures_for_run(
        _StubRun(), _skip_config("piezometric_map"), output_dir=tmp_path / "figures"
    )
    runs_module.log_render_summary(report, destination=tmp_path / "figures")

    assert report.skipped[0].actionable is True
    records = [r for r in hmp_log_records if "figure(s)" in r.getMessage()]
    assert [r.levelname for r in records] == ["WARNING"]


def test_summary_is_info_when_the_whole_batch_rendered(
    tmp_path, patched_registry, runs_module, hmp_log_records
):
    report = runs_module.render_figures_for_run(
        _StubRun(),
        _skip_config("piezometric_map"),
        output_dir=tmp_path / "figures",
    )
    runs_module.log_render_summary(report, destination=tmp_path / "figures")

    records = [r for r in hmp_log_records if "figure(s)" in r.getMessage()]
    assert [r.levelname for r in records] == ["INFO"]
    assert records[0].getMessage().startswith("Rendered 1/1 figure(s)")


def test_no_summary_when_nothing_was_requested(tmp_path, runs_module, hmp_log_records):
    runs_module.log_render_summary(runs_module.FigureRenderReport(), destination=tmp_path)

    assert [r for r in hmp_log_records if "figure(s)" in r.getMessage()] == []


def test_a_figure_that_fails_to_render_is_reported_in_the_summary(
    tmp_path, patched_registry, runs_module
):
    cfg = _skip_config("piezometric_map")
    stub = patched_registry.setdefault("piezometric_map", _StubFigure("piezometric_map"))

    def _boom(sim, **kw):
        raise RuntimeError("no data")

    stub.plot = _boom
    report = runs_module.render_figures_for_run(_StubRun(), cfg, output_dir=tmp_path / "figures")

    assert report.rendered == ()
    assert [s.name for s in report.skipped] == ["piezometric_map"]
    assert "render failed: no data" in report.summary()


def test_merged_reports_read_as_one_batch(runs_module):
    # The run path renders one figure at a time to advance the progress bar;
    # merging must still produce a single batch summary.
    first = runs_module.FigureRenderReport(requested=("a",), rendered=("a",))
    second = runs_module.FigureRenderReport(
        requested=("b",),
        skipped=(runs_module.SkippedFigure(name="b", reason="no calibration"),),
    )

    merged = first.merged_with(second)

    assert merged.summary() == "Rendered 1/2 figure(s); 1 skipped: b (no calibration)"


def test_one_figure_the_run_cannot_feed_is_refused_with_its_reason(
    tmp_path, patched_registry, runs_module
):
    with pytest.raises(ValueError, match="'na_particles' does not apply to this run: stub is"):
        runs_module.render_figure("na_particles", _StubRun(), save=tmp_path)

    assert patched_registry["na_particles"].calls == []
    assert not (tmp_path / "na_particles.png").exists()


def test_one_figure_gets_its_dpi_and_lands_in_the_directory_it_is_given(
    tmp_path, patched_registry, runs_module
):
    runs_module.render_figure("piezometric_map", _StubRun(), save=tmp_path, dpi=300)

    assert patched_registry["piezometric_map"].calls == [(tmp_path / "piezometric_map.png", 300)]
    assert (tmp_path / "piezometric_map.png").is_file()


def test_the_availability_of_a_run_names_each_figure_and_its_reason(
    monkeypatch, patched_registry, runs_module
):
    monkeypatch.setattr(
        runs_module,
        "_list_figures",
        lambda: [
            FigureSpec(name="piezometric_map", title="piezometric_map"),
            FigureSpec(name="na_particles", title="na_particles"),
        ],
    )

    availability = runs_module.figure_availability(_StubRun())

    assert [(spec.name, reason) for spec, reason in availability] == [
        ("piezometric_map", None),
        ("na_particles", "stub is not applicable"),
    ]
    assert all(stub.calls == [] for stub in patched_registry.values()), "nothing is drawn"


# A figure that finds it does not apply is skipped, even under on_error = "raise".
#
# The composite calibration of example 04 samples K and Sy together. Its promoted
# run lists the figures of a one-parameter search, and the downslope crossing
# raised "this figure reads one calibrated parameter" mid-render, so
# ``on_error = "raise"`` failed the promotion of a search that had converged.

pytestmark = pytest.mark.unit


class _Run:
    sim_id = "11111111-2222-3333-4444-555555555555"
    name = "composite"

    def has_field(self, variable: str, *, subgroup: str | None = None) -> bool:
        del variable, subgroup
        return False


class _OneParameterFigure:
    def __init__(self, name: str) -> None:
        self.spec = FigureSpec(name=name, title=name)

    def unavailable_reason(self, sim) -> str | None:
        del sim
        return None

    def plot(self, sim, *, dpi: int = 150, save_path: Path | None = None, **kw) -> None:
        raise FigureNotApplicable("this figure reads one calibrated parameter")


class _Figure(_OneParameterFigure):
    def plot(self, sim, *, dpi: int = 150, save_path: Path | None = None, **kw) -> None:
        if save_path is not None:
            Path(save_path).write_bytes(b"png")


def _config(*figures: str) -> DisplayConfig:
    return DisplayConfig.model_construct(
        enabled=True,
        save=True,
        dpi=150,
        preset="default",
        backend="auto",
        show=False,
        on_error="raise",
        cmap="viridis",
        overrides={},
        output_dir=RUN_FIGURES_DIRNAME,
        figures=list(figures),
    )


def test_the_batch_skips_it_and_draws_the_rest(tmp_path: Path, monkeypatch) -> None:
    import hydromodpy.display.runs as runs

    figures = {"crossing": _OneParameterFigure("crossing"), "hydrograph": _Figure("hydrograph")}
    monkeypatch.setattr(runs, "_get_figure", figures.__getitem__)

    report = runs.render_figures_for_run(
        _Run(), _config("crossing", "hydrograph"), output_dir=tmp_path
    )

    assert report.rendered == ("hydrograph",)
    assert [s.name for s in report.skipped] == ["crossing"]
    assert "one calibrated parameter" in report.skipped[0].reason


def test_two_sampled_parameters_without_a_name_do_not_apply() -> None:
    table = TrialTable(
        frame=pd.DataFrame({"K": [1e-5, 2e-5], "Sy": [0.05, 0.06]}), parameters=("K", "Sy")
    )

    with pytest.raises(FigureNotApplicable, match="K, Sy"):
        table.parameter_values()
    name, values = table.parameter_values("K")
    assert name == "K"
    assert list(values) == [1e-5, 2e-5]


# A figure names its instant by date, and a date the run does not hold is a skip.
#
# Measured on the Nancon. A pre-release of 2.0 wrote ``timestep = 33`` for October
# 2002 of the monthly run, ``timestep = 1017`` for the same month of the daily
# run, and a calibration phase override ``timestep = 0`` for its steady stage,
# which solves one period over the whole record. Reading step 33 out of a
# one-step store raised inside zarr, and ``on_error = "raise"`` turned a
# converged phase into a failed run.
#
# A date names the period that holds it on every grid: the same ``time`` draws
# the same month on the monthly and the daily run, and the one period of the
# steady stage. A date outside a run is a figure inapplicable to that run,
# skipped with the reason, never a failure.

OCTOBER = "2002-10-15"


class _DatedFigure:
    """A figure that is available and records the options it is drawn with."""

    spec = FigureSpec(name="stub", title="stub")

    def __init__(self) -> None:
        self.drawn: list[dict] = []

    def unavailable_reason(self, _sim) -> None:
        return None

    def plot(self, _sim, *, dpi=150, save_path=None, timestep=None, cmap=None, **_):
        self.drawn.append({"timestep": timestep, "cmap": cmap, **_})


class _Periods(RunPeriods):
    """The real ``run.periods`` lookups over given edges, with no catalog behind."""

    def __init__(self, edges, n_timesteps: int) -> None:
        self.edges = edges
        self._n_timesteps = n_timesteps

    def _count(self) -> int:
        return self._n_timesteps


class _DatedRun:
    """A run as the time selector reads it: its period edges, nothing else.

    ``periods`` holds the real :meth:`RunPeriods.step_at`.
    """

    solver = "modflow6"

    def __init__(self, edges) -> None:
        self.n_timesteps = 1 if edges is None else len(edges) - 1
        self.periods = _Periods(
            None if edges is None else pd.DatetimeIndex(edges), self.n_timesteps
        )

    def has_field(self, _name: str) -> bool:
        return True

    def has_table(self, _name: str) -> bool:
        return True


MONTHLY = pd.date_range("2000-01-01", "2003-01-01", freq="MS")


DAILY = pd.date_range("2000-01-01", "2003-01-01", freq="D")


STEADY = pd.DatetimeIndex(["2000-01-01", "2003-01-01"])


@pytest.fixture
def figure(monkeypatch) -> _DatedFigure:
    stub = _DatedFigure()
    monkeypatch.setattr(_runs, "_get_figure", lambda _name: stub)
    return stub


def _dated_config(**display) -> DisplayConfig:
    display.setdefault("figures", ["seepage_map"])
    return DisplayConfig(enabled=True, on_error="raise", save=False, **display)


@pytest.mark.parametrize(
    ("edges", "expected"),
    [(MONTHLY, 33), (DAILY, 1017), (STEADY, 0)],
    ids=["monthly", "daily", "one-period steady"],
)
def test_one_date_names_the_period_that_holds_it_on_every_grid(
    figure, tmp_path, edges, expected
) -> None:
    report = render_figures_for_run(
        _DatedRun(edges), _dated_config(time=OCTOBER), output_dir=tmp_path
    )

    assert report.rendered == ("seepage_map",)
    drawn = figure.drawn[0]
    assert drawn["timestep"] == expected
    assert "time" not in drawn
    # The same instant on the three grids: the period drawn holds the date.
    assert edges[expected] < pd.Timestamp(OCTOBER) <= edges[expected + 1]


def test_the_steady_stage_draws_the_date_with_no_phase_override(figure, tmp_path) -> None:
    # The two lines a calibration file wrote to undo an index are not needed:
    # the one period of the steady stage covers the whole record.
    cfg = _dated_config(time=OCTOBER, figures=["seepage_map", "cross_section"])

    report = render_figures_for_run(_DatedRun(STEADY), cfg, output_dir=tmp_path)

    assert report.rendered == ("seepage_map", "cross_section")
    assert [d["timestep"] for d in figure.drawn] == [0, 0]


def test_a_date_outside_the_run_is_skipped_with_the_record_it_holds(figure, tmp_path) -> None:
    # A phase window narrower than the record: the date is not in it.
    window = pd.date_range("2001-01-01", "2002-01-01", freq="MS")

    report = render_figures_for_run(
        _DatedRun(window), _dated_config(time=OCTOBER), output_dir=tmp_path
    )

    assert report.rendered == ()
    assert figure.drawn == []
    (skipped,) = report.skipped
    assert skipped.name == "seepage_map"
    assert "2002-10-15" in skipped.reason
    assert "2001-01-01 to 2002-01-01" in skipped.reason
    assert skipped.actionable is False


def test_a_date_on_a_run_without_dates_is_skipped_and_last_still_draws(figure, tmp_path) -> None:
    no_dates = _DatedRun(None)

    dated = render_figures_for_run(no_dates, _dated_config(time=OCTOBER), output_dir=tmp_path)
    last = render_figures_for_run(no_dates, _dated_config(time="last"), output_dir=tmp_path)

    assert "no dates" in dated.skipped[0].reason
    assert last.rendered == ("seepage_map",)
    assert figure.drawn[0]["timestep"] == 0


def test_the_figure_time_wins_over_the_gallery_time(figure, tmp_path) -> None:
    cfg = _dated_config(time=OCTOBER, overrides={"seepage_map": {"time": "first"}})

    render_figures_for_run(_DatedRun(MONTHLY), cfg, output_dir=tmp_path)

    assert figure.drawn[0]["timestep"] == 0


class _Series(_DatedFigure):
    """A figure over the whole record: its plot takes no instant."""

    def plot(self, _sim, *, dpi=150, save_path=None, **_):
        self.drawn.append(dict(_))


def test_the_gallery_time_reaches_only_the_figures_that_draw_one_instant(
    monkeypatch, tmp_path
) -> None:
    # A hydrograph draws the whole record: a gallery date must neither reach
    # it nor skip it on a run that does not hold the date.
    series = _Series()
    monkeypatch.setattr(_runs, "_get_figure", lambda _name: series)
    window = pd.date_range("2001-01-01", "2002-01-01", freq="MS")
    cfg = _dated_config(time=OCTOBER, figures=["hydrograph"])

    report = render_figures_for_run(_DatedRun(window), cfg, output_dir=tmp_path)

    assert report.rendered == ("hydrograph",)
    assert series.drawn == [{}]


def test_an_integer_time_is_a_period_index(figure, tmp_path) -> None:
    cfg = _dated_config(overrides={"seepage_map": {"time": 33}})

    monthly = render_figures_for_run(_DatedRun(MONTHLY), cfg, output_dir=tmp_path)
    steady = render_figures_for_run(_DatedRun(STEADY), cfg, output_dir=tmp_path)

    assert monthly.rendered == ("seepage_map",)
    assert figure.drawn[0]["timestep"] == 33
    # An index names nothing on a run of another length: a skip, not a crash.
    assert steady.rendered == ()
    assert "period index 33 is out of range" in steady.skipped[0].reason


def test_a_skip_by_date_is_not_a_warning(figure, tmp_path) -> None:
    window = pd.date_range("2001-01-01", "2002-01-01", freq="MS")
    report = render_figures_for_run(
        _DatedRun(window), _dated_config(time=OCTOBER), output_dir=tmp_path
    )
    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = records.append
    summary_logger = get_logger("hydromodpy.display.runs")
    previous = summary_logger.level
    summary_logger.setLevel(logging.DEBUG)
    summary_logger.addHandler(handler)
    try:
        log_render_summary(report, destination=tmp_path)
    finally:
        summary_logger.removeHandler(handler)
        summary_logger.setLevel(previous)

    assert [r.levelname for r in records] == ["INFO", "INFO"]
    assert "seepage_map" in records[1].getMessage()


def test_one_figure_resolves_its_date_and_refuses_one_the_run_does_not_hold(figure) -> None:
    # hmp.figure and hmp viz show go through render_figure.
    render_figure("seepage_map", _DatedRun(DAILY), time=OCTOBER)
    assert figure.drawn[0]["timestep"] == 1017

    window = pd.date_range("2001-01-01", "2002-01-01", freq="MS")
    with pytest.raises(ValueError, match="does not apply to this run: time '2002-10-15'"):
        render_figure("seepage_map", _DatedRun(window), time=OCTOBER)


def test_one_figure_refuses_an_option_it_does_not_take(figure) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        with pytest.raises(ValueError, match="has no option 'timestep'.*time"):
            render_figure("seepage_map", _DatedRun(MONTHLY), timestep=33)
    assert figure.drawn == []


# A figure built on the surface outflow is skipped on a model without exit.
#
# A model with no drain, stream, lake or surface excess releases no groundwater
# at the surface, so ``release_flux`` does not exist. The field is rebuilt on
# read, so nothing stops the run: the figure is skipped with that reason, and
# the skip is not actionable, since no option adds an exit to the model.
#
# That holds only when the store proves it: a run that kept the whole budget, or
# every exit term with no array. A run that kept the terms its consumers read
# (``consumers``) may lack the exits because the plan never asked for them, and
# its skip names ``keep_per_cell_budget``.

N_STEPS = 2


N_CELLS = 4


def _seed(
    project: Path,
    budget: dict[str, np.ndarray],
    *,
    policy: str = "all",
    kept_terms: list[str] | None = None,
    edit: Callable[[SimulationZarr], None] | None = None,
) -> str:
    """Write one run with a head and the budget terms given, seal it and return its id.

    ``edit`` changes the field store after the writes, before the seal.
    """
    store = open_run_store(
        project, f"run_{uuid.uuid4().hex[:8]}", n_cells=N_CELLS, n_layers=1, n_timesteps=N_STEPS
    )
    sid = store.sim_id
    sz = store.open_zarr(sid)
    try:
        sz.write_field_stack("head", np.full((N_STEPS, 1, N_CELLS), 120.0))
        for name, values in budget.items():
            sz.write_field_stack(name, values, subgroup="budget")
        if budget:
            # What the extractor declares: the names written under "all", the
            # plan's terms, produced or not, under "consumers".
            terms = sorted(budget) if kept_terms is None else sorted(kept_terms)
            sz.root["budget"].attrs.update({"policy": policy, "kept_terms": terms})
        if edit is not None:
            edit(sz)
    finally:
        sz.close()
    seal_completed(store)
    return sid


def _recharge_only() -> dict[str, np.ndarray]:
    return {"recharge": np.full((N_STEPS, 1, N_CELLS), 1e-5)}


@pytest.fixture
def seeded(tmp_path: Path) -> Iterator[Callable[..., Run]]:
    """Seal a run, index the project and return the run read through the index."""
    project = tmp_path / "p"
    readers: list[Catalog] = []

    def _open(budget: dict[str, np.ndarray], **options: object) -> Run:
        sid = _seed(project, budget, **options)
        rebuild_index(project)
        reader = Catalog(project)
        readers.append(reader)
        return Run(sid, reader)

    yield _open
    for reader in readers:
        reader.close()


def test_a_run_without_an_exit_does_not_serve_the_release_flux(seeded) -> None:
    assert not seeded(_recharge_only()).has_field("release_flux")


def test_the_figure_is_skipped_with_the_physical_reason(seeded, tmp_path, caplog) -> None:
    run = seeded(_recharge_only())
    cfg = DisplayConfig(figures=["downslope_distance_map"], save=False)

    with caplog.at_level(logging.DEBUG, logger="hydromodpy.display.runs"):
        report = runs.render_figures_for_run(run, cfg, output_dir=tmp_path / "figures")

    assert report.rendered == ()
    (skip,) = report.skipped
    assert skip.name == "downslope_distance_map"
    assert "no drain, stream, lake or surface excess" in skip.reason
    assert "release_flux" in skip.reason
    # No results option can add an exit to the model: the skip is not actionable.
    assert not skip.actionable
    assert "keep_per_cell_budget" not in caplog.text


def test_a_drain_only_figure_names_the_drain(seeded) -> None:
    run = seeded(_recharge_only())

    reason = runs.unavailable_reason(runs._get_figure("accumulation_map"), run)

    assert reason is not None
    assert "the model has no drain," in reason
    assert "drain_accumulation_flux" in reason


def test_a_model_with_a_drain_keeps_the_figure_reason(seeded) -> None:
    budget = _recharge_only()
    budget["drain"] = np.full((N_STEPS, 1, N_CELLS), -1e-4)
    run = seeded(budget)

    assert run.has_field("release_flux")
    assert (
        no_surface_exit_reason(run, runs._get_figure("downslope_distance_map").spec.required_fields)
        is None
    )


def test_a_run_without_budget_is_not_judged(seeded) -> None:
    run = seeded({})

    spec = runs._get_figure("downslope_distance_map").spec
    assert no_surface_exit_reason(run, spec.required_fields) is None


def test_a_store_without_attributes_keeps_the_old_reading(seeded) -> None:

    def _drop_attributes(sz: SimulationZarr) -> None:
        for key in ("policy", "kept_terms"):
            del sz.root["budget"].attrs[key]

    run = seeded(_recharge_only(), edit=_drop_attributes)

    spec = runs._get_figure("downslope_distance_map").spec
    assert "no drain, stream, lake or surface excess" in no_surface_exit_reason(
        run, spec.required_fields
    )


def test_a_consumers_run_that_never_kept_the_exits_is_not_a_model_without_exit(
    seeded, tmp_path, caplog
) -> None:
    run = seeded(_recharge_only(), policy="consumers", kept_terms=["recharge"])
    cfg = DisplayConfig(figures=["downslope_distance_map"], save=False)

    spec = runs._get_figure("downslope_distance_map").spec
    assert no_surface_exit_reason(run, spec.required_fields) is None
    with caplog.at_level(logging.DEBUG, logger="hydromodpy.display.runs"):
        report = runs.render_figures_for_run(run, cfg, output_dir=tmp_path / "figures")

    (skip,) = report.skipped
    assert "the model has no" not in skip.reason
    assert skip.actionable
    (record,) = [r for r in caplog.records if "downslope_distance_map" in r.getMessage()]
    assert record.levelno == logging.WARNING
    message = record.getMessage()
    assert "kept only the per-cell budget terms its consumers read (recharge)" in message
    assert "[simulation.results] keep_per_cell_budget = true" in message
    assert "spatial_fields" not in message


def test_a_consumers_run_that_kept_the_exits_without_array_has_no_exit(seeded) -> None:
    run = seeded(
        _recharge_only(),
        policy="consumers",
        kept_terms=["recharge", *budget_terms_for("release_flux")],
    )

    spec = runs._get_figure("downslope_distance_map").spec
    assert "no drain, stream, lake or surface excess" in no_surface_exit_reason(
        run, spec.required_fields
    )


def test_a_consumers_run_that_kept_only_some_exits_stays_actionable(seeded) -> None:
    run = seeded(_recharge_only(), policy="consumers", kept_terms=["recharge", "drain"])

    spec = runs._get_figure("downslope_distance_map").spec
    assert no_surface_exit_reason(run, spec.required_fields) is None


def test_an_all_store_with_no_term_at_all_is_not_judged(seeded) -> None:

    def _declare_no_term(sz: SimulationZarr) -> None:
        sz.root.require_group("budget").attrs.update({"policy": "all", "kept_terms": []})

    run = seeded({}, edit=_declare_no_term)

    spec = runs._get_figure("downslope_distance_map").spec
    assert no_surface_exit_reason(run, spec.required_fields) is None


def test_a_figure_with_only_optional_fields_logs_the_not_kept_skip(
    seeded, tmp_path, caplog
) -> None:
    run = seeded(_recharge_only(), policy="consumers", kept_terms=["recharge"])
    cfg = DisplayConfig(figures=["boundary_package_map"], save=False)

    with caplog.at_level(logging.DEBUG, logger="hydromodpy.display.runs"):
        report = runs.render_figures_for_run(run, cfg, output_dir=tmp_path / "figures")

    (skip,) = report.skipped
    assert skip.actionable
    (record,) = [r for r in caplog.records if "boundary_package_map" in r.getMessage()]
    assert record.levelno == logging.WARNING
    assert ".." not in record.getMessage()
    assert "keep_per_cell_budget = true" in record.getMessage()
