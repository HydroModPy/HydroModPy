"""Step 13 - auto-render the figures listed in ``[display].figures``, after the seal.

Runs last, after :class:`SealStep` and the exports that follow it. The
figures render the sealed run: they open its store on the run directory, as
``hmp show <run> --figure NAME`` does, for their own span. Each figure declared in the
TOML is written into ``runs/<run>/figures/``, stamped with the identity of
the run (its label of the day, the rules it follows and the date) and
recorded in ``figures/index.json``. A session figure draws the calibration
session that promoted the run.

A figure that fails under ``on_error = "raise"`` leaves the run sealed and
``completed``: the step raises :class:`~hydromodpy.core.exceptions.DisplayError`
naming ``hmp show <run> --figure <figure>``, which draws it again.

Skipped silently when ``display.enabled`` is false, when ``display.figures``
is empty, when the run is a kept calibration trial (the ``research`` level,
which draws nothing), or when the pipeline was set to headless via
``state.data["skip_display"]`` (honored by the CLI ``--no-display`` flag).

Inputs
------
``ctx`` : WorkflowContext - provides ``sim_id``, ``cfg.display``, workspace.

Outputs
-------
``state`` unchanged aside from the usual ``advance(...)`` bookkeeping. The
rendered file paths are attached via ``state.data["rendered_figures"]`` for
downstream tooling/tests.
"""

from __future__ import annotations

from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from hydromodpy.core.console import progress
from hydromodpy.core.exceptions import ConfigError, DisplayError
from hydromodpy.core.logging import get_logger
from hydromodpy.core.runtime.stopwatch import Measure, measured
from hydromodpy.results.storage.kept import renders
from hydromodpy.workflow.record.run_store import run_is_persisted
from hydromodpy.workflow.runner import record_measure
from hydromodpy.workflow.state import PipelineState

if TYPE_CHECKING:
    from collections.abc import Callable

    from hydromodpy.display.config import DisplayConfig
    from hydromodpy.results.run import Run

logger = get_logger(__name__)


def _render_figures_tracked(
    run: Run,
    display_cfg: DisplayConfig,
    *,
    output_dir: Path,
    figure_names: list[str],
    on_measure: Callable[[Measure], None] | None = None,
    run_name: str | None = None,
) -> list[Path]:
    """Render figures one at a time so the progress bar advances per figure.

    Individual figures log nothing on success (a skip or a per-figure failure
    warning aside); this emits a single summary line for the whole batch,
    naming every requested figure that produced nothing. ``on_measure`` receives
    the time of each figure once it ends, a figure that failed included.
    ``run_name`` names a sealed run: a figure that raises is raised again as a
    :class:`DisplayError` that says the run is sealed and how to draw the
    figure again.
    """
    from hydromodpy.display.runs import (
        FigureRenderReport,
        log_render_summary,
        render_figures_for_run,
    )

    report = FigureRenderReport()
    for figure_name in progress.track(figure_names, "Rendering figures"):
        try:
            with measured("figure", figure_name) as measure:
                report = report.merged_with(
                    render_figures_for_run(
                        run,
                        display_cfg,
                        output_dir=output_dir,
                        figure_names=[figure_name],
                    )
                )
        except Exception as exc:
            if on_measure is not None:
                on_measure(measure)
            if run_name is None:
                raise
            raise DisplayError(
                f"run {run_name} is sealed; draw the figure again with "
                f"hmp show {run_name} --figure {figure_name}: {exc}"
            ) from exc
        if on_measure is not None:
            on_measure(measure)
    log_render_summary(report, destination=output_dir)
    return list(report.written)


class DisplayStep:
    """Render the figures declared in ``[display].figures`` from the sealed run."""

    name = "display"
    reads: ClassVar[tuple[str, ...]] = (
        "ctx",
        "skip_display",
    )
    writes: ClassVar[tuple[str, ...]] = (
        "ctx",
        "rendered_figures",
    )
    config_sections: ClassVar[tuple[str, ...]] = ("display",)

    def depends_on(self) -> tuple[str, ...]:
        return ("seal",)

    def rebuild_state(
        self,
        *,
        prior_state: PipelineState,
        workspace: Path,
        run_id: str,
    ) -> PipelineState:
        """List the figures ``figures/index.json`` of the run records."""
        from hydromodpy.display.runs import figures_dir_of
        from hydromodpy.results.ledger import Ledger

        ctx = prior_state.get("ctx")
        if ctx is None:
            raise ConfigError("DisplayStep.rebuild_state requires 'ctx' in state.data")
        rendered: list[Path] = []
        run_dir = getattr(ctx, "run_dir", None)
        if run_dir is not None:
            figures_dir = figures_dir_of(Path(run_dir))
            rendered = [figures_dir / entry.file for entry in Ledger.read(figures_dir).entries]
        return prior_state.advance(
            step_index=prior_state.step_index + 1,
            step_name=self.name,
            ctx=ctx,
            rendered_figures=rendered,
        )

    def run(self, state: PipelineState) -> PipelineState:
        from hydromodpy.display.runs import figures_dir_of

        ctx = state.get("ctx")
        if ctx is None:
            raise ConfigError("DisplayStep requires 'ctx' in state.data")

        rendered: list = []

        if state.get("skip_display"):
            logger.info("DisplayStep skipped (skip_display=True)")
        else:
            display_cfg = getattr(ctx.cfg, "display", None)
            sim_id = getattr(ctx, "sim_id", None)
            if display_cfg is None or sim_id is None or not run_is_persisted(ctx):
                logger.debug("DisplayStep: no display config, no sim_id or no store, skipping")
            elif not renders(getattr(ctx, "level", None) or "result"):
                logger.info("DisplayStep skipped: a kept calibration trial draws nothing")
            elif not display_cfg.enabled or not display_cfg.figures:
                # At info, not debug: a run that draws nothing looks exactly
                # like a run whose figure list silently emptied, and the second
                # one is a real accident. In TOML a table header swallows every
                # key below it, so a `[display.overrides.<fig>]` written above
                # `figures` takes the list with it and nothing warns.
                logger.info(
                    "No figure rendered: [display] enabled = %s, figures lists %d name(s).",
                    display_cfg.enabled,
                    len(display_cfg.figures),
                )
            else:
                from hydromodpy.results.run import Run
                from hydromodpy.workflow.steps.export import sealed_run_name, sealed_run_store

                run_dir = Path(ctx.run_dir)
                with sealed_run_store(ctx) as store:
                    sim = Run(sim_id, store)
                    out_dir = figures_dir_of(run_dir)
                    rendered = _render_figures_tracked(
                        sim,
                        display_cfg,
                        output_dir=out_dir,
                        figure_names=list(display_cfg.figures),
                        on_measure=partial(record_measure, ctx.run_dir, attempt=ctx.attempt),
                        run_name=sealed_run_name(run_dir),
                    )
                if rendered:
                    logger.debug(
                        "DisplayStep rendered %d figure(s) in %s",
                        len(rendered),
                        out_dir,
                    )

        return state.advance(
            step_index=state.step_index + 1,
            step_name=self.name,
            ctx=ctx,
            rendered_figures=rendered,
        )
