"""The shared helper behind ``hmp display`` and the pipeline display step.

The tests check policy, not rendering. A disabled gallery writes nothing, a figure
the run cannot serve is skipped with its reason, a date names the period that holds
it, and a model with no surface exit skips the figures that read the release flux.
"""

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
from hydromodpy.core.state.layout import RUNS_DIRNAME
from hydromodpy.display import runs
from hydromodpy.display.config import DisplayConfig
from hydromodpy.display.figure import FigureNotApplicable, FigureSpec
from hydromodpy.display.figures._trial_diagnostics import TrialTable
from hydromodpy.display.runs import render_figure, render_figures_for_run
from hydromodpy.results.catalog.facade import Catalog
from hydromodpy.results.catalog.indexer import rebuild_index
from hydromodpy.results.derive.config_flags import no_surface_exit_reason
from hydromodpy.results.run.periods import RunPeriods
from hydromodpy.results.run.view import Run
from hydromodpy.results.storage.contract import RUN_FIGURES_DIRNAME
from hydromodpy.results.storage.sealing import seal_completed
from hydromodpy.results.zarr_store.simulation_zarr import SimulationZarr
from tests._helpers.run_stores import open_run_store


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
def patched_registry(monkeypatch):
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

    monkeypatch.setattr(runs, "_get_figure", _fake_get)
    return stubs


NOTHING_TO_DRAW = [
    pytest.param(DisplayConfig(enabled=False, figures=["piezometric_map"]), id="disabled"),
    pytest.param(DisplayConfig(enabled=True, figures=[]), id="no figure"),
]


@pytest.mark.parametrize("cfg", NOTHING_TO_DRAW)
def test_nothing_rendered(cfg, tmp_path, patched_registry):
    out = tmp_path / "figures" / "baseline"

    report = runs.render_figures_for_run(_StubRun(), cfg, output_dir=out)

    assert report.written == ()
    assert report.requested == ()
    assert not out.exists()


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
def test_sealed_display_values(snapshot, expected):
    # A former figure name in a sealed snapshot loads without the renaming
    # warning, which is addressed to the author of a config, not to a reader.
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        written = runs.sealed_display_values(snapshot)
        if written is not None:
            DisplayConfig.model_validate(written)
    assert written == expected


def test_show_closes_own_figures(monkeypatch):
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


def test_unknown_figure_refused():
    # A typo must fail at config load, where the user can see it, instead of
    # silently producing one figure less at the end of a long run.
    with pytest.raises(ValueError, match="unknown figure"):
        DisplayConfig(enabled=True, figures=["bad_missing", "piezometric_map"])


def _config(*figures: str, on_error: str = "warn") -> DisplayConfig:
    """Built with model_construct so stub names bypass the validator."""
    return DisplayConfig.model_construct(
        enabled=True,
        save=True,
        dpi=150,
        preset="default",
        backend="auto",
        show=False,
        on_error=on_error,
        cmap="viridis",
        overrides={},
        output_dir=RUN_FIGURES_DIRNAME,
        figures=list(figures),
    )


# A derived field is rebuilt on read from budget terms, and a raw budget field is
# kept or not by a switch. A run that kept neither cannot serve the figure, so the
# skip must be visible and must name the option that keeps the per-cell budget.
UNKEPT_FIELDS = ["nd_active_network", "nb_recharge_map"]


@pytest.mark.parametrize("figure", UNKEPT_FIELDS)
def test_unkept_budget_warns(figure, tmp_path, patched_registry, hmp_log_records):
    runs.render_figures_for_run(_StubRun(), _config(figure), output_dir=tmp_path / "figures")

    records = [r for r in hmp_log_records if figure in r.getMessage()]
    assert [r.levelname for r in records] == ["WARNING"]
    assert "[simulation.results] keep_per_cell_budget = true" in records[0].getMessage()


class _PngFigure(_StubFigure):
    """A stub that writes a real PNG, as every figure does."""

    def plot(self, sim, *, dpi: int = 150, save_path: Path | None = None, **kw) -> None:
        from PIL import Image

        self.calls.append((save_path, dpi))
        if save_path is not None:
            Image.new("RGB", (240, 120), "white").save(save_path, format="PNG")


