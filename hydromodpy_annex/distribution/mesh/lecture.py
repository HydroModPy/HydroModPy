"""Lecture des donnees necessaires a la distribution d'un maillage.

Ce module regroupe toute la partie lecture :
- chargement de la configuration TOML ;
- chargement du bundle de maillage exporte ;
- assemblage dans une classe unique, facile a passer au reste du pipeline.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
import tomllib
from typing import Any

from hydromodpy.solver.utils.mesh.gmsh_grid.catchment_mesh_bundle_reader import (
    CatchmentMeshBundle,
    load_catchment_mesh_bundle,
)

FICHIER_CONFIG_DEFAUT = "config_exemple.toml"
SECTION_TOML_DEFAUT = "distribution_maillage"

# Les champs ci-dessous sont ceux qui existent deja dans le bundle exporte.
CHAMPS_NUMERIQUES_COULEUR = {
    "area_m2",
    "z_top_centroid",
    "z_top_mean",
}
CHAMPS_CATEGORIELS_COULEUR = {
    "geology_code",
    "geology_key",
}
CHAMPS_AUTORISES_COULEUR = CHAMPS_NUMERIQUES_COULEUR | CHAMPS_CATEGORIELS_COULEUR
CHAMPS_AUTORISES_TOPOGRAPHIE = {
    "z_top_centroid",
    "z_top_mean",
}


@dataclass(frozen=True)
class ConfigurationTrace:
    """Parametres de tracé des figures de distribution."""

    champ_couleur: str = "geology_key"
    palette_couleur: str = "viridis"
    taille_figure: tuple[float, float] = (11.0, 9.0)
    dpi: int = 160
    titre: str | None = None
    afficher_panneau_topographie: bool = True
    champ_topographie: str = "z_top_mean"
    palette_topographie: str = "terrain"
    titre_topographie: str | None = None
    afficher_aretes_maillage: bool = True
    couleur_aretes_maillage: str = "0.35"
    epaisseur_aretes_maillage: float = 0.55
    afficher_limites: bool = True
    afficher_interfaces_geologie: bool = True
    afficher_aretes_riviere: bool = True
    annoter_identifiants_cellules: bool = False


@dataclass(frozen=True)
class ConfigurationVisualisation:
    """Configuration complete d'une execution de distribution."""

    dossier_bundle: Path
    sortie_figure: Path | None = None
    sortie_resume_json: Path | None = None
    afficher_fenetre: bool = False
    trace: ConfigurationTrace = ConfigurationTrace()


@dataclass(frozen=True)
class DonneesVisualisationMaillage:
    """Objet final de lecture, pret a etre trace ou exporte."""

    maillage: CatchmentMeshBundle
    configuration: ConfigurationVisualisation


def _exiger_mapping(valeur_brute: object, *, etiquette: str) -> Mapping[str, Any]:
    """Verifie qu'un bloc TOML est bien une table cle -> valeur."""
    if not isinstance(valeur_brute, Mapping):
        raise ValueError(f"{etiquette} doit etre une table TOML.")
    return valeur_brute


def _texte_optionnel(valeur_brute: object | None) -> str | None:
    """Normalise une chaine optionnelle en supprimant les blancs inutiles."""
    if valeur_brute is None:
        return None
    texte = str(valeur_brute).strip()
    return None if texte == "" else texte


def _booleen(valeur_brute: object, *, etiquette: str) -> bool:
    """Valide un booleen explicite dans la configuration."""
    if isinstance(valeur_brute, bool):
        return valeur_brute
    raise ValueError(f"{etiquette} doit etre un booleen.")


def _entier_positif(valeur_brute: object, *, etiquette: str) -> int:
    """Valide un entier strictement positif."""
    try:
        valeur = int(valeur_brute)
    except Exception as exc:
        raise ValueError(f"{etiquette} doit etre un entier.") from exc
    if valeur <= 0:
        raise ValueError(f"{etiquette} doit etre > 0.")
    return valeur


