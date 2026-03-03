"""CLI entry-point for the HydroModPy launcher.

Usage::

    python -m launchers run path/to/config.toml
"""

import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) == 3 and sys.argv[1] == "run":
        from launchers import HydroModPyLauncher
        HydroModPyLauncher(Path(sys.argv[2])).run()
    else:
        print("Usage: python -m launchers run <path/to/config.toml>")
        sys.exit(1)


if __name__ == "__main__":
    main()