def test_figure_stamped_and_recorded(tmp_path, monkeypatch):
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
    figures = runs.figures_dir_of(run_dir)
    monkeypatch.setattr(runs, "_get_figure", lambda name: _PngFigure(name))
    cfg = DisplayConfig(figures=["hydrograph"], show=False, save=True)

    report = runs.render_figures_for_run(_StubRun(), cfg, output_dir=figures)

    (written,) = report.written
    identity = read_identity_from(written)
    assert identity is not None and identity.case_id == "demo"
    (entry,) = Ledger.read(figures).entries
    assert (entry.file, entry.producer) == ("hydrograph.png", "display:hydrograph")
    assert entry.identity == identity
    from PIL import Image

    with Image.open(written) as image:
        assert image.size[1] > 120


def test_summary_inapplicable(tmp_path, patched_registry, hmp_log_records):
    # A calibration figure on a plain run is not something the user can fix:
    # the showcase lists them on purpose. One milestone line counts them, and
    # the next line, at INFO (--verbose), names each one with its reason.
    report = runs.render_figures_for_run(
        _StubRun(),
        _config("na_calibration", "piezometric_map"),
        output_dir=tmp_path / "figures",
    )
    runs.log_render_summary(report, destination=tmp_path / "figures")

    records = [r for r in hmp_log_records if "runs" in r.name and r.levelno >= logging.INFO]
    assert [r.levelname for r in records] == ["INFO", "INFO"]
    assert getattr(records[0], MILESTONE_KEY, False) is True
    assert records[0].getMessage().endswith("; 1 not applicable to this run")
    assert getattr(records[1], MILESTONE_KEY, False) is False
    assert "na_calibration (stub is not applicable)" in records[1].getMessage()


def test_summary_actionable(tmp_path, patched_registry, hmp_log_records):
    # WARNING so the line survives quiet mode: the user can act on it.
    report = runs.render_figures_for_run(
        _StubRun(),
        _config("na_calibration", "nd_active_network", "piezometric_map"),
        output_dir=tmp_path / "figures",
    )
    runs.log_render_summary(report, destination=tmp_path / "figures")

    assert [s.actionable for s in report.skipped] == [False, True]
    records = [r for r in hmp_log_records if "figure(s)" in r.getMessage()]
    assert [r.levelname for r in records] == ["WARNING"]
    assert "na_calibration" in records[0].getMessage()
    assert "nd_active_network" in records[0].getMessage()


def test_no_summary_when_empty(tmp_path, hmp_log_records):
    runs.log_render_summary(runs.FigureRenderReport(), destination=tmp_path)

    assert [r for r in hmp_log_records if "figure(s)" in r.getMessage()] == []


def test_failed_figure_summary(tmp_path, patched_registry):
    cfg = _config("piezometric_map")
    stub = patched_registry.setdefault("piezometric_map", _StubFigure("piezometric_map"))

    def _boom(sim, **kw):
        raise RuntimeError("no data")

    stub.plot = _boom
    report = runs.render_figures_for_run(_StubRun(), cfg, output_dir=tmp_path / "figures")

    assert report.rendered == ()
    assert [s.name for s in report.skipped] == ["piezometric_map"]
    assert "render failed: no data" in report.summary()


def test_merged_reports():
    # The run path renders one figure at a time to advance the progress bar;
    # merging must still produce a single batch summary.
    first = runs.FigureRenderReport(requested=("a",), rendered=("a",))
    second = runs.FigureRenderReport(
        requested=("b",),
        skipped=(runs.SkippedFigure(name="b", reason="no calibration"),),
    )

    merged = first.merged_with(second)

    assert merged.summary() == "Rendered 1/2 figure(s); 1 skipped: b (no calibration)"


def test_one_figure_dpi_folder(tmp_path, patched_registry):
    runs.render_figure("piezometric_map", _StubRun(), save=tmp_path, dpi=300)

    assert patched_registry["piezometric_map"].calls == [(tmp_path / "piezometric_map.png", 300)]
    assert (tmp_path / "piezometric_map.png").is_file()


