"""Figure files: written through ``static.save``, stamped with the run identity, entered in the ledger.

Each file gets one entry of ``figures/index.json`` with the producer ``PRODUCER``.
The entry holds the request that draws the figure again, so ``hmp export <run>
--regen figures`` replays it without the configuration of the run.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from matplotlib.figure import Figure

from hydromodpy.core.exceptions import DisplayError
from hydromodpy.display import static
from hydromodpy.display.png_metadata import stamp_png_identity
from hydromodpy.display.request import FigureRequest, ResolvedFigure, replay_request
from hydromodpy.display.theme import Theme
from hydromodpy.results.derive.time_alignment import run_period
from hydromodpy.results.ledger import record_derived_file
from hydromodpy.results.record.label import identity_of_run_dir
from hydromodpy.results.run.view import Run

PRODUCER_PREFIX = "display:"
"""Start of the producer of every figure entry of the ledger, old registry and requests."""
PRODUCER = f"{PRODUCER_PREFIX}figure"
REQUEST_KEY = "request"
PRESET_KEY = "preset"
THEME_KEY = "theme"


def ledger_options(figure: ResolvedFigure, theme: str = "default") -> dict[str, Any]:
    """Return the ``options`` of the ledger entry of a figure.

    ``{"request": replay_request(figure).model_dump(mode="json", exclude_defaults=True),
    "preset": figure.preset, "theme": theme}``. The preset name is kept for memory, since
    the request already holds its panels expanded, and the theme name so that a
    regeneration draws the same look. A figure drawn by a Python function without a
    preset records ``{"request": None, "preset": None, "theme": theme}`` and ``regen``
    refuses it.
    """
    if figure.draw is not None and figure.preset is None:
        return {REQUEST_KEY: None, PRESET_KEY: None, THEME_KEY: theme}
    request = replay_request(figure).model_dump(mode="json", exclude_defaults=True)
    return {REQUEST_KEY: request, PRESET_KEY: figure.preset, THEME_KEY: theme}


def request_from_ledger(options: Mapping[str, Any]) -> FigureRequest:
    """Return the request a ledger entry of ``PRODUCER`` recorded, to draw it again.

    Refuses an entry of another producer, naming ``PRODUCER``, and an entry without
    a request, naming the Python function path.
    """
    if REQUEST_KEY not in options:
        raise DisplayError(
            f"This ledger entry holds no {REQUEST_KEY!r}, so it was not written by "
            f"the producer {PRODUCER!r}."
        )
    request = options[REQUEST_KEY]
    if request is None:
        raise DisplayError(
            "This figure was drawn by a Python function that no preset names, so it "
            "cannot be replayed. Call the function again in Python."
        )
    return FigureRequest.model_validate(request)


def write(
    fig: Figure,
    figure: ResolvedFigure,
    run: Run | None,
    directory: Path,
    theme: Theme,
) -> list[Path]:
    """Write ``fig`` as ``directory/<figure.stem>.<format>`` for each format and return the paths.

    Files go through ``static.save(fig, directory / figure.stem, theme,
    formats=figure.formats)``. When ``run`` is given and ``directory`` is its
    ``figures/`` folder, each PNG gets the identity of
    ``results.record.label.identity_of_run_dir`` with the run period, stamped by
    ``png_metadata.stamp_png_identity``, and each file one entry through
    ``results.ledger.record_derived_file(directory, path, producer=PRODUCER,
    options=ledger_options(figure), identity=...)``. Without a run (a session or a
    set of runs, or a folder that is not a run directory), files are written and not
    recorded, since a ledger entry needs an identity.
    """
    paths = static.save(fig, directory / figure.stem, theme, formats=figure.formats)
    identity = identity_of_run_dir(directory.parent) if run is not None else None
    if identity is None:
        return paths
    if identity.period is None:
        identity = identity.model_copy(update={"period": run_period(run)})
    options = ledger_options(figure, theme.name)
    for path in paths:
        if path.suffix == ".png":
            stamp_png_identity(path, identity)
        record_derived_file(directory, path, producer=PRODUCER, options=options, identity=identity)
    return paths
