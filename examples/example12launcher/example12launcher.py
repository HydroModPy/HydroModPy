# -*- coding: utf-8 -*-
"""Example 12 — launcher entry-point.

Runs the full example12 study via the generic HydroModPyLauncher.
Study-specific logic (recharge, NO3, plots) lives in hooks.py alongside
this file; everything else is driven by config.toml.

Usage::

    python -m examples.example12launcher.example12launcher
    # or
    python -m launchers run examples/example12launcher/config.toml
"""

from pathlib import Path

from launchers import HydroModPyLauncher


def main() -> None:
    """Run the example12 launcher with its colocated TOML configuration."""

    HydroModPyLauncher(Path(__file__).parent / "config.toml").run()


if __name__ == "__main__":
    main()
