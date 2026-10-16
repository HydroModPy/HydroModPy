"""Path resolution helpers for the site-selection workflow."""

from __future__ import annotations

from pathlib import Path

from hydromodpy.spatial.site_selection.config import SiteSelectionConfig


def _resolve_paths(cfg: SiteSelectionConfig, *, base_dir: Path) -> SiteSelectionConfig:
    output_root = _resolve_optional_path(cfg.output_root, base_dir=base_dir)
    dem = cfg.dem
    dem_path = _resolve_optional_path(dem.path, base_dir=base_dir)
    outlets = cfg.outlets
    reference_network_path = _resolve_optional_path(
        outlets.reference_network_path,
        base_dir=base_dir,
    )
    territory = cfg.territory
    polygon_file = _resolve_optional_path(territory.polygon_file, base_dir=base_dir)
    input_cfg = cfg.input
    catchments_csv = _resolve_optional_path(input_cfg.catchments_csv, base_dir=base_dir)
    workspace_root = _resolve_optional_path(input_cfg.workspace_root, base_dir=base_dir)
    data_root = _resolve_optional_path(input_cfg.data_root, base_dir=base_dir)
    map_context = cfg.map_context
    context_layers = [
        layer.model_copy(update={"path": _resolve_optional_path(layer.path, base_dir=base_dir)})
        for layer in map_context.layers
    ]
    criteria = cfg.criteria
    influence = criteria.influence
    influence_layers = [
        layer.model_copy(update={"path": _resolve_optional_path(layer.path, base_dir=base_dir)})
        for layer in influence.layers
    ]
    geology = criteria.geology
    geology_layers = [
        layer.model_copy(update={"path": _resolve_optional_path(layer.path, base_dir=base_dir)})
        for layer in geology.layers
    ]
    observations = criteria.observations
    piezometer_layers = [
        layer.model_copy(update={"path": _resolve_optional_path(layer.path, base_dir=base_dir)})
        for layer in observations.piezometer_layers
    ]
    return cfg.model_copy(
        update={
            "output_root": output_root,
            "dem": dem.model_copy(update={"path": dem_path}),
            "outlets": outlets.model_copy(
                update={"reference_network_path": reference_network_path}
            ),
            "territory": territory.model_copy(update={"polygon_file": polygon_file}),
            "input": input_cfg.model_copy(
                update={
                    "catchments_csv": catchments_csv,
                    "workspace_root": workspace_root,
                    "data_root": data_root,
                }
            ),
            "criteria": criteria.model_copy(
                update={
                    "influence": influence.model_copy(update={"layers": influence_layers}),
                    "geology": geology.model_copy(update={"layers": geology_layers}),
                    "observations": observations.model_copy(
                        update={"piezometer_layers": piezometer_layers}
                    ),
                }
            ),
            "map_context": map_context.model_copy(update={"layers": context_layers}),
        },
    )


def _with_default_data_root(
    cfg: SiteSelectionConfig,
    data_root: str | Path | None = None,
) -> SiteSelectionConfig:
    """Return ``cfg`` with an isolated default data root for executable runs."""

    resolved_data_root = (
        Path(data_root).expanduser().resolve()
        if data_root is not None
        else cfg.input.data_root or cfg.output_root / "data"
    )
    return cfg.model_copy(
        update={"input": cfg.input.model_copy(update={"data_root": resolved_data_root})}
    )


def _data_access_error(
    family: str,
    *,
    data_root: str | Path | None,
    detail: Exception,
) -> str:
    root = "<default>" if data_root is None else str(Path(data_root).expanduser())
    section = "[hydrometry]" if family == "hydrometry" else "[data.dem]"
    return (
        f"site_selection failed while loading {family} data. "
        f"data_root={root}. Check [site_selection.input].data_root, the matching "
        f"{section} TOML section, and provider cache permissions. "
        f"Original error: {type(detail).__name__}: {detail}"
    )


def _resolve_optional_path(path: Path | None, *, base_dir: Path) -> Path | None:
    if path is None:
        return None
    expanded = Path(path).expanduser()
    if expanded.is_absolute():
        return expanded
    return (base_dir / expanded).resolve()


def _resolve_csv_path(value: object, *, base_dir: Path) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    path = Path(text).expanduser()
    if path.is_absolute():
        return str(path)
    return str((base_dir / path).resolve())


def _path_or_none(path: Path | None) -> str | None:
    return None if path is None else str(path)
