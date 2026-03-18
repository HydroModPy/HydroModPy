"""Modeles et contrats de donnees pour la distribution des maillages.

Ce module centralise les objets Python partages par le sous-package :

- constantes publiques ;
- protocoles minimaux attendus pour un bundle ;
- dataclasses de configuration et de travail.

L'objectif est d'eviter que la structure des donnees soit redefinie dans
plusieurs modules a la fois.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

DEFAULT_CONFIG_FILENAME = "config_example.toml"
DEFAULT_TOML_SECTION = "mesh_distribution"

# =============================================================================
# Champs publics disponibles dans le bundle
# =============================================================================
#
# Ces constantes servent a valider le TOML et a documenter les champs que
# l'utilisateur peut demander dans les figures.
#
# Les champs ci-dessous sont ceux qui existent deja dans le bundle exporte.
NUMERIC_COLOR_FIELDS = {
    "area_m2",
    "z_top_centroid",
    "z_top_mean",
    "hydraulic_conductivity_m_s",
    "storage_coefficient",
}
CATEGORICAL_COLOR_FIELDS = {
    "geology_code",
    "geology_key",
}
ALLOWED_COLOR_FIELDS = NUMERIC_COLOR_FIELDS | CATEGORICAL_COLOR_FIELDS
ALLOWED_TOPOGRAPHY_FIELDS = {
    "z_top_centroid",
    "z_top_mean",
}


class MeshNodeLike(Protocol):
    """Structure minimale attendue pour un noeud du bundle."""

    node_id: int
    x: float
    y: float
    z_top: float | None


class MeshCellLike(Protocol):
    """Structure minimale attendue pour une cellule du bundle."""

    cell_id: int
    geom_type: str
    node_indices: tuple[int, ...]
    centroid_x: float
    centroid_y: float
    area_m2: float
    z_top_centroid: float | None
    z_top_mean: float | None
    geology_code: int | None
    geology_key: str
    hydraulic_conductivity_m_s: float | None
    storage_coefficient: float | None


class MeshEdgeLike(Protocol):
    """Structure minimale attendue pour une arete du bundle."""

    edge_id: int
    node_a: int
    node_b: int
    cell_a: int
    cell_b: int | None
    length_m: float
    edge_kind: str
    is_river: bool
    geology_a_key: str
    geology_b_key: str


class GeologyFractionLike(Protocol):
    """Structure minimale attendue pour une fraction geologique."""

    cell_id: int
    geology_key: str
    fraction: float


class MeshBundleLike(Protocol):
    """Structure minimale attendue pour le bundle relu en memoire."""

    bundle_dir: Path
    metadata: dict[str, Any]
    nodes: Sequence[MeshNodeLike]
    cells: Sequence[MeshCellLike]
    edges: Sequence[MeshEdgeLike]
    geology_fractions: Sequence[GeologyFractionLike]
    mesh_summary: dict[str, Any] | None

    @property
    def n_nodes(self) -> int: ...

    @property
    def n_cells(self) -> int: ...

    @property
    def n_edges(self) -> int: ...

    @property
    def mesh_path(self) -> Path: ...


@dataclass(frozen=True)
class PlotConfig:
    """Parametres d'affichage des figures.

    Cette classe regroupe uniquement les choix visuels :
    - champ de coloriage principal ;
    - palette ;
    - dimensions de la figure ;
    - presence des surcouches et du panneau topographique.

    L'idee est de separer clairement :
    - ce qui releve de la lecture des donnees ;
    - ce qui releve du rendu graphique.
    """

    color_field: str = "geology_key"
    color_map: str = "viridis"
    figure_size: tuple[float, float] = (11.0, 9.0)
    dpi: int = 160
    title: str | None = None
    show_topography_panel: bool = True
    topography_field: str = "z_top_mean"
    topography_cmap: str = "terrain"
    topography_title: str | None = None
    show_mesh_edges: bool = True
    mesh_edge_color: str = "0.35"
    mesh_edge_linewidth: float = 0.55
    show_boundaries: bool = True
    show_geology_interfaces: bool = True
    show_river_edges: bool = True
    annotate_cell_ids: bool = False


@dataclass(frozen=True)
class VisualizationConfig:
    """Configuration complete d'une execution.

    Cette classe porte :
    - le chemin du bundle a lire ;
    - les chemins optionnels de sortie ;
    - le mode interactif ou non ;
    - la sous-configuration de trace.
    """

    bundle_dir: Path
    figure_output_path: Path | None = None
    summary_output_path: Path | None = None
    show_window: bool = False
    plot: PlotConfig = PlotConfig()


@dataclass(frozen=True)
class MeshVisualizationData:
    """Objet de travail central du module de distribution.

    On y trouve a la fois :
    - le maillage relu depuis le bundle ;
    - la configuration de visualisation associee.

    Cet objet est volontairement simple afin d'etre passe tel quel aux autres
    briques du sous-package.
    """

    mesh: MeshBundleLike
    config: VisualizationConfig


__all__ = [
    "ALLOWED_COLOR_FIELDS",
    "ALLOWED_TOPOGRAPHY_FIELDS",
    "CATEGORICAL_COLOR_FIELDS",
    "DEFAULT_CONFIG_FILENAME",
    "DEFAULT_TOML_SECTION",
    "GeologyFractionLike",
    "MeshBundleLike",
    "MeshCellLike",
    "MeshEdgeLike",
    "MeshNodeLike",
    "MeshVisualizationData",
    "NUMERIC_COLOR_FIELDS",
    "PlotConfig",
    "VisualizationConfig",
]
