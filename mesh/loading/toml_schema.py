"""Validation legere du contrat TOML pour la distribution des maillages."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path

from mesh.schema import (
    ALLOWED_COLOR_FIELDS,
    ALLOWED_TOPOGRAPHY_FIELDS,
    PlotConfig,
)


class ValidationError(ValueError):
    """Erreur de validation du contrat TOML public."""


def _format_allowed_values(values: set[str]) -> str:
    """Formate une liste de valeurs admises pour les descriptions publiques."""
    return ", ".join(f"`{value}`" for value in sorted(values))


_MAIN_LABEL = "[mesh_distribution]"
_PLOT_LABEL = "[mesh_distribution.plot]"

_MAIN_ALLOWED_KEYS = {
    "bundle_dir",
    "figure_output_path",
    "summary_output_path",
    "show_window",
    "plot",
}
_PLOT_ALLOWED_KEYS = {
    "color_field",
    "color_map",
    "figure_size",
    "dpi",
    "title",
    "show_topography_panel",
    "topography_field",
    "topography_cmap",
    "topography_title",
    "show_mesh_edges",
    "mesh_edge_color",
    "mesh_edge_linewidth",
    "show_boundaries",
    "show_geology_interfaces",
    "show_river_edges",
    "annotate_cell_ids",
}

_TOML_PARAMETER_DESCRIPTIONS = {
    "[mesh_distribution].bundle_dir": (
        "Chemin vers le dossier bundle a relire. Il peut etre absolu ou "
        "relatif au fichier TOML."
    ),
    "[mesh_distribution].figure_output_path": (
        "Chemin optionnel du PNG de synthese a ecrire. Si absent, aucune "
        "figure n'est enregistree sur disque."
    ),
    "[mesh_distribution].summary_output_path": (
        "Chemin optionnel du resume JSON a ecrire. Si absent, aucun JSON "
        "n'est enregistre sur disque."
    ),
    "[mesh_distribution].show_window": (
        "Ouvre ou non une fenetre matplotlib interactive a la fin de l'execution."
    ),
    "[mesh_distribution.plot].color_field": (
        "Champ utilise pour colorer les cellules du panneau structurel. "
        f"Valeurs admises : {_format_allowed_values(ALLOWED_COLOR_FIELDS)}."
    ),
    "[mesh_distribution.plot].color_map": (
        "Nom de palette matplotlib applique au champ `color_field`."
    ),
    "[mesh_distribution.plot].figure_size": (
        "Dimensions de la figure sous la forme `[largeur, hauteur]` en pouces."
    ),
    "[mesh_distribution.plot].dpi": "Resolution de sortie de la figure en DPI.",
    "[mesh_distribution.plot].title": (
        "Titre explicite du panneau principal. Si absent, un titre automatique "
        "est construit a partir de `color_field`."
    ),
    "[mesh_distribution.plot].show_topography_panel": (
        "Active ou non le panneau topographique situe a droite de la figure."
    ),
    "[mesh_distribution.plot].topography_field": (
        "Champ cellule utilise pour le repli du panneau topographique quand "
        "les altitudes nodales ne suffisent pas. "
        f"Valeurs admises : {_format_allowed_values(ALLOWED_TOPOGRAPHY_FIELDS)}."
    ),
    "[mesh_distribution.plot].topography_cmap": (
        "Nom de palette matplotlib du panneau topographique."
    ),
    "[mesh_distribution.plot].topography_title": (
        "Titre explicite du panneau topographique. Si absent, un titre "
        "automatique est construit."
    ),
    "[mesh_distribution.plot].show_mesh_edges": (
        "Affiche ou masque les aretes du maillage dans les panneaux."
    ),
    "[mesh_distribution.plot].mesh_edge_color": (
        "Couleur matplotlib utilisee pour les aretes du maillage, par "
        'exemple un niveau de gris (`"0.35"`) ou un nom de couleur.'
    ),
    "[mesh_distribution.plot].mesh_edge_linewidth": (
        "Epaisseur des aretes du maillage en points."
    ),
    "[mesh_distribution.plot].show_boundaries": (
        "Affiche ou masque les aretes de bord du domaine."
    ),
    "[mesh_distribution.plot].show_geology_interfaces": (
        "Affiche ou masque les interfaces entre unites geologiques."
    ),
    "[mesh_distribution.plot].show_river_edges": (
        "Affiche ou masque les aretes identifiees comme rivieres."
    ),
    "[mesh_distribution.plot].annotate_cell_ids": (
        "Ajoute ou non les identifiants de cellules au centroide de chaque maille."
    ),
}


def _require_mapping(raw_value: object, *, label: str) -> Mapping[str, object]:
    """Verifie qu'un bloc TOML est bien une table cle -> valeur."""
    if not isinstance(raw_value, Mapping):
        raise ValidationError(f"{label} doit etre une table TOML.")
    return raw_value


