"""Per-run figure rendering helpers.

Bridges :class:`~hydromodpy.results.run.Run` and the figure registry in
:mod:`hydromodpy.display`. Saving and showing are driven by
``DisplayConfig`` (TOML ``[display]`` section).

Rendering reports what it did through :class:`FigureRenderReport` rather than
a bare list of files: a figure the user asked for and did not get is an output
that must stay visible. Per-figure logging keeps its gradation (a skip a config
option can unblock is a WARNING, a figure inapplicable by nature is DEBUG), and
the batch summary always names every requested figure that produced nothing:
at WARNING when the user can act on one of them, at INFO otherwise.

A figure that draws one instant is asked for it by ``time``: a date, "first"
or "last". :func:`_resolve_time` turns it into the stress period this run
stored, the one place a date meets a run, so the same date names the same
month on a monthly, a daily or a one-period steady run.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hydromodpy.core.logging import get_logger
from hydromodpy.core.progress import MILESTONE
from hydromodpy.core.state.paths import display_path
from hydromodpy.core.time.selection import TimeSelectionError
from hydromodpy.display import get as _get_figure
from hydromodpy.display import list_figures as _list_figures
from hydromodpy.display.figure import FigureNotApplicable
from hydromodpy.display.style import apply_theme

if TYPE_CHECKING:
    from matplotlib.figure import Figure as MplFigure

    from hydromodpy.display.config import DisplayConfig
    from hydromodpy.display.figure import BaseFigure, FigureSpec
    from hydromodpy.results.run import Run

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class SkippedFigure:
    """One requested figure that produced nothing, and the short reason why.

    ``actionable`` marks a skip the user can act on: a config option would
    have kept the field it needs, or the figure failed while drawing. A figure
    inapplicable to the run by nature (no calibration, one period for a
    persistence map, a date the run does not hold) is not.
    """

    name: str
    reason: str
    actionable: bool = False


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

    def summary(self, *, destination: Path | None = None, detail: bool = True) -> str:
        """One line: the rendered count, then every figure not produced.

        ``detail = False`` counts the skipped figures without naming them.
        """
        line = f"Rendered {len(self.rendered)}/{len(self.requested)} figure(s)"
        if destination is not None:
            line = f"{line} -> {display_path(destination)}"
        if self.skipped and detail:
            named = ", ".join(f"{item.name} ({item.reason})" for item in self.skipped)
            line = f"{line}; {len(self.skipped)} skipped: {named}"
        elif self.skipped:
            line = f"{line}; {len(self.skipped)} not applicable to this run"
        return line


def log_render_summary(
    report: FigureRenderReport,
    *,
    destination: Path | None = None,
) -> None:
    """Log the batch summary of one rendering pass.

    WARNING when the user can act on a skipped figure (a config option would
    have kept its field, or it failed while drawing), so the line survives
    ``quiet`` mode. Otherwise one milestone line counts the figures, and the
    figures inapplicable to this run by nature are named at INFO, which
    ``--verbose`` shows: a showcase that lists the calibration figures on a
    plain run must not print a warning on its plainest command.
    """
    if not report.requested:
        return
    if any(item.actionable for item in report.skipped):
        logger.warning("%s", report.summary(destination=destination))
        return
    logger.info("%s", report.summary(destination=destination, detail=False), extra=MILESTONE)
    if report.skipped:
        logger.info(
            "Not applicable to this run: %s",
            ", ".join(f"{item.name} ({item.reason})" for item in report.skipped),
        )


@contextmanager
def matplotlib_backend(*, interactive: bool = False, dpi: int = 150) -> Iterator[None]:
    """Scope the matplotlib backend and its cleanup to a ``with`` block.

    ``Agg`` unless ``interactive``; the previous backend comes back and every
    figure is closed on the way out.
    """
    import matplotlib

    previous_backend = matplotlib.get_backend()
    target = previous_backend if interactive else "Agg"
    if target.lower() != previous_backend.lower():
        matplotlib.use(target, force=True)
    rc_context = matplotlib.rc_context()
    try:
        with rc_context:
            matplotlib.rcParams["figure.dpi"] = dpi
            yield
    finally:
        import matplotlib.pyplot as plt

        plt.close("all")
        current = matplotlib.get_backend()
        if current.lower() != previous_backend.lower():
            try:
                matplotlib.use(previous_backend, force=True)
            except Exception:  # an interactive backend may not load headless; the render is done
                pass


def _backend_is_interactive(display_cfg: DisplayConfig) -> bool:
    backend = str(getattr(display_cfg, "backend", "auto") or "auto").lower()
    if backend == "auto":
        return bool(display_cfg.show)
    return backend != "agg"


def _draws_one_instant(figure_name: str) -> bool:
    """Return whether the registered figure ``figure_name`` takes a ``time``."""
    from hydromodpy.display.config import TIME_KEY
    from hydromodpy.display.figure import option_names_of

    return TIME_KEY in option_names_of(type(_get_figure(figure_name)))


def _figure_options(display_cfg: DisplayConfig, figure_name: str) -> dict:
    """Build the keyword options passed to one figure.

    The project-wide ``cmap`` is forwarded only when the user actually set
    it. Injecting the schema default would override each figure's own
    colormap, which is chosen for the physics it shows (a reversed scale for
    a depth, a discrete one for an indicator).

    The gallery ``[display] time`` goes to every figure that draws one
    instant, under the figure's own options: a ``time`` in
    ``[display.overrides.<figure>]`` wins over it.
    """
    options: dict = {}
    if "cmap" in display_cfg.model_fields_set:
        options["cmap"] = display_cfg.cmap
    gallery_time = getattr(display_cfg, "time", None)
    if gallery_time is not None and _draws_one_instant(figure_name):
        options["time"] = gallery_time
    options.update(dict(display_cfg.overrides.get(figure_name, {})))
    return options


def _resolve_time(sim: Run, options: dict[str, Any]) -> str | None:
    """Turn ``options["time"]`` into the step this run stored, or say why not.

    Pops ``time``, resolves it through ``run.periods.step_at`` and writes the
    period index into ``options["timestep"]``, the channel every figure that
    draws one instant reads. Returns ``None`` when the figure can draw, or the
    reason it cannot: a date outside this run is not a failure but a figure
    inapplicable to a run of this length. The steady stage of a calibration
    solves one period over the whole record, so every date of the record
    names that period and needs no phase override. A phase window narrower
    than the record may hold no such date, and the figure is skipped.
    """
    if "time" not in options:
        return None
    selector = options.pop("time")
    if selector is None:
        return None
    try:
        options["timestep"] = int(sim.periods.step_at(selector))
    except TimeSelectionError as exc:
        return f"time {selector!r} names no period of this run: {exc}"
    except RuntimeError as exc:
        # The catalog records no time grid for this run (not completed).
        return f"time {selector!r} cannot be placed: {exc}"
    return None


def _log_skipped_figure(name: str, fig: BaseFigure, sim: Run, reason: str) -> bool:
    """Log one skipped figure, loudly when a field it needs was not kept.

    Returns whether the skip is actionable, which the batch summary reads.
    """
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
        return True
    # A figure inapplicable by nature (no calibration, no particles, another
    # solver) is a normal skip: DEBUG here, and always named in the batch
    # summary so it never disappears entirely.
    logger.debug("Figure '%s' not applicable to this run: %s.", name, reason)
    return False


def _check_options(figure_name: str, fig: BaseFigure, opts: Mapping[str, Any]) -> None:
    """Refuse an option the figure does not take, as ``[display.overrides]`` does."""
    from hydromodpy.display.figure import option_names_of

    accepted = option_names_of(type(fig))
    unknown = sorted(str(key) for key in opts if key not in accepted)
    if not unknown:
        return
    hint = ""
    if "timestep" in unknown and "time" in accepted:
        hint = ' Name the instant with time: a date, "first" or "last".'
    raise ValueError(
        f"figure '{figure_name}' has no option {', '.join(map(repr, unknown))}; "
        f"it takes: {', '.join(sorted(accepted))}.{hint}"
    )


def render_figure(
    figure_name: str,
    sim: Run,
    *,
    save: str | Path | None = None,
    dpi: int | None = None,
    **opts: Any,
) -> MplFigure:
    """Render one figure registered in :mod:`hydromodpy.display` and return it.

    The one path for a single figure: ``hmp.figure``, ``hmp viz show`` and the
    export step all come here, so each refuses a figure the run cannot feed
    in the same words. ``save`` may be a directory (one ``<figure_name>.png``
    is written into it) or a full file path. ``opts`` are the figure's own
    options, as in ``[display.overrides]``: ``time`` names the instant a
    map draws, a date, ``"first"`` or ``"last"``.

    Raises
    ------
    KeyError
        If ``figure_name`` is not registered.
    ValueError
        If an option is not one the figure takes, if the run does not carry
        what the figure needs, or if ``time`` names no period of the run; the
        message gives the reason.
    """
    fig = _get_figure(figure_name)
    if opts:
        _check_options(figure_name, fig, opts)
    reason = fig.unavailable_reason(sim)
    if reason is None:
        opts = dict(opts)
        reason = _resolve_time(sim, opts)
    if reason is not None:
        raise ValueError(f"figure '{figure_name}' does not apply to this run: {reason}")
    save_path: Path | None
    if save is None:
        save_path = None
    else:
        target = Path(save)
        # Treat suffix-less paths as a directory; anything with an extension
        # is a complete file path the caller wants honoured verbatim.
        save_path = target / f"{figure_name}.png" if target.suffix == "" else target
    if dpi is not None:
        opts["dpi"] = dpi
    return fig.plot(sim, save_path=save_path, **opts)


def figure_options_from_run(sim: Run, figure_name: str) -> dict[str, Any]:
    """Return the options the run's own ``[display]`` gave ``figure_name``.

    Read from the config snapshot the run sealed, so redrawing a figure of a
    run draws the instant and the style that run was drawn with. A run
    without a snapshot, or whose ``[display]`` no longer loads, gives no
    option and the figure its defaults; the second case is logged.
    """
    import warnings

    from hydromodpy.display.config import DisplayConfig

    snapshot = getattr(sim, "config_snapshot", None)
    section = snapshot.get("display") if isinstance(snapshot, Mapping) else None
    if not isinstance(section, Mapping):
        return {}
    # A snapshot spells out every field. Only a value away from its default
    # counts as set: the project-wide cmap is forwarded only when chosen.
    fields = DisplayConfig.model_fields
    written = {
        key: value
        for key, value in section.items()
        if key not in fields or value != fields[key].get_default(call_default_factory=True)
    }
    try:
        with warnings.catch_warnings():
            # A former spelling in a sealed snapshot is not the reader's to fix.
            warnings.simplefilter("ignore")
            display_cfg = DisplayConfig.model_validate(written)
    except ValueError as exc:
        logger.warning(
            "The [display] this run was drawn with no longer loads (%s); "
            "drawing '%s' with its default options.",
            exc,
            figure_name,
        )
        return {}
    return _figure_options(display_cfg, figure_name)


def figure_availability(sim: Run) -> list[tuple[FigureSpec, str | None]]:
    """Return every registered figure with the reason ``sim`` cannot feed it.

    The reason is ``None`` for a figure the run supports. Each figure answers
    through its own ``unavailable_reason``, the check ``[display].figures`` and
    ``render_figure`` apply before drawing, so the list says in advance what
    those would skip or refuse. Nothing is drawn.
    """
    return [(spec, _get_figure(spec.name).unavailable_reason(sim)) for spec in _list_figures()]


def resolve_run_output_dir(
    display_cfg: DisplayConfig,
    *,
    project_root: Path,
    run_name: str | None,
    sim_id: str,
) -> Path:
    """Return the directory where figures for one run should be saved.

    Layout: ``<project_root>/runs/<run>/<display.output_dir>/``. Figures
    live inside the run they describe, so moving or deleting a run takes
    them along.
    """
    from hydromodpy.core.state.paths import runs_dir_for
    from hydromodpy.results.catalog.storage_paths import run_dirname

    label = run_name if run_name else sim_id[:8]
    return runs_dir_for(project_root) / run_dirname(label) / display_cfg.output_dir


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
            options = _figure_options(display_cfg, name)
            reason = fig.unavailable_reason(sim) or _resolve_time(sim, options)
            if reason is not None:
                actionable = _log_skipped_figure(name, fig, sim, reason)
                skipped.append(SkippedFigure(name=name, reason=reason, actionable=actionable))
                continue
            save_path = output_dir / f"{name}.png" if display_cfg.save else None
            try:
                fig.plot(
                    sim,
                    dpi=display_cfg.dpi,
                    save_path=save_path,
                    **options,
                )
            except FigureNotApplicable as exc:
                reason = str(exc)
                actionable = _log_skipped_figure(name, fig, sim, reason)
                skipped.append(SkippedFigure(name=name, reason=reason, actionable=actionable))
                continue
            except Exception as exc:
                # One line per figure that fails, at WARNING so it is visible.
                if display_cfg.on_error == "raise":
                    raise
                logger.warning("Figure '%s' failed to render: %s", name, exc)
                skipped.append(
                    SkippedFigure(name=name, reason=f"render failed: {exc}", actionable=True)
                )
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
