"""Per-run figure rendering helpers.

Bridges :class:`~hydromodpy.results.run.Run` and the figure registry in
:mod:`hydromodpy.display`. Saving and showing are driven by
``DisplayConfig`` (TOML ``[display]`` section).

Rendering reports what it did through :class:`FigureRenderReport` rather than
a bare list of files: a figure the user asked for and did not get is an output
that must stay visible. Per-figure logging keeps its gradation (a skip a config
option can unblock is a WARNING, a figure inapplicable by nature is DEBUG), and
the batch summary always names every requested figure that produced nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from hydromodpy.core.logging import get_logger
from hydromodpy.display import get as _get_figure
from hydromodpy.display.renderer import matplotlib_backend
from hydromodpy.display.theme import apply_theme

if TYPE_CHECKING:
    from hydromodpy.display.config import DisplayConfig
    from hydromodpy.display.figure import BaseFigure
    from hydromodpy.results.run import Run

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class SkippedFigure:
    """One requested figure that produced nothing, and the short reason why."""

    name: str
    reason: str


@dataclass(frozen=True, slots=True)
class FigureRenderReport:
    """What one rendering pass asked for, drew, wrote and skipped.

    ``rendered`` counts the figures actually drawn, which is not
    ``len(written)``: ``display.save = false`` draws without writing a file.
    ``skipped`` holds every requested figure that produced nothing, whether it
    was inapplicable to the run or failed while rendering.
    """

    requested: tuple[str, ...] = ()
    rendered: tuple[str, ...] = ()
    written: tuple[Path, ...] = ()
    skipped: tuple[SkippedFigure, ...] = ()

    def merged_with(self, other: FigureRenderReport) -> FigureRenderReport:
        """Concatenate two passes so a per-figure loop reports as one batch."""
        return FigureRenderReport(
            requested=self.requested + other.requested,
            rendered=self.rendered + other.rendered,
            written=self.written + other.written,
            skipped=self.skipped + other.skipped,
        )

    def summary(self, *, destination: Path | None = None) -> str:
        """One line: the rendered count, then every figure not produced."""
        line = f"Rendered {len(self.rendered)}/{len(self.requested)} figure(s)"
        if destination is not None:
            line = f"{line} -> {destination}"
        if self.skipped:
            detail = ", ".join(f"{item.name} ({item.reason})" for item in self.skipped)
            line = f"{line}; {len(self.skipped)} skipped: {detail}"
        return line


def log_render_summary(
    report: FigureRenderReport,
    *,
    destination: Path | None = None,
) -> None:
    """Log the batch summary of one rendering pass.

    WARNING when a requested figure produced nothing, so the line survives
    ``quiet`` mode: an output the user asked for and did not get must never
    disappear. INFO when the whole batch was rendered.
    """
    if not report.requested:
        return
    level = logger.warning if report.skipped else logger.info
    level("%s", report.summary(destination=destination))


def _backend_is_interactive(display_cfg: DisplayConfig) -> bool:
    backend = str(getattr(display_cfg, "backend", "auto") or "auto").lower()
    if backend == "auto":
        return bool(display_cfg.show)
    return backend != "agg"


def _figure_options(display_cfg: DisplayConfig, figure_name: str) -> dict:
    """Build the keyword options passed to one figure.

    The project-wide ``cmap`` is forwarded only when the user actually set
    it. Injecting the schema default would override each figure's own
    colormap, which is chosen for the physics it shows (a reversed scale for
    a depth, a discrete one for an indicator).
    """
    options: dict = {}
    if "cmap" in display_cfg.model_fields_set:
        options["cmap"] = display_cfg.cmap
    options.update(dict(display_cfg.overrides.get(figure_name, {})))
    return options


def _log_skipped_figure(name: str, fig: BaseFigure, sim: Run, reason: str) -> None:
    """Log one skipped figure, loudly when a field it needs was not kept."""
    from hydromodpy.results.derive.config_flags import (
        enable_options_hint,
        missing_field_options,
    )

    options = missing_field_options(fig.spec.required_fields, sim)
    if options:
        logger.warning(
            "Figure '%s' skipped: %s. %s",
            name,
            reason,
            enable_options_hint(options),
        )
        return
    # A figure inapplicable by nature (no calibration, no particles, another
    # solver) is a normal skip: DEBUG here, and always named in the batch
    # summary so it never disappears entirely.
    logger.debug("Figure '%s' not applicable to this run: %s.", name, reason)


def render_figure(
    figure_name: str,
    sim: Run,
    *,
    save: str | Path | None = None,
) -> None:
    """Render one figure registered in :mod:`hydromodpy.display`.

    ``save`` may be a directory (one ``<figure_name>.png`` is written into
    it) or a full file path.
    """
    fig = _get_figure(figure_name)
    save_path: Path | None
    if save is None:
        save_path = None
    else:
        target = Path(save)
        # Treat suffix-less paths as a directory; anything with an extension
        # is a complete file path the caller wants honoured verbatim.
        save_path = target / f"{figure_name}.png" if target.suffix == "" else target
    fig.plot(sim, save_path=save_path)


def resolve_run_output_dir(
    display_cfg: DisplayConfig,
    *,
    project_root: Path,
    run_name: str | None,
    sim_id: str,
) -> Path:
    """Return the directory where figures for one run should be saved.

    Layout: ``<project_root>/<display.output_dir>/<run_label>/`` where
    ``run_label`` is the run name when available, falling back to the
    short sim_id. Keeping one folder per run prevents figures from
    different runs overwriting each other.
    """
    base = project_root / display_cfg.output_dir
    label = run_name if run_name else sim_id[:8]
    return base / label


def render_figures_for_run(
    sim: Run,
    display_cfg: DisplayConfig,
    *,
    output_dir: Path,
    figure_names: list[str] | None = None,
) -> FigureRenderReport:
    """Render the figures listed in ``display_cfg`` for one :class:`Run`.

    Honors ``display_cfg.enabled`` and ``display_cfg.save``. A figure whose
    declared requirements are not met by this run (no particle process, no
    calibration, a solver that does not produce the field) is reported as
    not applicable and skipped. A figure that fails while rendering raises
    or is logged depending on ``display_cfg.on_error``. Returns the
    :class:`FigureRenderReport` of the pass: the caller owns the summary, so
    a per-figure loop can render one at a time and still report as one batch.
    """
    if not display_cfg.enabled:
        return FigureRenderReport()

    wanted = figure_names if figure_names is not None else list(display_cfg.figures)
    if not wanted:
        return FigureRenderReport()

    rendered: list[str] = []
    written: list[Path] = []
    skipped: list[SkippedFigure] = []
    output_dir = Path(output_dir)
    if display_cfg.save:
        output_dir.mkdir(parents=True, exist_ok=True)

    with matplotlib_backend(interactive=_backend_is_interactive(display_cfg), dpi=display_cfg.dpi):
        apply_theme(display_cfg.preset)
        for name in wanted:
            fig = _get_figure(name)
            reason = fig.unavailable_reason(sim)
            if reason is not None:
                _log_skipped_figure(name, fig, sim, reason)
                skipped.append(SkippedFigure(name=name, reason=reason))
                continue
            save_path = output_dir / f"{name}.png" if display_cfg.save else None
            try:
                fig.plot(
                    sim,
                    dpi=display_cfg.dpi,
                    save_path=save_path,
                    **_figure_options(display_cfg, name),
                )
            except Exception as exc:
                # One line per figure that fails, at WARNING so it is visible.
                if display_cfg.on_error == "raise":
                    raise
                logger.warning("Figure '%s' failed to render: %s", name, exc)
                skipped.append(SkippedFigure(name=name, reason=f"render failed: {exc}"))
                continue
            rendered.append(name)
            if display_cfg.show:
                import matplotlib.pyplot as plt

                plt.show()
            if save_path is not None:
                written.append(save_path)
                logger.debug("Rendered figure '%s' -> %s", name, save_path)
    return FigureRenderReport(
        requested=tuple(wanted),
        rendered=tuple(rendered),
        written=tuple(written),
        skipped=tuple(skipped),
    )
