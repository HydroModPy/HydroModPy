"""Script de lancement direct du package autonome `mesh`.

Ce script permet de charger un bundle exporte, produire une figure de synthese
et ecrire un resume JSON sans dependre d'une arborescence HydroModPy plus large.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

# Ajoute le dossier parent de `mesh/` au `sys.path` afin de permettre
# `python mesh/run_visualization.py` sans installation prealable.
_repo_root = Path(__file__).resolve().parent.parent
if str(_repo_root) not in sys.path:
    sys.path.insert(0, str(_repo_root))

from mesh.workflow import (  # noqa: E402
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



