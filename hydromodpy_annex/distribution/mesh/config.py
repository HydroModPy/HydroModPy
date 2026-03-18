"""Lecture et validation TOML pour la distribution des maillages.

Ce module se concentre uniquement sur la transformation d'un fichier de
configuration en objets Python valides. Il ne charge pas le bundle lui-meme.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import tomllib
from typing import Any

from hydromodpy_annex.distribution.mesh.models import (
    DEFAULT_TOML_SECTION,
    PlotConfig,
    VisualizationConfig,
)
from hydromodpy_annex.distribution.mesh.toml_schema import (
    MeshDistributionTomlSchema,
    ValidationError,
)


def _require_mapping(raw_value: object, *, label: str) -> Mapping[str, Any]:
    """Verifie qu'un bloc TOML est bien une table cle -> valeur."""
    if not isinstance(raw_value, Mapping):
        raise ValueError(f"{label} doit etre une table TOML.")
    return raw_value


def _resolve_config_path(
    *,
    config_path: Path,
    raw_value: Path | None,
) -> Path | None:
    """Resout un chemin relatif depuis le dossier du fichier TOML.

    Cette resolution locale est importante pour que le fichier de configuration
    reste portable lorsqu'il est partage avec un bundle.
    """
    if raw_value is None:
        return None
    path = Path(raw_value).expanduser()
    if not path.is_absolute():
        path = (config_path.parent / path).resolve()
    return path


def load_toml_config(
    toml_path: str | Path,
    *,
    section: str = DEFAULT_TOML_SECTION,
) -> VisualizationConfig:
    """Charge la configuration TOML du module de distribution.

    Le fichier est structure en deux niveaux :

    - `[mesh_distribution]` pour les chemins et les sorties ;
    - `[mesh_distribution.plot]` pour les choix de representation.

    Seuls les noms anglais du contrat courant sont acceptes.
    """

    config_path = Path(toml_path).resolve()
    content = tomllib.loads(config_path.read_text(encoding="utf-8-sig"))
    main_block = _require_mapping(content.get(section), label=f"[{section}]")

    try:
        parsed = MeshDistributionTomlSchema.model_validate(dict(main_block))
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc

    plot_config = PlotConfig(
        color_field=parsed.plot.color_field,
        color_map=parsed.plot.color_map,
        figure_size=parsed.plot.figure_size,
        dpi=parsed.plot.dpi,
        title=parsed.plot.title,
        show_topography_panel=parsed.plot.show_topography_panel,
        topography_field=parsed.plot.topography_field,
        topography_cmap=parsed.plot.topography_cmap,
        topography_title=parsed.plot.topography_title,
        show_mesh_edges=parsed.plot.show_mesh_edges,
        mesh_edge_color=parsed.plot.mesh_edge_color,
        mesh_edge_linewidth=parsed.plot.mesh_edge_linewidth,
        show_boundaries=parsed.plot.show_boundaries,
        show_geology_interfaces=parsed.plot.show_geology_interfaces,
        show_river_edges=parsed.plot.show_river_edges,
        annotate_cell_ids=parsed.plot.annotate_cell_ids,
    )

    return VisualizationConfig(
        bundle_dir=_resolve_config_path(
            config_path=config_path,
            raw_value=parsed.bundle_dir,
        ),
        figure_output_path=_resolve_config_path(
            config_path=config_path,
            raw_value=parsed.figure_output_path,
        ),
        summary_output_path=_resolve_config_path(
            config_path=config_path,
            raw_value=parsed.summary_output_path,
        ),
        show_window=parsed.show_window,
        plot=plot_config,
    )


__all__ = [
    "load_toml_config",
]
