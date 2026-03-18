"""Script de lancement direct pour la distribution visuelle des maillages.

Ce fichier sert de point d'entree le plus simple possible pour un utilisateur
qui souhaite :

- pointer un bundle deja exporte ;
- lancer une figure de synthese ;
- recuperer un petit resume JSON.

Le script est concu pour fonctionner dans deux contextes :

1. depuis le depot HydroModPy ;
2. depuis un paquet distribue contenant seulement `hydromodpy_annex`.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

# On ajoute au besoin la racine contenant `hydromodpy_annex` ou `hydromodpy`
# pour permettre une execution directe du script par chemin absolu, sans
# installation prealable du projet complet.
current_path = Path(__file__).resolve()
for parent_path in current_path.parents:
    if (parent_path / "hydromodpy_annex").exists() or (parent_path / "hydromodpy").exists():
        if str(parent_path) not in sys.path:
            sys.path.insert(0, str(parent_path))
        break

from hydromodpy_annex.distribution.mesh.workflow import (  # noqa: E402
    DEFAULT_CONFIG_FILENAME,
    DEFAULT_TOML_SECTION,
    run_visualization_from_toml,
)


def _build_parser() -> argparse.ArgumentParser:
    """Construit l'interface ligne de commande du module."""
    default_config_path = Path(__file__).resolve().parent / "examples" / DEFAULT_CONFIG_FILENAME
    parser = argparse.ArgumentParser(
        description=(
            "Charge un bundle de maillage exporte, produit une ou plusieurs "
            "figures pedagogiques et ecrit un resume JSON si demande."
        )
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=default_config_path,
        help="Chemin du fichier TOML de configuration.",
    )
    parser.add_argument(
        "--section",
        type=str,
        default=DEFAULT_TOML_SECTION,
        help=f"Section TOML a charger (defaut : {DEFAULT_TOML_SECTION}).",
    )
    parser.add_argument(
        "--output-json",
        dest="output_json",
        type=Path,
        default=None,
        help="Chemin optionnel pour forcer la sortie du resume JSON.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Execute la visualisation depuis la ligne de commande."""
    args = _build_parser().parse_args(argv)
    summary = run_visualization_from_toml(
        args.config,
        section=args.section,
        forced_summary_output_path=args.output_json,
    )
    print(json.dumps(summary, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
