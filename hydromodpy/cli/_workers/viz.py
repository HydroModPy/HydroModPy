"""Private worker helpers for ``hmp viz`` actions."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def render_figure(
    sim_ref: str,
    figure: str,
    *,
    workspace: Any = None,
    output: Any = None,
) -> Path:
    """Render one registered figure for a simulation. Returns the output path."""
    from hydromodpy.cli.helpers import find_catalog_root
    from hydromodpy.display import get as get_figure
    from hydromodpy.results.catalog import Catalog

    workspace_root = find_catalog_root(
        Path(workspace).expanduser().resolve() if workspace else Path.cwd().resolve()
    )
    with Catalog(workspace_root) as catalog:
        sim = catalog[sim_ref]
        save = (
            Path(output).expanduser().resolve()
            if output
            else Path.cwd() / "figures" / f"{figure}.png"
        )
        save.parent.mkdir(parents=True, exist_ok=True)
        get_figure(figure).plot(sim, save_path=save)
        return save


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
    """Render the ``[display]`` figure gallery for one or several runs."""
    from hydromodpy.core.toml_io.loader import load_toml_with_base_config
    from hydromodpy.display.config import DisplayConfig
    from hydromodpy.display.runs import render_figures_for_run, resolve_run_output_dir
    from hydromodpy.results.catalog import Catalog

    target_path = Path(config_toml).expanduser()
    if not target_path.is_file() or target_path.suffix != ".toml":
        raise ValueError(f"Expected a TOML file: {target_path}")

    raw_toml = load_toml_with_base_config(target_path)
    display_cfg = DisplayConfig.model_validate(raw_toml.get("display", {}))
    if no_show:
        display_cfg.show = False
    project_dir = target_path.parent.resolve()
    config_source = str(target_path.resolve())

    written_paths: list[Path] = []
    with Catalog(project_dir) as catalog:
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
            written_paths.extend(
                render_figures_for_run(sim, display_cfg, output_dir=out_dir, figure_names=only)
            )
    return written_paths
