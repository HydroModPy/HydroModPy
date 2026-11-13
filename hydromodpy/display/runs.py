"""Figures of a run: draw requests at the end of a run, draw the recorded ones again.

A figure of a run is written under ``runs/<run>/figures/``. Each file carries the
identity block of the run (a visible footer and a PNG text chunk) and an entry in
``figures/index.json``, which :func:`regen_figures` replays.

Drawing reports what it did through :class:`FigureRenderReport`. A figure the user
asked for and did not get is an output that must stay visible: the batch summary
names every requested figure that produced nothing, at WARNING when the user can act
on one of them, at INFO otherwise.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hydromodpy.core.console.progress import MILESTONE
from hydromodpy.core.exceptions import DisplayError
from hydromodpy.core.logging import get_logger
from hydromodpy.core.runtime.stopwatch import Measure, measured
from hydromodpy.core.state.portable import display_path
from hydromodpy.display.output import (
    PRODUCER,
    PRODUCER_PREFIX,
    THEME_KEY,
    request_from_ledger,
    write,
)
from hydromodpy.display.presets import PRESETS
from hydromodpy.display.render import render
from hydromodpy.display.request import (
    END,
    FORMATS,
    INTERACTIVE,
    STATIC,
    expand,
    file_stem,
    retired,
)
from hydromodpy.display.subject import FigureNotApplicable
from hydromodpy.display.theme import get_theme
from hydromodpy.results.ledger import Ledger
from hydromodpy.results.storage.contract import RUN_FIGURES_DIRNAME

if TYPE_CHECKING:
    from hydromodpy.display.config import DisplayConfig
    from hydromodpy.display.request import FigureRequest
    from hydromodpy.display.theme import Theme
    from hydromodpy.results.run.view import Run

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

    ``rendered`` counts the figures actually drawn, and ``written`` the files they
    gave. ``skipped`` holds every requested figure that produced nothing, whether it
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


def figures_dir_of(run_dir: Path) -> Path:
    """Return ``runs/<run>/figures/``, where the figures of one run are saved.

    Figures live inside the run they describe, so moving, publishing or
    deleting a run takes them along.
    """
    return Path(run_dir) / RUN_FIGURES_DIRNAME


def _regen_request(entry: Any, sim: Run, figures_dir: Path, dpi: int | None) -> None:
    """Draw again the figure of a ``display:figure`` entry, from the request and theme it recorded."""
    theme = get_theme(entry.options.get(THEME_KEY, "default"))
    theme = theme if dpi is None else replace(theme, dpi=dpi)
    figure = expand(request_from_ledger(entry.options), PRESETS)
    suffix = Path(entry.file).suffix.lstrip(".")
    figure = replace(
        figure,
        stem=Path(entry.file).stem,
        formats=(suffix,) if suffix in FORMATS else figure.formats,
    )
    engine = INTERACTIVE if suffix == "html" else STATIC
    write(render(figure, sim, theme=theme, engine=engine), figure, sim, figures_dir, theme)


def sealed_display_values(snapshot: object) -> dict[str, Any] | None:
    """Return the ``[display]`` values a config snapshot sets away from their defaults.

    ``None`` when the snapshot holds no ``[display]``. A snapshot spells out every
    field, so only a value away from its default counts as set.
    """
    from hydromodpy.display.config import DisplayConfig

    section = snapshot.get("display") if isinstance(snapshot, Mapping) else None
    if not isinstance(section, Mapping):
        return None
    fields = DisplayConfig.model_fields
    return {
        key: value
        for key, value in section.items()
        if key not in fields or value != fields[key].get_default(call_default_factory=True)
    }


def display_theme(display_cfg: DisplayConfig) -> Theme:
    """Return the theme a ``[display]`` names, drawn at its ``dpi``."""
    return replace(get_theme(display_cfg.theme), dpi=display_cfg.dpi)


def draw_requests(
    run: Run,
    requests: Sequence[FigureRequest],
    *,
    presets: Mapping[str, FigureRequest],
    theme: Theme,
    output_dir: Path,
    on_error: str = "warn",
    on_measure: Callable[[Measure], None] | None = None,
) -> FigureRenderReport:
    """Draw each request of ``when = "end"``: one expand, one render and one write each.

    A figure that does not apply to the run is skipped with its reason. Any other
    failure is logged and skipped, or raised when ``on_error`` is ``raise``. A request
    drawn at another time is left out of the report.
    """
    rendered: list[str] = []
    written: list[Path] = []
    skipped: list[SkippedFigure] = []
    requested: list[str] = []
    for request in requests:
        stem = file_stem(request)
        try:
            figure = expand(request, presets)
            if figure.when != END:
                logger.info(
                    "Figure %s is not drawn at the end of the run: when = %r is drawn at that time.",
                    stem,
                    figure.when,
                )
                continue
            requested.append(stem)
            with measured("figure", stem) as measure:
                try:
                    paths = write(render(figure, run, theme=theme), figure, run, output_dir, theme)
                finally:
                    if on_measure is not None:
                        on_measure(measure)
        except FigureNotApplicable as exc:
            logger.info("Figure %s skipped: %s", stem, exc)
            skipped.append(SkippedFigure(name=stem, reason=str(exc)))
        except Exception as exc:
            if on_error == "raise":
                raise
            logger.warning("Figure %s failed: %s", stem, exc)
            if stem not in requested:
                requested.append(stem)
            skipped.append(
                SkippedFigure(name=stem, reason=f"render failed: {exc}", actionable=True)
            )
        else:
            rendered.append(stem)
            written.extend(paths)
    return FigureRenderReport(
        requested=tuple(requested),
        rendered=tuple(rendered),
        written=tuple(written),
        skipped=tuple(skipped),
    )


def _old_entry(entry: Any) -> SkippedFigure:
    """Skip a ledger entry of a figure of a pre-release, with what replaces it."""
    name = entry.producer.removeprefix(PRODUCER_PREFIX)
    reason = (
        f"figures/index.json records {entry.file} from the figure '{name}' of a pre-release, "
        "which this version does not draw. Draw it again with hmp show <run> "
        f"--figure <variable or preset> --to {entry.file}"
    )
    more = retired(name)
    return SkippedFigure(name=Path(entry.file).stem, reason=f"{reason}. {more}" if more else reason)


def regen_figures(sim: Run, run_dir: Path, *, dpi: int | None = None) -> FigureRenderReport:
    """Draw again every figure ``figures/index.json`` of a run records.

    Each request entry is drawn with the request and theme it was recorded with, into
    the same file, at ``dpi`` or at the dpi of its theme, and recorded again. An entry
    of a figure of a pre-release is skipped with a sentence that names what to draw.
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
            "'hmp show <run> --figure <variable or preset> --to FILE' or write a "
            "[[display.figure]] table."
        )
    rendered: list[str] = []
    written: list[Path] = []
    skipped: list[SkippedFigure] = []
    for entry in entries:
        stem = Path(entry.file).stem
        if entry.producer != PRODUCER:
            skipped.append(_old_entry(entry))
            continue
        try:
            _regen_request(entry, sim, figures_dir, dpi)
        except (DisplayError, ValueError) as error:
            skipped.append(SkippedFigure(name=stem, reason=str(error)))
            continue
        rendered.append(stem)
        written.append(figures_dir / entry.file)
    return FigureRenderReport(
        requested=tuple(Path(entry.file).stem for entry in entries),
        rendered=tuple(rendered),
        written=tuple(written),
        skipped=tuple(skipped),
    )
