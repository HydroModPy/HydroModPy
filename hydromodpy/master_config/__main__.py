"""Entry point for ``python -m hydromodpy.master_config``."""

from __future__ import annotations

import sys


def main() -> None:
    sys.argv = [sys.argv[0], "config", *sys.argv[1:]]
    from hydromodpy.__main__ import main as _main

    _main()


if __name__ == "__main__":
    main()
