# -*- coding: utf-8 -*-
"""Example 12 — launcher entry-point.

Runs the full example12 study via the generic HydroModPyLauncher.
Study-specific logic (recharge, NO3, plots) lives in hooks.py alongside
this file; everything else is driven by config.toml.

Usage::

    python example12launcher.py
    # or
    python -m launcher run examples/example12launcher/config.toml
"""

import sys
from pathlib import Path

# Ensure the repo root (where the `launcher` package lives) is on sys.path.
# Not needed once `pip install -e .` has been re-run after adding launcher to pyproject.toml.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from launcher import HydroModPyLauncher

# Path(__file__).parent resolves to the directory containing this script,
# so config.toml is always located relative to example12launcher.py
# regardless of the working directory from which the script is launched.
HydroModPyLauncher(Path(__file__).parent / "config.toml").run()