def _flottant_non_negatif(valeur_brute: object, *, etiquette: str) -> float:
    """Valide un reel positif ou nul."""
    try:
        valeur = float(valeur_brute)
    except Exception as exc:
        raise ValueError(f"{etiquette} doit etre un nombre.") from exc
    if valeur < 0.0:
        raise ValueError(f"{etiquette} doit etre >= 0.")
    return valeur


def _taille_figure(valeur_brute: object, *, etiquette: str) -> tuple[float, float]:
    """Valide le format [largeur, hauteur] attendu dans le TOML."""
    if not isinstance(valeur_brute, (list, tuple)) or len(valeur_brute) != 2:
        raise ValueError(f"{etiquette} doit etre un tableau [largeur, hauteur].")
    try:
        largeur = float(valeur_brute[0])
        hauteur = float(valeur_brute[1])
    except Exception as exc:
        raise ValueError(f"{etiquette} doit contenir deux nombres.") from exc
    if largeur <= 0.0 or hauteur <= 0.0:
        raise ValueError(f"{etiquette} doit contenir des valeurs > 0.")
    return (largeur, hauteur)


def _resoudre_chemin(
    *,
    chemin_config: Path,
    valeur_brute: object | None,
    obligatoire: bool,
    etiquette: str,
) -> Path | None:
    """Resout un chemin relatif depuis le dossier du fichier TOML."""
    texte = _texte_optionnel(valeur_brute)
    if texte is None:
        if obligatoire:
            raise ValueError(f"{etiquette} est obligatoire.")
        return None
    chemin = Path(texte).expanduser()
    if not chemin.is_absolute():
        chemin = (chemin_config.parent / chemin).resolve()
    return chemin


