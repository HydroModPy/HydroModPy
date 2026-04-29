"""Per-run figure rendering helpers.

Bridges :class:`~hydromodpy.results.run.Run` and the figure registry in
:mod:`hydromodpy.display`. Saving and showing are driven by
``DisplayConfig`` (TOML ``[display]`` section).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from hydromodpy.display import get as _get_figure

if TYPE_CHECKING:
    from hydromodpy.display.config import DisplayConfig
    from hydromodpy.results.run import Run

logger = logging.getLogger(__name__)


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
) -> list[Path]:
    """Render the figures listed in ``display_cfg`` for one :class:`Run`.

    Honors ``display_cfg.enabled`` and ``display_cfg.save``. Unknown
    figure names are logged and skipped, not raised, so one bad entry
    never aborts a run. Returns the list of written file paths.
    """
    if not display_cfg.enabled:
        return []

    wanted = figure_names if figure_names is not None else list(display_cfg.figures)
    if not wanted:
        return []

    written: list[Path] = []
    output_dir = Path(output_dir)
    if display_cfg.save:
        output_dir.mkdir(parents=True, exist_ok=True)

    for name in wanted:
        try:
            fig = _get_figure(name)
        except KeyError:
            logger.warning("Unknown figure '%s' - skipped.", name)
            continue
        save_path = output_dir / f"{name}.png" if display_cfg.save else None
        try:
            fig.plot(sim, dpi=display_cfg.dpi, save_path=save_path)
        except Exception as exc:
            logger.warning("Skipping figure '%s': %s", name, exc)
            continue
        if save_path is not None:
            written.append(save_path)
            logger.info("Rendered figure '%s' → %s", name, save_path)
    return written
