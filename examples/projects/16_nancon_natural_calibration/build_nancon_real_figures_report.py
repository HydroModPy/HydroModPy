"""Build the Nancon reference catchment report."""

# ruff: noqa: E402, I001

from __future__ import annotations

import sys

from nancon_real_figures_report import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
