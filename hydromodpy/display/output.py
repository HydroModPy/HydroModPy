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
from hydromodpy.display import interactive, static
from hydromodpy.display.request import FORMATS, FigureRequest, ResolvedFigure, replay_request
from hydromodpy.display.theme import Theme
from hydromodpy.results.derive.time_alignment import run_period
from hydromodpy.results.identity import PNG_IDENTITY_KEY, Identity
from hydromodpy.results.ledger import record_derived_file
from hydromodpy.results.record.label import identity_of_run_dir
from hydromodpy.results.run.view import Run

PRODUCER_PREFIX = "display:"
"""Start of the producer of every figure entry of the ledger, old registry and requests."""
PRODUCER = f"{PRODUCER_PREFIX}figure"
REQUEST_KEY = "request"
PRESET_KEY = "preset"
THEME_KEY = "theme"
FOOTER_COLOR = (90, 90, 90)
"""Gray of the identity footer text."""


def stamp_png_identity(path: str | Path, identity: Identity) -> Path:
    """Pose the identity block in a saved PNG: a visible footer and a text chunk.

    The footer is a strip under the image that reads ``Identity.footer_text``. The
    block goes to the text chunk ``PNG_IDENTITY_KEY``, beside the chunks the file
    holds. A PNG that already carries the chunk keeps its footer, so stamping twice
    never stacks two strips.
    """
    from PIL import Image, ImageDraw, ImageFont
    from PIL.PngImagePlugin import PngInfo

    target = Path(path)
    with Image.open(target) as opened:
        chunks = {str(key): str(value) for key, value in getattr(opened, "text", {}).items()}
        image = opened.copy()
    if PNG_IDENTITY_KEY not in chunks:
        text = identity.footer_text()
        width, height = image.size
        size = max(10, min(18, width // 90))
        font = ImageFont.load_default(size=size)
        mode = "RGBA" if image.mode in ("RGBA", "LA", "P") else "RGB"
        white = (255, 255, 255, 255) if mode == "RGBA" else (255, 255, 255)
        framed = Image.new(mode, (width, height + size * 2), white)
        framed.paste(image.convert(mode), (0, 0))
        draw = ImageDraw.Draw(framed)
        left = max(4, (width - draw.textlength(text, font=font)) / 2)
        draw.text((left, height + size // 2), text, fill=FOOTER_COLOR, font=font)
        image = framed
    chunks.update(identity.as_png_metadata())
    info = PngInfo()
    for key, value in chunks.items():
        info.add_text(key, value)
    image.save(target, format="PNG", pnginfo=info, optimize=False)
    return target


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
    *,
    embed: bool = False,
) -> list[Path]:
    """Write ``fig`` as ``directory/<figure.stem>.<format>`` for each format and return the paths.

    Files go through ``static.save(fig, directory / figure.stem, theme,
    formats=figure.formats)``. When ``run`` is given and ``directory`` is its
    ``figures/`` folder, each PNG gets the identity of
    ``results.record.label.identity_of_run_dir`` with the run period, stamped by
    ``stamp_png_identity``, and each file one entry through
    ``results.ledger.record_derived_file(directory, path, producer=PRODUCER,
    options=ledger_options(figure), identity=...)``. Without a run (a session or a
    set of runs, or a folder that is not a run directory), files are written and not
    recorded, since a ledger entry needs an identity.

    A plotly figure of the interactive engine is written as ``<stem>.html``, which loads
    plotly.js from the CDN, or holds it with ``embed``. A static figure writes the formats
    of the static engine and leaves ``html`` to the interactive one.
    """
    if isinstance(fig, Figure):
        formats = tuple(fmt for fmt in figure.formats if fmt in FORMATS)
        paths = static.save(fig, directory / figure.stem, theme, formats=formats)
    else:
        paths = [interactive.write(fig, directory / figure.stem, embed=embed)]
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
