"""Private worker helpers for ``hmp viz`` actions."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


def render_figure(
    sim_ref: str,
    figure: str,
    *,
    workspace: Any = None,
    output: Any = None,
    time: str | None = None,
    options: Mapping[str, Any] | None = None,
) -> Path:
    """Render one registered figure for a simulation. Returns the file written.

    The figure gets the options the run's own ``[display]`` gave it (its
    ``time`` and its ``[display.overrides]``), so it redraws the figure the
    run drew. ``time`` replaces the instant: a date, ``"first"`` or
    ``"last"``. Without an explicit ``output`` the figure is written inside
    the run it describes, at ``runs/<run>/figures/<figure>.png``; an
    ``output`` without a suffix is written as ``<output>.png``. The index is
    opened read-only: rendering a figure reads a run, it never rewrites its
    index. A figure the run cannot feed raises ``ValueError`` with its reason
    and writes no PNG. ``options`` are figure options, such as the ones
    :func:`parse_figure_options` reads from ``--opt``: they replace the ones
    the run gave the figure.
    """
    from hydromodpy.core.state.result_dirs import resolve_project_root
    from hydromodpy.display.runs import figure_options_from_run, figures_dir_of, record_figure
    from hydromodpy.display.runs import render_figure as render_one_figure
    from hydromodpy.results.catalog import Catalog

    workspace_root = resolve_project_root(
        Path(workspace).expanduser().resolve() if workspace else Path.cwd().resolve()
    )
    with Catalog(workspace_root) as catalog:
        sid = catalog.resolve(sim_ref)
        sim = catalog[sid]
        figures_dir = figures_dir_of(catalog.run_dir_for(sid))
        save = Path(output).expanduser().resolve() if output else figures_dir / f"{figure}.png"
        if save.suffix == "":
            save = save.with_suffix(".png")
        drawn = dict(figure_options_from_run(sim, figure))
        drawn.update(options or {})
        if time is not None:
            drawn["time"] = time
        save.parent.mkdir(parents=True, exist_ok=True)
        render_one_figure(figure, sim, save=save, run_dir=figures_dir.parent, **drawn)
        if save.parent.resolve() == figures_dir.resolve():
            record_figure(save, name=figure, options=drawn, sim=sim, figures_dir=figures_dir)
        return save


def regen_figures(sim_ref: str, *, workspace: Any = None) -> list[Path]:
    """Draw again every figure the ledger of a run records; return the files written.

    The index is opened read-only: the figures are files of the run directory.
    """
    from hydromodpy.core.state.result_dirs import resolve_project_root
    from hydromodpy.display.runs import log_render_summary
    from hydromodpy.display.runs import regen_figures as regen_run_figures
    from hydromodpy.results.catalog import Catalog

    workspace_root = resolve_project_root(
        Path(workspace).expanduser().resolve() if workspace else Path.cwd().resolve()
    )
    with Catalog(workspace_root) as catalog:
        sid = catalog.resolve(sim_ref)
        run_dir = catalog.run_dir_for(sid)
        report = regen_run_figures(catalog[sid], run_dir)
    log_render_summary(report, destination=run_dir)
    return list(report.written)


def parse_figure_options(figure: str, items: Sequence[str]) -> dict[str, Any]:
    """Read ``NAME=VALUE`` items into the options of ``figure``, typed as it declares them.

    A value is read as a TOML value first, as ``[display.overrides]`` writes
    it: ``false``, ``12``, ``1e-4``, ``[8, 5]``, ``"text"``. A value that is
    not one is the bare text, so ``title=Water table`` needs no quotes, and
    ``title=`` is the empty string, which removes the title. The value is then
    checked against the type of the option. Raises ``ValueError`` for an item
    without ``=``, an option the figure does not take, or a value of the wrong
    type, naming what the figure takes. An option that takes a Python object,
    such as another run, is refused with the ``hmp.figure`` call that sets it.
    """
    from hydromodpy.display.figure_registry import (
        figure_option_types,
        figure_python_only_options,
    )

    types = figure_option_types(figure)
    python_only = figure_python_only_options(figure)
    options: dict[str, Any] = {}
    for item in items:
        name, sep, raw = str(item).partition("=")
        name = name.strip()
        if not sep or not name:
            raise ValueError(f"--opt {item!r}: write NAME=VALUE, as in --opt show_run_name=false.")
        if name not in types:
            raise ValueError(
                f"figure '{figure}' has no option '{name}'; it takes: {', '.join(sorted(types))}."
            )
        if name in python_only:
            raise ValueError(
                f"figure '{figure}', option '{name}' takes a Python object: "
                f"pass it to hmp.figure(run, '{figure}', {name}=...)."
            )
        options[name] = _typed_option(figure, name, raw, types[name])
    return options


def _typed_option(figure: str, name: str, raw: str, annotation: Any) -> Any:
    """One ``--opt`` value, read as TOML then checked against the option type."""
    import tomllib

    from pydantic import TypeAdapter, ValidationError

    try:
        candidates: list[Any] = [tomllib.loads(f"value = {raw}")["value"], raw]
    except tomllib.TOMLDecodeError:
        candidates = [raw]
    if annotation is None:
        return candidates[0]
    adapter = TypeAdapter(annotation)
    last_error: ValidationError | None = None
    for candidate in candidates:
        try:
            return adapter.validate_python(candidate)
        except ValidationError as exc:
            last_error = exc
    reason = last_error.errors()[0]["msg"] if last_error is not None else "invalid value"
    raise ValueError(f"figure '{figure}', option '{name}' = {raw!r}: {reason}.")


def figure_availability(sim_ref: str, *, workspace: Any = None) -> list[tuple[Any, str | None]]:
    """Return every registered figure with the reason the run cannot feed it.

    ``None`` marks a figure the run supports. The index is opened read-only.
    """
    from hydromodpy.core.state.result_dirs import resolve_project_root
    from hydromodpy.display.runs import figure_availability as availability_of
    from hydromodpy.results.catalog import Catalog

    workspace_root = resolve_project_root(
        Path(workspace).expanduser().resolve() if workspace else Path.cwd().resolve()
    )
    with Catalog(workspace_root) as catalog:
        return availability_of(catalog[catalog.resolve(sim_ref)])
