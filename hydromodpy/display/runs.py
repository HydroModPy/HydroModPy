"""Per-run figure rendering helpers.

Bridges :class:`~hydromodpy.results.run.view.Run` and the figure registry in
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

A figure of a run is written under ``runs/<run>/figures/``. Each file carries
the identity block of the run (a visible footer and a PNG text chunk) and an
entry in ``figures/index.json``, which :func:`regen_figures` replays. Figures
are drawn after the seal, so the block of a sealed run carries its label, the
rules it follows and the day it was computed.

A figure declares its subject (``FigureSpec.subject``): a run, a calibration
session or a set of runs. ``_subject_for`` resolves it once, before any
refusal is asked: a session figure asked for on a run draws the session that
promoted the run, and receives the run as the option ``promoted``. A run the
figure cannot take is refused with a sentence naming what to pass.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hydromodpy.core.console.progress import MILESTONE
from hydromodpy.core.exceptions import DisplayError
from hydromodpy.core.logging import get_logger
from hydromodpy.core.state.portable import display_path
from hydromodpy.core.time.selection import TimeSelectionError
from hydromodpy.display.figure import (
    NOT_A_RUN_REASON,
    NOT_A_RUNSET_REASON,
    NOT_A_SESSION_REASON,
    NOT_PROMOTED_REASON,
    PROMOTED_OPTION,
)
from hydromodpy.display.figure_registry import get as _get_figure
from hydromodpy.display.figure_registry import list_figures as _list_figures
from hydromodpy.display.figure_table import FORMER_NAMES
from hydromodpy.display.output import PRODUCER, PRODUCER_PREFIX
from hydromodpy.display.png_metadata import stamp_png_identity
from hydromodpy.display.style import Theme, themed
from hydromodpy.display.subject import FigureNotApplicable
from hydromodpy.results.derive.config_flags import (
    missing_field_explanation,
    no_surface_exit_reason,
)
from hydromodpy.results.derive.time_alignment import run_period
from hydromodpy.results.identity import Identity
from hydromodpy.results.ledger import Ledger, record_derived_file
from hydromodpy.results.record.label import identity_of_run_dir
from hydromodpy.results.run.group import RunSet
from hydromodpy.results.session.view import Session
from hydromodpy.results.storage.contract import RUN_FIGURES_DIRNAME

if TYPE_CHECKING:
    from matplotlib.figure import Figure as MplFigure

    from hydromodpy.display.config import DisplayConfig
    from hydromodpy.display.figure import BaseFigure, FigureSpec
    from hydromodpy.results.run.view import Run

logger = get_logger(__name__)

"""What a figure ledger entry names as producer, followed by the figure name."""


@dataclass(frozen=True, slots=True)
class _Subject:
    """What one figure draws, resolved from the object a caller passed.

    ``drawn`` is what ``render`` and ``plot`` receive. ``run`` is the run the
    figure belongs to: the run itself, or the run a session promoted. It
    places ``time``, gives the period of the identity block and the field
    checks; it is ``None`` for a session or a set of runs passed directly.
    ``options`` carry the promoted run to a session figure. ``reason`` says
    why the figure cannot take the object, else ``None``.
    """

    drawn: Any
    run: Any
    options: Mapping[str, Any]
    reason: str | None = None


def _subject_for(
    fig: BaseFigure,
    obj: Any,
    *,
    session_of: Callable[[Any], Session | None] = Session.of_run,
) -> _Subject:
    """Resolve the subject ``fig`` draws from ``obj``, once, before any refusal.

    ``session_of`` finds the session that promoted a run; a batch passes a
    memoised one so a run is looked up once for all its session figures.
    """
    subject = getattr(getattr(fig, "spec", None), "subject", "run")
    if subject == "session":
        if isinstance(obj, Session):
            return _Subject(drawn=obj, run=None, options={})
        if isinstance(obj, RunSet):
            return _Subject(drawn=obj, run=None, options={}, reason=NOT_A_SESSION_REASON)
        session = session_of(obj)
        if session is None:
            return _Subject(drawn=obj, run=obj, options={}, reason=NOT_PROMOTED_REASON)
        return _Subject(drawn=session, run=obj, options={PROMOTED_OPTION: obj})
    if subject == "runset":
        if isinstance(obj, RunSet):
            return _Subject(drawn=obj, run=None, options={})
        run = None if isinstance(obj, Session) else obj
        return _Subject(drawn=obj, run=run, options={}, reason=NOT_A_RUNSET_REASON)
    if isinstance(obj, (Session, RunSet)):
        return _Subject(drawn=obj, run=None, options={}, reason=NOT_A_RUN_REASON)
    return _Subject(drawn=obj, run=obj, options={})


def _memoised_session_of() -> Callable[[Any], Session | None]:
    """Return ``Session.of_run`` remembering its answer for the last run asked."""
    seen: dict[int, Session | None] = {}

    def session_of(run: Any) -> Session | None:
        key = id(run)
        if key not in seen:
            seen[key] = Session.of_run(run)
        return seen[key]

    return session_of


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
def rendering(theme: str | None = None) -> Iterator[Theme | None]:
    """Hold the render lock, with the style of ``theme``, for the length of one render.

    Figures are drawn on their own canvas (:func:`~hydromodpy.display.figure.new_figure`),
    so no backend is switched and no figure is left to close. What a render
    shares with the others is ``rcParams``, which :func:`~hydromodpy.display.style.themed`
    sets for this block only. With no ``theme`` the style in force is kept.
    """
    with themed(theme) as resolved:
        yield resolved


def _show(figures: Sequence[MplFigure]) -> None:
    """Open ``figures`` in the backend of the user's session, then close those only.

    This is the one place a render meets ``pyplot``: a window needs the
    registry. Each figure takes the canvas of a new manager, which is what
    ``plt.figure()`` would have built for it.
    """
    import matplotlib.pyplot as plt

    for fig in figures:
        manager = plt.figure().canvas.manager
        manager.canvas.figure = fig
        fig.set_canvas(manager.canvas)
    plt.show()
    for fig in figures:
        plt.close(fig)


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


def unavailable_reason(fig: BaseFigure, sim: Any) -> str | None:
    """Return why ``fig`` cannot draw ``sim``, or None when it can.

    ``sim`` is a run, a session or a set of runs. The subject of the figure
    is resolved first (a session figure on a run reads the session that
    promoted it), then the figure gives its own answer.
    """
    return _reason_for(fig, _subject_for(fig, sim))


def _reason_for(fig: BaseFigure, subject: _Subject) -> str | None:
    """Return why ``fig`` cannot draw its resolved ``subject``, or None.

    The refusal of the subject first, then for a run figure the one reason no
    figure can work around (a field built on the surface outflow of a model
    that has none), then the figure's own answer.
    """
    if subject.reason is not None:
        return subject.reason
    spec = getattr(fig, "spec", None)
    if spec is not None and getattr(spec, "subject", "run") == "run":
        exit_reason = no_surface_exit_reason(subject.run, spec.required_fields)
        if exit_reason is not None:
            return exit_reason
    return fig.unavailable_reason(subject.drawn)


def _time_reason(subject: _Subject, options: dict[str, Any]) -> str | None:
    """Place ``time`` on the run of the subject; a subject without a run takes none."""
    if subject.run is None:
        if options.pop("time", None) is not None:
            return "time names an instant of a run, and this figure draws no single run"
        return None
    return _resolve_time(subject.run, options)


def _log_skipped_figure(name: str, fig: BaseFigure, sim: Any, reason: str) -> bool:
    """Log one skipped figure, loudly when a field it needs was not kept.

    Returns whether the skip is actionable, which the batch summary reads.
    A session or a runset figure reads no field of a run, so its skip is
    never a field the configuration dropped.
    """

    spec = fig.spec
    if getattr(spec, "subject", "run") != "run" or sim is None:
        logger.debug("Figure '%s' not applicable: %s.", name, reason.rstrip("."))
        return False
    # A figure that requires nothing and reads optional fields (any one of them
    # draws it) is explained over those.
    fields = spec.required_fields or spec.optional_fields
    explanation = missing_field_explanation(fields, sim)
    if explanation and no_surface_exit_reason(sim, spec.required_fields) is None:
        # A figure may already carry the sentence in its own reason.
        if explanation in reason:
            logger.warning("Figure '%s' skipped: %s", name, reason)
        else:
            logger.warning("Figure '%s' skipped: %s. %s", name, reason.rstrip("."), explanation)
        return True
    # A figure inapplicable by nature (no calibration, no particles, another
    # solver) is a normal skip: DEBUG here, and always named in the batch
    # summary so it never disappears entirely.
    logger.debug("Figure '%s' not applicable to this run: %s.", name, reason.rstrip("."))
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
    run_dir: Path | None = None,
    **opts: Any,
) -> MplFigure:
    """Render one figure registered in :mod:`hydromodpy.display` and return it.

    The one path for a single figure: ``Run.figure``, ``hmp show --figure`` and the
    export step all come here, so each refuses a figure the run cannot feed
    in the same words. ``save`` may be a directory (one ``<figure_name>.png``
    is written into it) or a full file path. ``opts`` are the figure's own
    options, as in ``[display.overrides]``: ``time`` names the instant a
    map draws, a date, ``"first"`` or ``"last"``. ``run_dir`` is the
    directory of the run: a PNG saved with it is stamped with the identity of
    the run (a visible footer and a text chunk). ``sim`` is a run, a session
    or a set of runs, as the figure's subject says; a session figure given a
    run draws the session that promoted it. A session or a set of runs has no
    identity block: it is not a run and carries no label.

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
    subject = _subject_for(fig, sim)
    reason = _reason_for(fig, subject)
    if reason is None:
        opts = dict(opts)
        reason = _time_reason(subject, opts)
    if reason is not None:
        raise ValueError(f"figure '{figure_name}' does not apply to this run: {reason}")
    save_path: Path | None
    if save is None:
        save_path = None
    else:
        target = Path(save)
        # Treat suffix-less paths as a directory; anything with an extension
        # is a complete file path the caller wants honored verbatim.
        save_path = target / f"{figure_name}.png" if target.suffix == "" else target
    if dpi is not None:
        opts["dpi"] = dpi
    figure = fig.plot(subject.drawn, save_path=save_path, **subject.options, **opts)
    if (
        save_path is not None
        and run_dir is not None
        and subject.run is not None
        and save_path.suffix.lower() == ".png"
    ):
        identity = figure_identity(subject.run, run_dir)
        if identity is not None:
            stamp_png_identity(save_path, identity)
    return figure


