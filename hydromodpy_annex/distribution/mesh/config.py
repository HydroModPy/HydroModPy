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
    ALLOWED_COLOR_FIELDS,
    ALLOWED_TOPOGRAPHY_FIELDS,
    DEFAULT_TOML_SECTION,
    PlotConfig,
    VisualizationConfig,
)


def _require_mapping(raw_value: object, *, label: str) -> Mapping[str, Any]:
    """Verifie qu'un bloc TOML est bien une table cle -> valeur."""
    if not isinstance(raw_value, Mapping):
        raise ValueError(f"{label} doit etre une table TOML.")
    return raw_value


def _optional_text(raw_value: object | None) -> str | None:
    """Normalise une chaine optionnelle en supprimant les blancs inutiles."""
    if raw_value is None:
        return None
    text = str(raw_value).strip()
    return None if text == "" else text


def _parse_bool(raw_value: object, *, label: str) -> bool:
    """Valide un booleen explicite dans la configuration."""
    if isinstance(raw_value, bool):
        return raw_value
    raise ValueError(f"{label} doit etre un booleen.")


def _parse_positive_int(raw_value: object, *, label: str) -> int:
    """Valide un entier strictement positif."""
    try:
        value = int(raw_value)
    except Exception as exc:
        raise ValueError(f"{label} doit etre un entier.") from exc
    if value <= 0:
        raise ValueError(f"{label} doit etre > 0.")
    return value


def _parse_non_negative_float(raw_value: object, *, label: str) -> float:
    """Valide un reel positif ou nul."""
    try:
        value = float(raw_value)
    except Exception as exc:
        raise ValueError(f"{label} doit etre un nombre.") from exc
    if value < 0.0:
        raise ValueError(f"{label} doit etre >= 0.")
    return value


def _parse_figure_size(raw_value: object, *, label: str) -> tuple[float, float]:
    """Valide le format [largeur, hauteur] attendu dans le TOML."""
    if not isinstance(raw_value, (list, tuple)) or len(raw_value) != 2:
        raise ValueError(f"{label} doit etre un tableau [largeur, hauteur].")
    try:
        width = float(raw_value[0])
        height = float(raw_value[1])
    except Exception as exc:
        raise ValueError(f"{label} doit contenir deux nombres.") from exc
    if width <= 0.0 or height <= 0.0:
        raise ValueError(f"{label} doit contenir des valeurs > 0.")
    return (width, height)


def _resolve_config_path(
    *,
    config_path: Path,
    raw_value: object | None,
    required: bool,
    label: str,
) -> Path | None:
    """Resout un chemin relatif depuis le dossier du fichier TOML.

    Cette resolution locale est importante pour que le fichier de configuration
    reste portable lorsqu'il est partage avec un bundle.
    """

    text = _optional_text(raw_value)
    if text is None:
        if required:
            raise ValueError(f"{label} est obligatoire.")
        return None
    path = Path(text).expanduser()
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

    # On lit le sous-bloc de trace separement pour bien distinguer :
    # - les chemins et sorties ;
    # - les choix purement graphiques.
    plot_block = main_block.get("plot", {})
    if plot_block is None:
        plot_block = {}
    plot_block = _require_mapping(plot_block, label=f"[{section}.plot]")

    color_field = str(plot_block.get("color_field", "geology_key")).strip().lower()
    if color_field not in ALLOWED_COLOR_FIELDS:
        values = ", ".join(sorted(ALLOWED_COLOR_FIELDS))
        raise ValueError(f"[{section}.plot].color_field doit etre parmi : {values}.")

    topography_field = str(plot_block.get("topography_field", "z_top_mean")).strip().lower()
    if topography_field not in ALLOWED_TOPOGRAPHY_FIELDS:
        values = ", ".join(sorted(ALLOWED_TOPOGRAPHY_FIELDS))
        raise ValueError(f"[{section}.plot].topography_field doit etre parmi : {values}.")

    plot_config = PlotConfig(
        color_field=color_field,
        color_map=str(plot_block.get("color_map", "viridis")).strip() or "viridis",
        figure_size=_parse_figure_size(
            plot_block.get("figure_size", [11.0, 9.0]),
            label=f"[{section}.plot].figure_size",
        ),
        dpi=_parse_positive_int(
            plot_block.get("dpi", 160),
            label=f"[{section}.plot].dpi",
        ),
        title=_optional_text(plot_block.get("title")),
        show_topography_panel=_parse_bool(
            plot_block.get("show_topography_panel", True),
            label=f"[{section}.plot].show_topography_panel",
        ),
        topography_field=topography_field,
        topography_cmap=str(plot_block.get("topography_cmap", "terrain")).strip() or "terrain",
        topography_title=_optional_text(plot_block.get("topography_title")),
        show_mesh_edges=_parse_bool(
            plot_block.get("show_mesh_edges", True),
            label=f"[{section}.plot].show_mesh_edges",
        ),
        mesh_edge_color=str(plot_block.get("mesh_edge_color", "0.35")).strip() or "0.35",
        mesh_edge_linewidth=_parse_non_negative_float(
            plot_block.get("mesh_edge_linewidth", 0.55),
            label=f"[{section}.plot].mesh_edge_linewidth",
        ),
        show_boundaries=_parse_bool(
            plot_block.get("show_boundaries", True),
            label=f"[{section}.plot].show_boundaries",
        ),
        show_geology_interfaces=_parse_bool(
            plot_block.get("show_geology_interfaces", True),
            label=f"[{section}.plot].show_geology_interfaces",
        ),
        show_river_edges=_parse_bool(
            plot_block.get("show_river_edges", True),
            label=f"[{section}.plot].show_river_edges",
        ),
        annotate_cell_ids=_parse_bool(
            plot_block.get("annotate_cell_ids", False),
            label=f"[{section}.plot].annotate_cell_ids",
        ),
    )

    return VisualizationConfig(
        bundle_dir=_resolve_config_path(
            config_path=config_path,
            raw_value=main_block.get("bundle_dir"),
            required=True,
            label=f"[{section}].bundle_dir",
        ),
        figure_output_path=_resolve_config_path(
            config_path=config_path,
            raw_value=main_block.get("figure_output_path"),
            required=False,
            label=f"[{section}].figure_output_path",
        ),
        summary_output_path=_resolve_config_path(
            config_path=config_path,
            raw_value=main_block.get("summary_output_path"),
            required=False,
            label=f"[{section}].summary_output_path",
        ),
        show_window=_parse_bool(
            main_block.get("show_window", False),
            label=f"[{section}].show_window",
        ),
        plot=plot_config,
    )


__all__ = [
    "load_toml_config",
]
