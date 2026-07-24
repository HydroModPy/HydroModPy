"""Per-run figure rendering helpers.

Bridges :class:`~hydromodpy.results.run.Run` and the figure registry in
:mod:`hydromodpy.display`. Saving and showing are driven by
``DisplayConfig`` (TOML ``[display]`` section).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from hydromodpy.core.logging import get_logger
from hydromodpy.display import get as _get_figure
from hydromodpy.display.renderer import matplotlib_backend
from hydromodpy.display.theme import apply_theme

if TYPE_CHECKING:
    from hydromodpy.display.config import DisplayConfig
    from hydromodpy.results.run import Run

logger = get_logger(__name__)


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

    Honors ``display_cfg.enabled`` and ``display_cfg.save``. A figure whose
    declared requirements are not met by this run (no particle process, no
    calibration, a solver that does not produce the field) is reported as
    not applicable and skipped. A figure that fails while rendering raises
    or is logged depending on ``display_cfg.on_error``. Returns the list of
    written file paths.
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

    with matplotlib_backend(interactive=_backend_is_interactive(display_cfg), dpi=display_cfg.dpi):
        apply_theme(display_cfg.preset)
        for name in wanted:
            fig = _get_figure(name)
            reason = fig.unavailable_reason(sim)
            if reason is not None:
                # Skips are the norm (a run rarely feeds every figure); keep
                # them out of the console. The batch summary reports the count.
                logger.debug("Figure '%s' not applicable to this run: %s.", name, reason)
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
                continue
            if display_cfg.show:
                import matplotlib.pyplot as plt

                plt.show()
            if save_path is not None:
                written.append(save_path)
                logger.debug("Rendered figure '%s' -> %s", name, save_path)
    return written