def figure_identity(sim: Run, run_dir: Path) -> Identity | None:
    """Return the identity block a figure of *run_dir* carries, with the period of the run.

    A sealed run states its period in its seal; a run still being computed
    gets it from its time grid. ``None`` when the directory does not say
    which run it is.
    """
    identity = identity_of_run_dir(run_dir)
    if identity is None or identity.period is not None:
        return identity
    return identity.model_copy(update={"period": run_period(sim)})


def record_figure(
    path: Path, *, name: str, options: Mapping[str, Any], sim: Run, figures_dir: Path
) -> None:
    """Stamp a figure written under ``figures/`` with the identity of its run and record it.

    ``options`` are the options the figure was drawn with, as a user writes
    them (``time`` as a date, not the period index): the ledger replays them.
    """
    identity = figure_identity(sim, figures_dir.parent)
    if identity is None:
        logger.debug("Figure %s written outside an identified run directory: %s", name, path)
        return
    stamp_png_identity(path, identity)
    record_derived_file(
        figures_dir,
        path,
        producer=f"{PRODUCER_PREFIX}{name}",
        options=options,
        identity=identity,
    )


def sealed_display_values(snapshot: object) -> dict[str, Any] | None:
    """Return the ``[display]`` values a config snapshot sets away from their defaults.

    ``None`` when the snapshot holds no ``[display]``. A snapshot spells out every
    field, so only a value away from its default counts as set: the project-wide
    cmap is forwarded only when chosen. A figure name a figure used to carry is
    given its current name, so loading a sealed snapshot never raises the
    renaming warning, which is addressed to the author of a config.
    """
    from hydromodpy.display.config import DisplayConfig

    section = snapshot.get("display") if isinstance(snapshot, Mapping) else None
    if not isinstance(section, Mapping):
        return None
    fields = DisplayConfig.model_fields
    written = {
        key: value
        for key, value in section.items()
        if key not in fields or value != fields[key].get_default(call_default_factory=True)
    }
    if isinstance(written.get("figures"), list | tuple):
        written["figures"] = [_current_name(name) for name in written["figures"]]
    if isinstance(written.get("overrides"), Mapping):
        written["overrides"] = {_current_name(k): v for k, v in written["overrides"].items()}
    return written


