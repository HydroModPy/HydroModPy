"""Exemple 04 — data_overview.

Génère une carte d'identité du bassin (pas de simulation, juste
le chargement et la visualisation des données d'entrée).

Usage
-----
    python examples/04_data_overview/run_data_overview.py

Équivalent CLI :
    hmp run examples/04_data_overview/project.toml
"""

from __future__ import annotations

from pathlib import Path

import hydromodpy as hmp


def main() -> int:
    config = Path(__file__).with_name("project.toml").resolve()
    hmp.run(config, headless=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
