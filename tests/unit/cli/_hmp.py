"""One way to call ``hydromodpy.cli.main.main`` and read its exit code."""

from __future__ import annotations

import importlib
import sys


def run_main(monkeypatch, argv: list[str]) -> int:
    """Run the CLI with *argv* (program name first) and return its exit code."""
    module = importlib.import_module("hydromodpy.cli.main")
    monkeypatch.setattr(sys, "argv", argv)
    try:
        module.main()
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


def run_hmp(monkeypatch, *argv: str) -> int:
    """Same as :func:`run_main`, for arguments given without the program name."""
    return run_main(monkeypatch, ["hmp", *argv])