def test_figure_availability(monkeypatch, patched_registry):
    monkeypatch.setattr(
        runs,
        "_list_figures",
        lambda: [
            FigureSpec(name="piezometric_map", title="piezometric_map"),
            FigureSpec(name="na_particles", title="na_particles"),
        ],
    )

    availability = runs.figure_availability(_StubRun())

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


def test_batch_skips_inapplicable(tmp_path: Path, monkeypatch) -> None:
    figures = {"crossing": _OneParameterFigure("crossing"), "hydrograph": _Figure("hydrograph")}
    monkeypatch.setattr(runs, "_get_figure", figures.__getitem__)

    report = runs.render_figures_for_run(
        _StubRun(), _config("crossing", "hydrograph", on_error="raise"), output_dir=tmp_path
    )

    assert report.rendered == ("hydrograph",)
    assert [s.name for s in report.skipped] == ["crossing"]
    assert "one calibrated parameter" in report.skipped[0].reason


def test_two_parameters_need_name() -> None:
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


@pytest.fixture
def figure(monkeypatch) -> _DatedFigure:
    stub = _DatedFigure()
    monkeypatch.setattr(runs, "_get_figure", lambda _name: stub)
    return stub


def _dated_config(**display) -> DisplayConfig:
    display.setdefault("figures", ["seepage_map"])
    return DisplayConfig(enabled=True, on_error="raise", save=False, **display)


def test_date_without_run_dates(figure, tmp_path) -> None:
    no_dates = _DatedRun(None)

    dated = render_figures_for_run(no_dates, _dated_config(time=OCTOBER), output_dir=tmp_path)
    last = render_figures_for_run(no_dates, _dated_config(time="last"), output_dir=tmp_path)

    assert "no dates" in dated.skipped[0].reason
    assert last.rendered == ("seepage_map",)
    assert figure.drawn[0]["timestep"] == 0


def test_figure_time_wins(figure, tmp_path) -> None:
    cfg = _dated_config(time=OCTOBER, overrides={"seepage_map": {"time": "first"}})

    render_figures_for_run(_DatedRun(MONTHLY), cfg, output_dir=tmp_path)

    assert figure.drawn[0]["timestep"] == 0


def test_one_figure_date(figure) -> None:
    # hmp.figure and hmp viz show go through render_figure.
    render_figure("seepage_map", _DatedRun(DAILY), time=OCTOBER)
    assert figure.drawn[0]["timestep"] == 1017

    window = pd.date_range("2001-01-01", "2002-01-01", freq="MS")
    with pytest.raises(ValueError, match="does not apply to this run: time '2002-10-15'"):
        render_figure("seepage_map", _DatedRun(window), time=OCTOBER)


def test_one_figure_option_refused(figure) -> None:
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


def test_drain_figure_reason(seeded) -> None:
    run = seeded(_recharge_only())

    reason = runs.unavailable_reason(runs._get_figure("accumulation_map"), run)

    assert reason is not None
    assert "the model has no drain," in reason
    assert "drain_accumulation_flux" in reason


def test_model_with_a_drain(seeded) -> None:
    budget = _recharge_only()
    budget["drain"] = np.full((N_STEPS, 1, N_CELLS), -1e-4)
    run = seeded(budget)

    assert run.has_field("release_flux")
    assert (
        no_surface_exit_reason(run, runs._get_figure("downslope_distance_map").spec.required_fields)
        is None
    )


def test_run_without_budget(seeded) -> None:
    run = seeded({})

    spec = runs._get_figure("downslope_distance_map").spec
    assert no_surface_exit_reason(run, spec.required_fields) is None


def test_consumers_without_exits(seeded, tmp_path, caplog) -> None:
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


def test_consumers_with_exit_terms(seeded) -> None:
    run = seeded(
        _recharge_only(),
        policy="consumers",
        kept_terms=["recharge", *budget_terms_for("release_flux")],
    )

    spec = runs._get_figure("downslope_distance_map").spec
    assert "no drain, stream, lake or surface excess" in no_surface_exit_reason(
        run, spec.required_fields
    )


def test_optional_fields_not_kept(seeded, tmp_path, caplog) -> None:
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
