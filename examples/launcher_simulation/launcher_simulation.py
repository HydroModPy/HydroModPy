# -*- coding: utf-8 -*-
"""Example 12 — launcher entry-point.

Runs the full example12 study via the generic HydroModPyLauncher.
Study-specific preprocessing logic (recharge, NO3 runtime arrays) lives in
hooks.py; launcher-managed postprocess is configured in config.toml via
`[postprocess]` and `[display]`.

Usage::

    python -m examples.example12launcher.example12launcher
    # or
    python -m launchers run examples/example12launcher/config.toml
"""

from pathlib import Path
import sys

# When this file is executed directly by path, Python adds the script folder to
# ``sys.path`` but not necessarily the repository root.  Insert the repo root
# explicitly so the local ``launchers`` package can always be imported.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from launchers import HydroModPyLauncher


def main() -> None:
    """Run the example12 launcher with its colocated TOML configuration."""

    HydroModPyLauncher(Path(__file__).parent / "config.toml").run()


if __name__ == "__main__":
    main()