def _forbid_unknown_keys(
    raw_mapping: Mapping[str, object],
    *,
    allowed_keys: set[str],
    label: str,
) -> None:
    """Interdit les cles publiques inconnues pour garder un contrat net."""
    unknown_keys = sorted(set(raw_mapping) - allowed_keys)
    if unknown_keys:
        raise ValidationError(
            f"{label} contient des cles inconnues : {', '.join(unknown_keys)}."
        )


def _coerce_required_text(value: object, *, label: str) -> str:
    if value is None:
        raise ValidationError(f"{label} est obligatoire.")
    text = str(value).strip()
    if text == "":
        raise ValidationError(f"{label} est obligatoire.")
    return text


def _coerce_optional_text(value: object | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return None if text == "" else text


def _coerce_path(value: object, *, label: str) -> Path:
    if value is None:
        raise ValidationError(f"{label} est obligatoire.")
    text = str(value).strip()
    if text == "":
        raise ValidationError(f"{label} est obligatoire.")
    return Path(text)


def _coerce_optional_path(value: object | None) -> Path | None:
    if value is None:
        return None
    text = str(value).strip()
    return None if text == "" else Path(text)


def _coerce_bool(value: object, *, label: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "on"}:
        return True
    if text in {"false", "0", "no", "off"}:
        return False
    raise ValidationError(f"{label} doit etre un booleen.")


def _coerce_positive_int(value: object, *, label: str) -> int:
    if isinstance(value, bool):
        raise ValidationError(f"{label} doit etre un entier > 0.")
    try:
        coerced = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{label} doit etre un entier > 0.") from exc
    if isinstance(value, float) and not value.is_integer():
        raise ValidationError(f"{label} doit etre un entier > 0.")
    if coerced <= 0:
        raise ValidationError(f"{label} doit etre un entier > 0.")
    return coerced


def _coerce_non_negative_float(value: object, *, label: str) -> float:
    try:
        coerced = float(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{label} doit etre un nombre >= 0.") from exc
    if coerced < 0.0:
        raise ValidationError(f"{label} doit etre un nombre >= 0.")
    return coerced


def _coerce_figure_size(value: object) -> tuple[float, float]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValidationError("figure_size doit contenir exactement deux nombres.")
    if len(value) != 2:
        raise ValidationError("figure_size doit contenir exactement deux nombres.")
    try:
        width = float(value[0])
        height = float(value[1])
    except (TypeError, ValueError) as exc:
        raise ValidationError("figure_size doit contenir exactement deux nombres.") from exc
    if width <= 0.0 or height <= 0.0:
        raise ValidationError("figure_size doit contenir des valeurs > 0.")
    return (width, height)


def _normalize_color_field(value: object) -> str:
    text = _coerce_required_text(value, label="color_field").lower()
    if text not in ALLOWED_COLOR_FIELDS:
        values = ", ".join(sorted(ALLOWED_COLOR_FIELDS))
        raise ValidationError(f"color_field doit etre parmi : {values}.")
    return text


def _normalize_topography_field(value: object) -> str:
    text = _coerce_required_text(value, label="topography_field").lower()
    if text not in ALLOWED_TOPOGRAPHY_FIELDS:
        values = ", ".join(sorted(ALLOWED_TOPOGRAPHY_FIELDS))
        raise ValidationError(f"topography_field doit etre parmi : {values}.")
    return text


@dataclass(frozen=True)
class PlotTomlSchema:
    """Schema valide du bloc `[mesh_distribution.plot]`."""

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

    @classmethod
    def from_mapping(cls, raw_value: object | None) -> PlotTomlSchema:
        raw_plot = {} if raw_value is None else _require_mapping(raw_value, label=_PLOT_LABEL)
        _forbid_unknown_keys(raw_plot, allowed_keys=_PLOT_ALLOWED_KEYS, label=_PLOT_LABEL)
        return cls(
            color_field=_normalize_color_field(raw_plot.get("color_field", "geology_key")),
            color_map=_coerce_required_text(
                raw_plot.get("color_map", "viridis"),
                label="color_map",
            ),
            figure_size=_coerce_figure_size(raw_plot.get("figure_size", (11.0, 9.0))),
            dpi=_coerce_positive_int(raw_plot.get("dpi", 160), label="dpi"),
            title=_coerce_optional_text(raw_plot.get("title")),
            show_topography_panel=_coerce_bool(
                raw_plot.get("show_topography_panel", True),
                label="show_topography_panel",
            ),
            topography_field=_normalize_topography_field(
                raw_plot.get("topography_field", "z_top_mean")
            ),
            topography_cmap=_coerce_required_text(
                raw_plot.get("topography_cmap", "terrain"),
                label="topography_cmap",
            ),
            topography_title=_coerce_optional_text(raw_plot.get("topography_title")),
            show_mesh_edges=_coerce_bool(
                raw_plot.get("show_mesh_edges", True),
                label="show_mesh_edges",
            ),
            mesh_edge_color=_coerce_required_text(
                raw_plot.get("mesh_edge_color", "0.35"),
                label="mesh_edge_color",
            ),
            mesh_edge_linewidth=_coerce_non_negative_float(
                raw_plot.get("mesh_edge_linewidth", 0.55),
                label="mesh_edge_linewidth",
            ),
            show_boundaries=_coerce_bool(
                raw_plot.get("show_boundaries", True),
                label="show_boundaries",
            ),
            show_geology_interfaces=_coerce_bool(
                raw_plot.get("show_geology_interfaces", True),
                label="show_geology_interfaces",
            ),
            show_river_edges=_coerce_bool(
                raw_plot.get("show_river_edges", True),
                label="show_river_edges",
            ),
            annotate_cell_ids=_coerce_bool(
                raw_plot.get("annotate_cell_ids", False),
                label="annotate_cell_ids",
            ),
        )

    def to_plot_config(self) -> PlotConfig:
        """Construit la configuration d'affichage runtime a partir du TOML valide."""
        return PlotConfig(**asdict(self))


@dataclass(frozen=True)
class MeshDistributionTomlSchema:
    """Schema valide du bloc `[mesh_distribution]`."""

    bundle_dir: Path
    figure_output_path: Path | None = None
    summary_output_path: Path | None = None
    show_window: bool = False
    plot: PlotTomlSchema = field(default_factory=PlotTomlSchema)

    @classmethod
    def from_mapping(cls, raw_value: object) -> MeshDistributionTomlSchema:
        raw_main = _require_mapping(raw_value, label=_MAIN_LABEL)
        _forbid_unknown_keys(raw_main, allowed_keys=_MAIN_ALLOWED_KEYS, label=_MAIN_LABEL)
        return cls(
            bundle_dir=_coerce_path(raw_main.get("bundle_dir"), label="bundle_dir"),
            figure_output_path=_coerce_optional_path(raw_main.get("figure_output_path")),
            summary_output_path=_coerce_optional_path(raw_main.get("summary_output_path")),
            show_window=_coerce_bool(raw_main.get("show_window", False), label="show_window"),
            plot=PlotTomlSchema.from_mapping(raw_main.get("plot")),
        )


def get_toml_parameter_descriptions() -> dict[str, str]:
    """Retourne les descriptions humaines associees aux cles TOML publiques."""
    return dict(_TOML_PARAMETER_DESCRIPTIONS)


__all__ = [
    "MeshDistributionTomlSchema",
    "PlotTomlSchema",
    "ValidationError",
    "get_toml_parameter_descriptions",
]