def _current_name(name: Any) -> Any:
    return FORMER_NAMES.get(name, name) if isinstance(name, str) else name


def figure_options_from_run(sim: Run, figure_name: str) -> dict[str, Any]:
    """Return the options the run's own ``[display]`` gave ``figure_name``.

    Read from the config snapshot the run sealed, so redrawing a figure of a
    run draws the instant and the style that run was drawn with. A run
    without a snapshot, or whose ``[display]`` no longer loads, gives no
    option and the figure its defaults; the second case is logged.
    """
    from hydromodpy.display.config import DisplayConfig

    written = sealed_display_values(getattr(sim, "config_snapshot", None))
    if written is None:
        return {}
    try:
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


def figure_availability(sim: Any) -> list[tuple[FigureSpec, str | None]]:
    """Return every registered figure with the reason ``sim`` cannot feed it.

    The reason is ``None`` for a figure the run supports. Each figure answers
    through its own ``unavailable_reason``, the check ``[display].figures`` and
    ``render_figure`` apply before drawing, so the list says in advance what
    those would skip or refuse. Nothing is drawn.
    """
    session_of = _memoised_session_of()
    rows = []
    for spec in _list_figures():
        fig = _get_figure(spec.name)
        rows.append((spec, _reason_for(fig, _subject_for(fig, sim, session_of=session_of))))
    return rows


