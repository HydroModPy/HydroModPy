"""Exemple 01 — boucle de calibration Optuna.

Usage
-----
    python examples/01_calibration/run.py

Équivalent CLI :
    hmp calibrate examples/01_calibration/project.toml
"""

from __future__ import annotations

from pathlib import Path

import hydromodpy as hmp


def main() -> None:
    config = Path(__file__).resolve().parent / "project.toml"
    session = hmp.calibrate(config)
    print(f"[OK] calibration session={session}")


if __name__ == "__main__":
    main()
