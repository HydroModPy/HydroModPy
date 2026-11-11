"""Draw the cohort figures of a campaign summary: one PNG per figure and variable.

A cohort figure (``figures/cohort_*.py``) draws a table with one row per site,
not a run. ``hmp campaign collect`` asks this module for the names it may draw
(:func:`cohort_figure_names`) and draws them under ``summary/figures/``
(:func:`draw_cohort_figures`), each file recorded in the ledger of the folder.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from hydromodpy.core.logging import get_logger
from hydromodpy.core.version import __version__ as HYDROMODPY_VERSION
from hydromodpy.display.style import themed

if TYPE_CHECKING:
    import pandas as pd

logger = get_logger(__name__)

COHORT_FIGURE_MODULE_PREFIX: Final[str] = "hydromodpy.display.figures.cohort_"
"""A figure of ``[sites.summary] figures`` draws the cohort table; it lives in such a module."""


def is_cohort_figure(name: str) -> bool:
    """Whether the registered figure ``name`` draws the cohort table."""
    from hydromodpy.display.figure_registry import resolve
    from hydromodpy.display.figure_table import FIGURES

    target = resolve(name)
    path = FIGURES.get(target)
    if path is not None:
        return path.startswith(COHORT_FIGURE_MODULE_PREFIX)
    import hydromodpy.display.figure_registry as figure_registry

    return type(figure_registry.get(name)).__module__.startswith(COHORT_FIGURE_MODULE_PREFIX)


def cohort_figure_names() -> list[str]:
    """Return the registered cohort figures, sorted."""
    import hydromodpy.display.figure_registry as figure_registry

    return sorted(name for name in figure_registry.names() if is_cohort_figure(name))


def draw_cohort_figures(
    map_frame: pd.DataFrame,
    names: Sequence[str],
    variables: Sequence[str],
    figures_dir: Path,
) -> tuple[list[Path], list[str]]:
    """Draw each cohort figure for each variable; return the files written and those skipped.

    A figure the cohort cannot give (a variable without a finite value, a
    table without outlets) is skipped and named, ``<figure> of <variable>:
    <reason>``; the others are drawn.
    """
    if not names:
        return [], []
    import hydromodpy.display.figure_registry as figure_registry

    written: list[Path] = []
    skipped: list[str] = []
    with themed():
        for name in names:
            figure = figure_registry.get(name)
            for variable in variables:
                target = figures_dir / f"{name}_{variable}.png"
                try:
                    figure.plot(map_frame, variable=variable, save_path=target)
                except ValueError as exc:
                    skipped.append(f"{name} of {variable}: {exc}")
                    logger.warning("summary figure %s of %s skipped: %s", name, variable, exc)
                    continue
                record_collected_file(
                    figures_dir,
                    target,
                    producer=f"display.figures.{name}",
                    options={"variable": variable},
                )
                written.append(target)
    return written, skipped


def record_collected_file(
    directory: Path, path: Path, *, producer: str, options: Mapping[str, Any]
) -> None:
    """Add a file of the summary, drawn from many runs, to the ledger of its directory."""
    from hydromodpy.core.io.file_digest import sha256_of
    from hydromodpy.results.ledger import Ledger, LedgerEntry

    entry = LedgerEntry(
        file=path.relative_to(directory).as_posix(),
        producer=producer,
        options=dict(options),
        hydromodpy_version=HYDROMODPY_VERSION,
        at=datetime.now(UTC),
        sha256=sha256_of(path),
        identity=None,
    )
    ledger = Ledger.read(directory)
    ledger.append(entry)
    ledger.write(directory)


__all__ = [
    "COHORT_FIGURE_MODULE_PREFIX",
    "cohort_figure_names",
    "draw_cohort_figures",
    "is_cohort_figure",
    "record_collected_file",
]
