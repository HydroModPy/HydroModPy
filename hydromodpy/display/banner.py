"""HydroModPy ASCII banner."""

from __future__ import annotations

import sys

_banner_printed = False


def print_hydromodpy() -> None:
    """Print the HydroModPy ASCII banner once."""
    global _banner_printed
    if _banner_printed:
        return
    banner_lines = [
        r"      __  __          __           __  ____          ________     ",
        r"     / / / /         / /          /  \/   /         / / __  /     ",
        r"    / /_/ /_  ______/ /________  /       /___  ____/ / /_/ /_  __ ",
        r"   / __  / / / / __  / ___/ __ \/ /\,-/ / __ \/ __  / ____/ / / / ",
        r"  / / / / /_/ / /_/ / /  / /_/ / /   / / /_/ / /_/ / /   / /_/ /  ",
        r" /_/ /_/\__, /_____/_/   \____/_/   /_/\____/_____/_/____\__, /   ",
        r"       /____/ Hydrological Modelling in Python /_____________/    ",
        r"                                                                  ",
    ]
    print("\n".join(banner_lines), file=sys.stderr)
    _banner_printed = True


__all__ = ["print_hydromodpy"]
