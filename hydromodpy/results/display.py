"""Thin wrapper around :mod:`hydromodpy.display` for result-side rendering.

Saving and showing are controlled by ``DisplayConfig`` (TOML
``[display]`` section).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from hydromodpy.display import get as _get_figure

if TYPE_CHECKING:
    from hydromodpy.results.run import Run

logger = logging.getLogger(__name__)


def render_figure(
    figure_name: str,
    sim: "Run",
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
