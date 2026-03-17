"""Orchestration complete de la distribution de maillage.

Ce module assemble les briques de lecture et de visualisation pour :
- construire un resume JSON simple ;
- ecrire la figure de sortie ;
- proposer une API de haut niveau pour un lancement depuis TOML.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
import json
from pathlib import Path
from typing import Any

from hydromodpy_annex.distribution.mesh.lecture import (
    ConfigurationTrace,
    ConfigurationVisualisation,
    DonneesVisualisationMaillage,
    FICHIER_CONFIG_DEFAUT,
    SECTION_TOML_DEFAUT,
    charger_configuration_toml,
    charger_donnees_visualisation,
    charger_donnees_visualisation_depuis_toml,
)
from hydromodpy_annex.distribution.mesh.visualisation import (
    a_topographie_noeuds_continue,
    construire_figure_visualisation,
)


def construire_resume_visualisation(
    donnees: DonneesVisualisationMaillage,
) -> dict[str, Any]:
    """Construit un resume compact et facilement partageable."""
    maillage = donnees.maillage
    configuration = donnees.configuration
    metadata = dict(maillage.metadata)
    cles_geologie = sorted(
        {
            str(cellule.geology_key)
            for cellule in maillage.cells
            if str(cellule.geology_key).strip() != ""
        }
    )

    return {
        "version_schema_resume": "distribution_maillage_v1",
        "dossier_bundle": str(maillage.bundle_dir),
        "fichier_maillage": str(maillage.mesh_path),
        "nombre_noeuds": int(maillage.n_nodes),
        "nombre_cellules": int(maillage.n_cells),
        "nombre_aretes": int(maillage.n_edges),
        "crs": metadata.get("crs"),
        "mode_contraintes": metadata.get("constraints_mode"),
        "geologie_disponible": bool(metadata.get("geology", {}).get("available", False)),
        "cles_geologie": cles_geologie,
        "nombre_aretes_riviere": int(sum(1 for arete in maillage.edges if bool(arete.is_river))),
        "nombre_aretes_limite": int(
            sum(1 for arete in maillage.edges if str(arete.edge_kind) == "boundary")
        ),
        "nombre_aretes_interface_geologie": int(
            sum(
                1
                for arete in maillage.edges
                if str(arete.edge_kind) == "geology_interface"
            )
        ),
        "champ_couleur": str(configuration.trace.champ_couleur),
        "afficher_panneau_topographie": bool(configuration.trace.afficher_panneau_topographie),
        "champ_topographie": str(configuration.trace.champ_topographie),
        "mode_rendu_topographie": (
            "continu_sur_noeuds"
            if a_topographie_noeuds_continue(maillage)
            else "repli_par_cellules"
        ),
        "sortie_figure": (
            None if configuration.sortie_figure is None else str(configuration.sortie_figure)
        ),
        "sortie_resume_json": (
            None
            if configuration.sortie_resume_json is None
            else str(configuration.sortie_resume_json)
        ),
    }


def _ecrire_json(chemin: Path, contenu: Mapping[str, Any]) -> None:
    """Ecrit un JSON lisible et stable."""
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(
        json.dumps(dict(contenu), indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )


def executer_visualisation(
    configuration: ConfigurationVisualisation,
) -> dict[str, Any]:
    """Execute la lecture, le rendu et l'ecriture des sorties."""
    donnees = charger_donnees_visualisation(configuration)
    resume = construire_resume_visualisation(donnees)
    figure = construire_figure_visualisation(
        donnees.maillage,
        configuration=donnees.configuration,
    )

    # On ecrit les sorties seulement si elles ont ete demandees.
    if donnees.configuration.sortie_figure is not None:
        donnees.configuration.sortie_figure.parent.mkdir(parents=True, exist_ok=True)
        figure.savefig(donnees.configuration.sortie_figure)

    if donnees.configuration.sortie_resume_json is not None:
        _ecrire_json(donnees.configuration.sortie_resume_json, resume)

    from matplotlib import pyplot as plt

    if donnees.configuration.afficher_fenetre:
        plt.show()
    else:
        plt.close(figure)
    return resume


def executer_visualisation_depuis_toml(
    chemin_toml: str | Path,
    *,
    section: str = SECTION_TOML_DEFAUT,
    sortie_json_forcee: str | Path | None = None,
) -> dict[str, Any]:
    """Point d'entree de haut niveau pour lancer l'outil depuis un TOML."""
    configuration = charger_configuration_toml(chemin_toml, section=section)

    # On permet a la ligne de commande de surcharger le chemin de resume JSON.
    if sortie_json_forcee is not None:
        configuration = replace(
            configuration,
            sortie_resume_json=Path(sortie_json_forcee).resolve(),
        )

    return executer_visualisation(configuration)


__all__ = [
    "ConfigurationTrace",
    "ConfigurationVisualisation",
    "DonneesVisualisationMaillage",
    "FICHIER_CONFIG_DEFAUT",
    "SECTION_TOML_DEFAUT",
    "charger_configuration_toml",
    "charger_donnees_visualisation",
    "charger_donnees_visualisation_depuis_toml",
    "construire_resume_visualisation",
    "executer_visualisation",
    "executer_visualisation_depuis_toml",
]
