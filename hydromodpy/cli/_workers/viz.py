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
    from hydromodpy.core.state.paths import resolve_project_root
    from hydromodpy.display.runs import figure_options_from_run
    from hydromodpy.display.runs import render_figure as render_one_figure
    from hydromodpy.results.catalog import Catalog
    from hydromodpy.results.storage.contract import RUN_FIGURES_DIRNAME

    workspace_root = resolve_project_root(
        Path(workspace).expanduser().resolve() if workspace else Path.cwd().resolve()
    )
    with Catalog(workspace_root, read_only=True) as catalog:
        sid = catalog.resolve(sim_ref)
        sim = catalog[sid]
        save = (
            Path(output).expanduser().resolve()
            if output
            else catalog.run_dir_for(sid) / RUN_FIGURES_DIRNAME / f"{figure}.png"
        )
        if save.suffix == "":
            save = save.with_suffix(".png")
        drawn = dict(figure_options_from_run(sim, figure))
        drawn.update(options or {})
        if time is not None:
            drawn["time"] = time
        save.parent.mkdir(parents=True, exist_ok=True)
        render_one_figure(figure, sim, save=save, **drawn)
        return save


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
    from hydromodpy.core.state.paths import resolve_project_root
    from hydromodpy.display.runs import figure_availability as availability_of
    from hydromodpy.results.catalog import Catalog

    workspace_root = resolve_project_root(
        Path(workspace).expanduser().resolve() if workspace else Path.cwd().resolve()
    )
    with Catalog(workspace_root, read_only=True) as catalog:
        return availability_of(catalog[catalog.resolve(sim_ref)])


def render_gallery(
    config_toml: Any,
    *,
    run_name: str | None = None,
    sim_ref: str | None = None,
    all_runs: bool = False,
    latest: int | None = None,
    only: list[str] | None = None,
    no_show: bool = False,
) -> list[Path]:
    """Render the ``[display]`` figure gallery for one or several runs.

    Each run gets its own summary line, so a figure the gallery was asked for
    and could not produce is reported here exactly as it is on the run path.
    """
    from hydromodpy.config.config_migration import migrate_config_doc_on_load
    from hydromodpy.core.toml_io.loader import load_toml_with_base_config
    from hydromodpy.display.config import DisplayConfig
    from hydromodpy.display.runs import (
        log_render_summary,
        render_figures_for_run,
        resolve_run_output_dir,
    )
    from hydromodpy.results.catalog import Catalog
    from hydromodpy.results.catalog.registration import portable_config_source

    target_path = Path(config_toml).expanduser()
    if not target_path.is_file() or target_path.suffix != ".toml":
        raise ValueError(f"Expected a TOML file: {target_path}")

    raw_toml = load_toml_with_base_config(target_path)
    # The same in-memory migration `hmp run` applies, so an old key loads and
    # is reported the same way on both commands.
    migrate_config_doc_on_load(raw_toml, source=target_path)
    display_cfg = DisplayConfig.model_validate(raw_toml.get("display", {}))
    if no_show:
        display_cfg.show = False
    project_dir = target_path.parent.resolve()
    # The index stores the config path relative to the project, so a copied or
    # moved project still recognises the runs it owns.
    config_source = portable_config_source(project_dir, target_path)

    written_paths: list[Path] = []
    with Catalog(project_dir, read_only=True) as catalog:
        sims = catalog.list_simulations(config_source=config_source, order_by="created_at DESC")
        if sims.empty:
            sims = catalog.list_simulations(project=project_dir.name, order_by="created_at DESC")
        if sims.empty:
            raise FileNotFoundError(f"No simulations found for {target_path.name}.")

        if sim_ref:
            # Route through the single canonical resolver (UUID / prefix / name /
            # stem / @-selectors), not a bespoke startswith matcher.
            ids = [catalog.resolve(sim_ref, project=project_dir.name)]
        elif run_name:
            subset = sims[sims["name"] == run_name]
            if subset.empty:
                raise FileNotFoundError(f"No run named {run_name!r}")
            ids = [str(sid) for sid in subset["sim_id"].tolist()]
        elif all_runs:
            ids = [str(sid) for sid in sims["sim_id"].tolist()]
        elif latest is not None and latest > 0:
            ids = [str(sid) for sid in sims["sim_id"].tolist()[:latest]]
        else:
            ids = [str(sims.iloc[0]["sim_id"])]

        for sid in ids:
            sim = catalog[sid]
            out_dir = resolve_run_output_dir(
                display_cfg, project_root=project_dir, run_name=sim.name, sim_id=sid
            )
            report = render_figures_for_run(sim, display_cfg, output_dir=out_dir, figure_names=only)
            log_render_summary(report, destination=out_dir)
            written_paths.extend(report.written)
    return written_paths
