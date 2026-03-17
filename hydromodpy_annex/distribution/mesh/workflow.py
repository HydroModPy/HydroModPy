"""Orchestration complete de la distribution de maillage.

Ce module joue le role de colle entre les autres briques du sous-package.
Il ne fait ni lecture "bas niveau" des fichiers, ni dessin detaille.

Son role est de piloter une execution complete :

1. charger la configuration ;
2. relire le bundle ;
3. construire la figure ;
4. produire un resume JSON stable ;
5. ecrire les sorties demandees.

L'idee est de proposer une API simple pour des usages scripts, notebooks ou
ligne de commande, sans obliger l'utilisateur a enchainer lui-meme toutes
les etapes.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
import json
from pathlib import Path
from typing import Any

from hydromodpy_annex.distribution.mesh.bundle_loading import (
    load_visualization_data,
    load_visualization_data_from_toml,
)
from hydromodpy_annex.distribution.mesh.config import (
    load_toml_config,
)
from hydromodpy_annex.distribution.mesh.models import (
    DEFAULT_CONFIG_FILENAME,
    DEFAULT_TOML_SECTION,
    MeshVisualizationData,
    PlotConfig,
    VisualizationConfig,
)
from hydromodpy_annex.distribution.mesh.summary import (
    build_visualization_summary,
)
from hydromodpy_annex.distribution.mesh.visualization import (
    build_visualization_figure,
)


def _write_json_file(path: Path, content: Mapping[str, Any]) -> None:
    """Ecrit un JSON lisible et stable."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(dict(content), indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )


def run_visualization(
    config: VisualizationConfig,
) -> dict[str, Any]:
    """Execute la lecture, le rendu et l'ecriture des sorties.

    Cette fonction est le point d'entree Python le plus direct lorsque la
    configuration a deja ete construite en memoire.
    """

    data = load_visualization_data(config)
    summary = build_visualization_summary(data)
    figure = build_visualization_figure(
        data.mesh,
        config=data.config,
    )

    # On ecrit les sorties seulement si elles ont ete demandees.
    if data.config.figure_output_path is not None:
        data.config.figure_output_path.parent.mkdir(parents=True, exist_ok=True)
        figure.savefig(data.config.figure_output_path)

    if data.config.summary_output_path is not None:
        _write_json_file(data.config.summary_output_path, summary)

    from matplotlib import pyplot as plt

    if data.config.show_window:
        plt.show()
    else:
        plt.close(figure)
    return summary


def run_visualization_from_toml(
    toml_path: str | Path,
    *,
    section: str = DEFAULT_TOML_SECTION,
    forced_summary_output_path: str | Path | None = None,
) -> dict[str, Any]:
    """Point d'entree de haut niveau pour lancer l'outil depuis un TOML.

    C'est la fonction la plus pratique pour un usage "distribution" :
    un seul chemin TOML suffit pour relire le bundle et produire les sorties.
    """

    config = load_toml_config(toml_path, section=section)

    # On permet a la ligne de commande de surcharger le chemin de resume JSON.
    if forced_summary_output_path is not None:
        config = replace(
            config,
            summary_output_path=Path(forced_summary_output_path).resolve(),
        )

    return run_visualization(config)


__all__ = [
    "DEFAULT_CONFIG_FILENAME",
    "DEFAULT_TOML_SECTION",
    "MeshVisualizationData",
    "PlotConfig",
    "VisualizationConfig",
    "build_visualization_summary",
    "load_toml_config",
    "load_visualization_data",
    "load_visualization_data_from_toml",
    "run_visualization",
    "run_visualization_from_toml",
]