def figures_dir_of(run_dir: Path) -> Path:
    """Return ``runs/<run>/figures/``, where the figures of one run are saved.

    Figures live inside the run they describe, so moving, publishing or
    deleting a run takes them along.
    """
    return Path(run_dir) / RUN_FIGURES_DIRNAME


def _regen_request(entry: Any, sim: Run, figures_dir: Path, dpi: int) -> None:
    """Draw again the figure of a ``display:figure`` entry, from the request and theme it recorded."""
    from dataclasses import replace

    from hydromodpy.display.output import THEME_KEY, request_from_ledger, write
    from hydromodpy.display.presets import PRESETS
    from hydromodpy.display.render import render
    from hydromodpy.display.request import FORMATS, expand
    from hydromodpy.display.theme import get_theme

    theme = replace(get_theme(entry.options.get(THEME_KEY, "default")), dpi=dpi)
    figure = expand(request_from_ledger(entry.options), PRESETS)
    suffix = Path(entry.file).suffix.lstrip(".")
    figure = replace(
        figure,
        stem=Path(entry.file).stem,
        formats=(suffix,) if suffix in FORMATS else figure.formats,
    )
    write(render(figure, sim, theme=theme), figure, sim, figures_dir, theme)


def regen_figures(sim: Run, run_dir: Path, *, dpi: int = 150) -> FigureRenderReport:
    """Draw again every figure ``figures/index.json`` of a run records.

    Each entry is drawn with the options it was recorded with, into the same
    file, and recorded again.
    """
    figures_dir = figures_dir_of(run_dir)
    entries = [
        entry
        for entry in Ledger.read(figures_dir).entries
        if entry.producer.startswith(PRODUCER_PREFIX)
    ]
    if not entries:
        raise ValueError(
            f"{figures_dir} records no figure to draw again. Draw one with "
            "'hmp show <run> --figure <figure> --to FILE' or list figures in [display]."
        )
    rendered: list[str] = []
    written: list[Path] = []
    skipped: list[SkippedFigure] = []
    session_of = _memoised_session_of()
    with rendering():
        for entry in entries:
            name = entry.producer.removeprefix(PRODUCER_PREFIX)
            target = figures_dir / entry.file
            if entry.producer == PRODUCER:
                try:
                    _regen_request(entry, sim, figures_dir, dpi)
                except (DisplayError, ValueError) as error:
                    skipped.append(SkippedFigure(name=target.stem, reason=str(error)))
                    continue
                rendered.append(target.stem)
                written.append(target)
                continue
            fig = _get_figure(name)
            options = dict(entry.options)
            subject = _subject_for(fig, sim, session_of=session_of)
            reason = _reason_for(fig, subject) or _time_reason(subject, options)
            if reason is not None:
                skipped.append(SkippedFigure(name=name, reason=reason))
                continue
            fig.plot(subject.drawn, dpi=dpi, save_path=target, **subject.options, **options)
            record_figure(
                target, name=name, options=entry.options, sim=sim, figures_dir=figures_dir
            )
            rendered.append(name)
            written.append(target)
    return FigureRenderReport(
        requested=tuple(
            Path(entry.file).stem
            if entry.producer == PRODUCER
            else entry.producer.removeprefix(PRODUCER_PREFIX)
            for entry in entries
        ),
        rendered=tuple(rendered),
        written=tuple(written),
        skipped=tuple(skipped),
    )


