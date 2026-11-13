"""Step 13 - draw the ``[[display.figure]]`` tables of the config, after the seal.

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

Skipped silently when ``display.enabled`` is false, when ``display.figure``
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
from hydromodpy.core.pipeline_steps import FIGURE_STEPS
from hydromodpy.core.runtime.stopwatch import Measure
from hydromodpy.display.request import AFTER
from hydromodpy.results.storage.kept import renders
from hydromodpy.workflow.record.run_store import run_is_persisted, run_store
from hydromodpy.workflow.runner import record_measure
from hydromodpy.workflow.state import PipelineState

if TYPE_CHECKING:
    from collections.abc import Callable

    from hydromodpy.display.config import DisplayConfig
    from hydromodpy.results.run.view import Run

logger = get_logger(__name__)


def _render_requests(
    run: Run,
    display_cfg: DisplayConfig,
    *,
    output_dir: Path,
    on_measure: Callable[[Measure], None] | None = None,
    run_name: str | None = None,
) -> list[Path]:
    """Draw each ``[[display.figure]]`` of ``when = "end"``: one render and one write each.

    A figure that does not apply to the run is logged and skipped. Any other failure follows ``on_error``, with the same sealed-run message.
    """
    if not display_cfg.figure:
        return []
    from hydromodpy.display.presets import PRESETS
    from hydromodpy.display.request import file_stem
    from hydromodpy.display.runs import display_theme, draw_requests

    presets = {**PRESETS, **display_cfg.presets}
    theme = display_theme(display_cfg)
    written: list[Path] = []
    for request in progress.track(display_cfg.figure, "Rendering figures"):
        try:
            report = draw_requests(
                run,
                [request],
                presets=presets,
                theme=theme,
                output_dir=output_dir,
                on_error=display_cfg.on_error,
                on_measure=on_measure,
            )
        except Exception as exc:
            if run_name is None:
                raise
            stem = file_stem(request)
            raise DisplayError(
                f"run {run_name} is sealed; draw the figure again with "
                f"hmp show {run_name} --figure {stem}: {exc}"
            ) from exc
        written.extend(report.written)
    return written


def _display_config(state: PipelineState) -> DisplayConfig | None:
    """Return the ``[display]`` section when this run draws figures, else None and say why."""
    ctx = state.get("ctx")
    if state.get("skip_display"):
        logger.info("DisplayStep skipped (skip_display=True)")
        return None
    display_cfg = getattr(ctx.cfg, "display", None)
    if display_cfg is None or getattr(ctx, "sim_id", None) is None or not run_is_persisted(ctx):
        logger.debug("DisplayStep: no display config, no sim_id or no store, skipping")
        return None
    if not renders(getattr(ctx, "level", None) or "result"):
        logger.info("DisplayStep skipped: a kept calibration trial draws nothing")
        return None
    if not display_cfg.enabled or not display_cfg.figure:
        # At info, not debug: a run that draws nothing looks exactly like a
        # run whose figure list silently emptied.
        logger.info(
            "No figure rendered: [display] enabled = %s, %d [[display.figure]] table(s).",
            display_cfg.enabled,
            len(display_cfg.figure),
        )
        return None
    return display_cfg


def draw_after(state: PipelineState, step: str) -> list[Path]:
    """Draw the figures of ``when = "after:<step>"`` from the run as written so far.

    Only a step of ``FIGURE_STEPS`` has its results on disk, so any other step returns
    at once without opening the store. The run is not sealed yet, so a figure never
    fails it: ``on_error`` is always ``warn``, and ``hmp show`` draws the figure again.
    """
    ctx = state.get("ctx")
    when = AFTER + step
    asked = getattr(getattr(getattr(ctx, "cfg", None), "display", None), "figure", None) or ()
    if step not in FIGURE_STEPS or not any(getattr(r, "when", None) == when for r in asked):
        return []
    display_cfg = _display_config(state)
    if display_cfg is None:
        return []
    from hydromodpy.display.presets import PRESETS
    from hydromodpy.display.runs import display_theme, draw_requests, figures_dir_of
    from hydromodpy.results.run.view import Run

    with run_store(ctx) as store:
        report = draw_requests(
            Run(ctx.sim_id, store),
            display_cfg.figure,
            presets={**PRESETS, **display_cfg.presets},
            theme=display_theme(display_cfg),
            output_dir=figures_dir_of(Path(ctx.run_dir)),
            on_error="warn",
            on_measure=partial(record_measure, ctx.run_dir, attempt=ctx.attempt),
            when=when,
        )
    return list(report.written)


class DisplayStep:
    """Draw the figures declared in ``[[display.figure]]`` from the sealed run."""

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
        display_cfg = _display_config(state)
        if display_cfg is not None:
            from hydromodpy.results.run.view import Run
            from hydromodpy.workflow.steps.export import sealed_run_name, sealed_run_store

            run_dir = Path(ctx.run_dir)
            with sealed_run_store(ctx) as store:
                sim = Run(ctx.sim_id, store)
                out_dir = figures_dir_of(run_dir)
                on_measure = partial(record_measure, ctx.run_dir, attempt=ctx.attempt)
                rendered = _render_requests(
                    sim,
                    display_cfg,
                    output_dir=out_dir,
                    on_measure=on_measure,
                    run_name=sealed_run_name(run_dir),
                )
            if rendered:
                logger.debug("DisplayStep rendered %d figure(s) in %s", len(rendered), out_dir)

        return state.advance(
            step_index=state.step_index + 1,
            step_name=self.name,
            ctx=ctx,
            rendered_figures=rendered,
        )
