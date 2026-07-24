"""Coverage for ``hydromodpy.display.runs`` - the shared helper used by
both ``hmp display`` and the pipeline ``DisplayStep``.

These tests exercise policy, not rendering:
    * ``enabled=False`` or empty ``figures`` must produce zero output.
    * Unknown figure names are rejected by the config, not at render time.
    * A figure whose requirements the run does not meet is skipped.
    * Written files land in ``<output_dir>/<figure>.png``.
    * ``resolve_run_output_dir`` picks the run name when available and
      falls back to a short sim_id otherwise.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from hydromodpy.core.logging import get_logger
from hydromodpy.display.config import DisplayConfig
from hydromodpy.display.figure import FigureSpec


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
            # run); 'nd_' stubs miss a field a results.derived flag produces;
            # 'nb_' stubs miss a raw budget field the budget switch keeps.
            required: tuple[str, ...] = ()
            if name.startswith("nd_"):
                required = ("accumulation_flux",)
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
        output_dir=Path("figures"),
        figures=list(figures),
    )


@pytest.fixture
def hmp_log_records():
    """Capture ``hydromodpy`` records (the parent logger disables propagation)."""
    parent = get_logger("hydromodpy")
    previous_level = parent.level
    parent.setLevel(logging.DEBUG)
    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = _Capture(level=logging.DEBUG)
    parent.addHandler(handler)
    try:
        yield records
    finally:
        parent.removeHandler(handler)
        parent.setLevel(previous_level)


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


def test_uncomputed_derived_field_skip_warns(
    tmp_path, patched_registry, runs_module, hmp_log_records
):
    # A field only a disabled results.derived flag would have written is a
    # computation the run was asked for and did not do: it must be visible,
    # and the message must name the flag to enable.
    runs_module.render_figures_for_run(
        _StubRun(),
        _skip_config("nd_active_network"),
        output_dir=tmp_path / "figures",
    )
    records = [r for r in hmp_log_records if "nd_active_network" in r.getMessage()]
    assert [r.levelname for r in records] == ["WARNING"]
    assert "accumulation_flux" in records[0].getMessage()


def test_dropped_budget_field_skip_warns(tmp_path, patched_registry, runs_module, hmp_log_records):
    # Re-rendering a gallery on a run whose intermediate per-cell budget was
    # dropped finds no raw budget field. The figure cannot come back without a
    # new solve, so the skip names the switch to set instead of vanishing.
    runs_module.render_figures_for_run(
        _StubRun(),
        _skip_config("nb_recharge_map"),
        output_dir=tmp_path / "figures",
    )
    records = [r for r in hmp_log_records if "nb_recharge_map" in r.getMessage()]
    assert [r.levelname for r in records] == ["WARNING"]
    assert "[simulation.results.budget] spatial_fields = true" in records[0].getMessage()


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


def test_resolve_run_output_dir_prefers_run_name(tmp_path, runs_module):
    cfg = DisplayConfig(output_dir=Path("figures"))
    path = runs_module.resolve_run_output_dir(
        cfg,
        project_root=tmp_path,
        run_name="calib_best",
        sim_id="abcdef1234567890",
    )
    assert path == tmp_path / "figures" / "calib_best"


def test_resolve_run_output_dir_falls_back_to_short_sim_id(tmp_path, runs_module):
    cfg = DisplayConfig(output_dir=Path("figures"))
    path = runs_module.resolve_run_output_dir(
        cfg,
        project_root=tmp_path,
        run_name=None,
        sim_id="abcdef1234567890",
    )
    assert path == tmp_path / "figures" / "abcdef12"


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


def test_summary_is_a_warning_when_a_requested_figure_is_missing(
    tmp_path, patched_registry, runs_module, hmp_log_records
):
    # WARNING so the line survives quiet mode: an output the user asked for
    # and did not get must never disappear.
    report = runs_module.render_figures_for_run(
        _StubRun(),
        _skip_config("na_calibration", "piezometric_map"),
        output_dir=tmp_path / "figures",
    )
    runs_module.log_render_summary(report, destination=tmp_path / "figures")

    records = [r for r in hmp_log_records if "figure(s)" in r.getMessage()]
    assert [r.levelname for r in records] == ["WARNING"]
    assert "na_calibration" in records[0].getMessage()


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
