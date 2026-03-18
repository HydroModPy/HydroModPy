"""Schema Pydantic du contrat TOML pour la distribution des maillages.

Ce module centralise la description declarative des parametres attendus dans
les fichiers TOML du package autonome `mesh`.

Objectifs :

- disposer d'une source de verite unique pour la validation ;
- associer une description courte a chaque parametre ;
- reutiliser ces descriptions dans la documentation et les exemples commentes.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from mesh.models import (
    ALLOWED_COLOR_FIELDS,
    ALLOWED_TOPOGRAPHY_FIELDS,
)


def _format_allowed_values(values: set[str]) -> str:
    """Formate une liste de valeurs admises pour les descriptions de schema."""
    return ", ".join(f"`{value}`" for value in sorted(values))


class PlotTomlSchema(BaseModel):
    """Schema Pydantic du bloc `[mesh_distribution.plot]`."""

    model_config = ConfigDict(extra="forbid")

    color_field: str = Field(
        default="geology_key",
        description=(
            "Champ utilise pour colorer les cellules du panneau structurel. "
            f"Valeurs admises : {_format_allowed_values(ALLOWED_COLOR_FIELDS)}."
        ),
    )
    color_map: str = Field(
        default="viridis",
        description=(
            "Nom de palette matplotlib applique au champ `color_field`."
        ),
    )
    figure_size: tuple[float, float] = Field(
        default=(11.0, 9.0),
        description=(
            "Dimensions de la figure sous la forme `[largeur, hauteur]` en pouces."
        ),
    )
    dpi: int = Field(
        default=160,
        gt=0,
        description="Resolution de sortie de la figure en DPI.",
    )
    title: str | None = Field(
        default=None,
        description=(
            "Titre explicite du panneau principal. Si absent, un titre automatique "
            "est construit a partir de `color_field`."
        ),
    )
    show_topography_panel: bool = Field(
        default=True,
        description=(
            "Active ou non le panneau topographique situe a droite de la figure."
        ),
    )
    topography_field: str = Field(
        default="z_top_mean",
        description=(
            "Champ cellule utilise pour le repli du panneau topographique quand "
            "les altitudes nodales ne suffisent pas. "
            f"Valeurs admises : {_format_allowed_values(ALLOWED_TOPOGRAPHY_FIELDS)}."
        ),
    )
    topography_cmap: str = Field(
        default="terrain",
        description="Nom de palette matplotlib du panneau topographique.",
    )
    topography_title: str | None = Field(
        default=None,
        description=(
            "Titre explicite du panneau topographique. Si absent, un titre "
            "automatique est construit."
        ),
    )
    show_mesh_edges: bool = Field(
        default=True,
        description="Affiche ou masque les aretes du maillage dans les panneaux.",
    )
    mesh_edge_color: str = Field(
        default="0.35",
        description=(
            "Couleur matplotlib utilisee pour les aretes du maillage, par "
            "exemple un niveau de gris (`\"0.35\"`) ou un nom de couleur."
        ),
    )
    mesh_edge_linewidth: float = Field(
        default=0.55,
        ge=0.0,
        description="Epaisseur des aretes du maillage en points.",
    )
    show_boundaries: bool = Field(
        default=True,
        description="Affiche ou masque les aretes de bord du domaine.",
    )
    show_geology_interfaces: bool = Field(
        default=True,
        description=(
            "Affiche ou masque les interfaces entre unites geologiques."
        ),
    )
    show_river_edges: bool = Field(
        default=True,
        description="Affiche ou masque les aretes identifiees comme rivieres.",
    )
    annotate_cell_ids: bool = Field(
        default=False,
        description=(
            "Ajoute ou non les identifiants de cellules au centroide de chaque "
            "maille."
        ),
    )

    @field_validator("color_field", mode="before")
    @classmethod
    def _normalize_color_field(cls, value: object) -> str:
        """Normalise puis valide `color_field`."""
        text = str(value).strip().lower()
        if text not in ALLOWED_COLOR_FIELDS:
            values = ", ".join(sorted(ALLOWED_COLOR_FIELDS))
            raise ValueError(f"color_field doit etre parmi : {values}.")
        return text

    @field_validator("topography_field", mode="before")
    @classmethod
    def _normalize_topography_field(cls, value: object) -> str:
        """Normalise puis valide `topography_field`."""
        text = str(value).strip().lower()
        if text not in ALLOWED_TOPOGRAPHY_FIELDS:
            values = ", ".join(sorted(ALLOWED_TOPOGRAPHY_FIELDS))
            raise ValueError(f"topography_field doit etre parmi : {values}.")
        return text

    @field_validator("color_map", "topography_cmap", "mesh_edge_color", mode="before")
    @classmethod
    def _normalize_required_text(cls, value: object) -> str:
        """Normalise une chaine obligatoire non vide."""
        text = str(value).strip()
        if text == "":
            raise ValueError("ce parametre ne peut pas etre vide.")
        return text

    @field_validator("title", "topography_title", mode="before")
    @classmethod
    def _normalize_optional_text(cls, value: object | None) -> str | None:
        """Convertit une chaine vide en `None`."""
        if value is None:
            return None
        text = str(value).strip()
        return None if text == "" else text

    @field_validator("figure_size")
    @classmethod
    def _validate_figure_size(
        cls,
        value: tuple[float, float],
    ) -> tuple[float, float]:
        """Verifie que la taille de figure est strictement positive."""
        width, height = value
        if width <= 0.0 or height <= 0.0:
            raise ValueError("figure_size doit contenir des valeurs > 0.")
        return value


class MeshDistributionTomlSchema(BaseModel):
    """Schema Pydantic du bloc `[mesh_distribution]`."""

    model_config = ConfigDict(extra="forbid")

    bundle_dir: Path = Field(
        description=(
            "Chemin vers le dossier bundle a relire. Il peut etre absolu ou "
            "relatif au fichier TOML."
        ),
    )
    figure_output_path: Path | None = Field(
        default=None,
        description=(
            "Chemin optionnel du PNG de synthese a ecrire. Si absent, aucune "
            "figure n'est enregistree sur disque."
        ),
    )
    summary_output_path: Path | None = Field(
        default=None,
        description=(
            "Chemin optionnel du resume JSON a ecrire. Si absent, aucun JSON "
            "n'est enregistre sur disque."
        ),
    )
    show_window: bool = Field(
        default=False,
        description=(
            "Ouvre ou non une fenetre matplotlib interactive a la fin de "
            "l'execution."
        ),
    )
    plot: PlotTomlSchema = Field(
        default_factory=PlotTomlSchema,
        description=(
            "Sous-configuration de trace et d'habillage graphique."
        ),
    )

    @field_validator("bundle_dir", mode="before")
    @classmethod
    def _normalize_required_path(cls, value: object) -> object:
        """Interdit un chemin obligatoire vide."""
        text = str(value).strip()
        if text == "":
            raise ValueError("bundle_dir est obligatoire.")
        return value

    @field_validator("figure_output_path", "summary_output_path", mode="before")
    @classmethod
    def _normalize_optional_path(cls, value: object | None) -> object | None:
        """Transforme une chaine vide en `None` pour les sorties optionnelles."""
        if value is None:
            return None
        text = str(value).strip()
        return None if text == "" else value


def get_toml_parameter_descriptions() -> dict[str, str]:
    """Retourne les descriptions humaines associees aux cles TOML publiques."""
    main_fields = MeshDistributionTomlSchema.model_fields
    plot_fields = PlotTomlSchema.model_fields
    return {
        "[mesh_distribution].bundle_dir": main_fields["bundle_dir"].description or "",
        "[mesh_distribution].figure_output_path": (
            main_fields["figure_output_path"].description or ""
        ),
        "[mesh_distribution].summary_output_path": (
            main_fields["summary_output_path"].description or ""
        ),
        "[mesh_distribution].show_window": (
            main_fields["show_window"].description or ""
        ),
        "[mesh_distribution.plot].color_field": (
            plot_fields["color_field"].description or ""
        ),
        "[mesh_distribution.plot].color_map": (
            plot_fields["color_map"].description or ""
        ),
        "[mesh_distribution.plot].figure_size": (
            plot_fields["figure_size"].description or ""
        ),
        "[mesh_distribution.plot].dpi": plot_fields["dpi"].description or "",
        "[mesh_distribution.plot].title": plot_fields["title"].description or "",
        "[mesh_distribution.plot].show_topography_panel": (
            plot_fields["show_topography_panel"].description or ""
        ),
        "[mesh_distribution.plot].topography_field": (
            plot_fields["topography_field"].description or ""
        ),
        "[mesh_distribution.plot].topography_cmap": (
            plot_fields["topography_cmap"].description or ""
        ),
        "[mesh_distribution.plot].topography_title": (
            plot_fields["topography_title"].description or ""
        ),
        "[mesh_distribution.plot].show_mesh_edges": (
            plot_fields["show_mesh_edges"].description or ""
        ),
        "[mesh_distribution.plot].mesh_edge_color": (
            plot_fields["mesh_edge_color"].description or ""
        ),
        "[mesh_distribution.plot].mesh_edge_linewidth": (
            plot_fields["mesh_edge_linewidth"].description or ""
        ),
        "[mesh_distribution.plot].show_boundaries": (
            plot_fields["show_boundaries"].description or ""
        ),
        "[mesh_distribution.plot].show_geology_interfaces": (
            plot_fields["show_geology_interfaces"].description or ""
        ),
        "[mesh_distribution.plot].show_river_edges": (
            plot_fields["show_river_edges"].description or ""
        ),
        "[mesh_distribution.plot].annotate_cell_ids": (
            plot_fields["annotate_cell_ids"].description or ""
        ),
    }


__all__ = [
    "MeshDistributionTomlSchema",
    "PlotTomlSchema",
    "ValidationError",
    "get_toml_parameter_descriptions",
]


