"""Exemple 00 — getting_started.

Lance l'aquifère Dupuit synthétique en régime permanent via l'API Python.

Usage
-----
    python examples/00_getting_started/run.py

Équivalent CLI :
    hmp run examples/00_getting_started/project.toml
"""

from __future__ import annotations

from pathlib import Path

import hydromodpy as hmp


def main() -> None:
    config = Path(__file__).resolve().parent / "project.toml"
    result = hmp.run(config, headless=True)
    print(f"[OK] sim_id={result.sim_id} name={result.name}")


if __name__ == "__main__":
    main()