def render_figures_for_run(
    sim: Run,
    display_cfg: DisplayConfig,
    *,
    output_dir: Path,
    figure_names: list[str] | None = None,
) -> FigureRenderReport:
    """Render the figures listed in ``display_cfg`` for one :class:`Run`.

    ``output_dir`` is the ``figures/`` directory of the run
    (:func:`figures_dir_of`): each file written there is stamped with the
    identity of the run and recorded in its ledger.

    Honors ``display_cfg.enabled`` and ``display_cfg.save``. A figure whose
    declared requirements are not met by this run (no particle process, no
    calibration, a solver that does not produce the field) is reported as
    not applicable and skipped. A session figure draws the session that
    promoted ``sim``, and is skipped with its reason when none did. A figure that fails while rendering raises
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

    shown = display_cfg.show and _backend_is_interactive(display_cfg)
    drawn: list[MplFigure] = []
    with rendering(display_cfg.theme_name):
        session_of = _memoised_session_of()
        for name in wanted:
            fig = _get_figure(name)
            options = _figure_options(display_cfg, name)
            recorded = dict(options)
            subject = _subject_for(fig, sim, session_of=session_of)
            reason = _reason_for(fig, subject) or _time_reason(subject, options)
            if reason is not None:
                actionable = _log_skipped_figure(name, fig, sim, reason)
                skipped.append(SkippedFigure(name=name, reason=reason, actionable=actionable))
                continue
            save_path = output_dir / f"{name}.png" if display_cfg.save else None
            try:
                figure = fig.plot(
                    subject.drawn,
                    dpi=display_cfg.dpi,
                    save_path=save_path,
                    **subject.options,
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
            if shown:
                drawn.append(figure)
            if save_path is not None:
                record_figure(
                    save_path, name=name, options=recorded, sim=sim, figures_dir=output_dir
                )
                written.append(save_path)
                logger.debug("Rendered figure '%s' -> %s", name, save_path)
    if shown:
        _show(drawn)
    return FigureRenderReport(
        requested=tuple(wanted),
        rendered=tuple(rendered),
        written=tuple(written),
        skipped=tuple(skipped),
    )