def charger_configuration_toml(
    chemin_toml: str | Path,
    *,
    section: str = SECTION_TOML_DEFAUT,
) -> ConfigurationVisualisation:
    """Charge la configuration TOML du module de distribution."""
    chemin_config = Path(chemin_toml).resolve()
    contenu = tomllib.loads(chemin_config.read_text(encoding="utf-8-sig"))
    bloc_principal = _exiger_mapping(contenu.get(section), etiquette=f"[{section}]")

    # On lit le sous-bloc de tracé séparément pour bien distinguer
    # configuration de lecture et configuration d'affichage.
    bloc_trace = bloc_principal.get("trace", {})
    if bloc_trace is None:
        bloc_trace = {}
    bloc_trace = _exiger_mapping(bloc_trace, etiquette=f"[{section}.trace]")

    champ_couleur = str(bloc_trace.get("champ_couleur", "geology_key")).strip().lower()
    if champ_couleur not in CHAMPS_AUTORISES_COULEUR:
        valeurs = ", ".join(sorted(CHAMPS_AUTORISES_COULEUR))
        raise ValueError(f"[{section}.trace].champ_couleur doit etre parmi : {valeurs}.")

    champ_topographie = (
        str(bloc_trace.get("champ_topographie", "z_top_mean")).strip().lower()
    )
    if champ_topographie not in CHAMPS_AUTORISES_TOPOGRAPHIE:
        valeurs = ", ".join(sorted(CHAMPS_AUTORISES_TOPOGRAPHIE))
        raise ValueError(
            f"[{section}.trace].champ_topographie doit etre parmi : {valeurs}."
        )

    configuration_trace = ConfigurationTrace(
        champ_couleur=champ_couleur,
        palette_couleur=str(bloc_trace.get("palette_couleur", "viridis")).strip() or "viridis",
        taille_figure=_taille_figure(
            bloc_trace.get("taille_figure", [11.0, 9.0]),
            etiquette=f"[{section}.trace].taille_figure",
        ),
        dpi=_entier_positif(
            bloc_trace.get("dpi", 160),
            etiquette=f"[{section}.trace].dpi",
        ),
        titre=_texte_optionnel(bloc_trace.get("titre")),
        afficher_panneau_topographie=_booleen(
            bloc_trace.get("afficher_panneau_topographie", True),
            etiquette=f"[{section}.trace].afficher_panneau_topographie",
        ),
        champ_topographie=champ_topographie,
        palette_topographie=(
            str(bloc_trace.get("palette_topographie", "terrain")).strip() or "terrain"
        ),
        titre_topographie=_texte_optionnel(bloc_trace.get("titre_topographie")),
        afficher_aretes_maillage=_booleen(
            bloc_trace.get("afficher_aretes_maillage", True),
            etiquette=f"[{section}.trace].afficher_aretes_maillage",
        ),
        couleur_aretes_maillage=(
            str(bloc_trace.get("couleur_aretes_maillage", "0.35")).strip() or "0.35"
        ),
        epaisseur_aretes_maillage=_flottant_non_negatif(
            bloc_trace.get("epaisseur_aretes_maillage", 0.55),
            etiquette=f"[{section}.trace].epaisseur_aretes_maillage",
        ),
        afficher_limites=_booleen(
            bloc_trace.get("afficher_limites", True),
            etiquette=f"[{section}.trace].afficher_limites",
        ),
        afficher_interfaces_geologie=_booleen(
            bloc_trace.get("afficher_interfaces_geologie", True),
            etiquette=f"[{section}.trace].afficher_interfaces_geologie",
        ),
        afficher_aretes_riviere=_booleen(
            bloc_trace.get("afficher_aretes_riviere", True),
            etiquette=f"[{section}.trace].afficher_aretes_riviere",
        ),
        annoter_identifiants_cellules=_booleen(
            bloc_trace.get("annoter_identifiants_cellules", False),
            etiquette=f"[{section}.trace].annoter_identifiants_cellules",
        ),
    )

    return ConfigurationVisualisation(
        dossier_bundle=_resoudre_chemin(
            chemin_config=chemin_config,
            valeur_brute=bloc_principal.get("dossier_bundle"),
            obligatoire=True,
            etiquette=f"[{section}].dossier_bundle",
        ),
        sortie_figure=_resoudre_chemin(
            chemin_config=chemin_config,
            valeur_brute=bloc_principal.get("sortie_figure"),
            obligatoire=False,
            etiquette=f"[{section}].sortie_figure",
        ),
        sortie_resume_json=_resoudre_chemin(
            chemin_config=chemin_config,
            valeur_brute=bloc_principal.get("sortie_resume_json"),
            obligatoire=False,
            etiquette=f"[{section}].sortie_resume_json",
        ),
        afficher_fenetre=_booleen(
            bloc_principal.get("afficher_fenetre", False),
            etiquette=f"[{section}].afficher_fenetre",
        ),
        trace=configuration_trace,
    )


def charger_donnees_visualisation(
    configuration: ConfigurationVisualisation,
) -> DonneesVisualisationMaillage:
    """Charge le bundle et retourne l'objet de travail unique du module."""
    maillage = load_catchment_mesh_bundle(configuration.dossier_bundle)
    return DonneesVisualisationMaillage(
        maillage=maillage,
        configuration=configuration,
    )


def charger_donnees_visualisation_depuis_toml(
    chemin_toml: str | Path,
    *,
    section: str = SECTION_TOML_DEFAUT,
) -> DonneesVisualisationMaillage:
    """Enchaine lecture du TOML puis lecture du bundle."""
    configuration = charger_configuration_toml(chemin_toml, section=section)
    return charger_donnees_visualisation(configuration)


__all__ = [
    "CHAMPS_AUTORISES_COULEUR",
    "CHAMPS_AUTORISES_TOPOGRAPHIE",
    "CHAMPS_CATEGORIELS_COULEUR",
    "CHAMPS_NUMERIQUES_COULEUR",
    "ConfigurationTrace",
    "ConfigurationVisualisation",
    "DonneesVisualisationMaillage",
    "FICHIER_CONFIG_DEFAUT",
    "SECTION_TOML_DEFAUT",
    "charger_configuration_toml",
    "charger_donnees_visualisation",
    "charger_donnees_visualisation_depuis_toml",
]
