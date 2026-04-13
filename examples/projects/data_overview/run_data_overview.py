"""Thin wrapper around the canonical ``data-overview`` launcher entry point.

Preferred invocation:

``python -m launchers data-overview run examples/projects/data_overview/project.toml``
"""

from __future__ import annotations

from pathlib import Path
import sys


def _ensure_repo_root_on_sys_path() -> None:
    """Allow direct execution of this example wrapper by file path."""
    repo_root = Path(__file__).resolve().parents[3]
    repo_root_str = str(repo_root)
    if repo_root_str not in sys.path:
        sys.path.insert(0, repo_root_str)


def main() -> int:
    """Delegate to the canonical launcher CLI using the local example config."""
    _ensure_repo_root_on_sys_path()

    from launchers.__main__ import main as launchers_main

    config_path = Path(__file__).with_name("project.toml").resolve()
    return int(
        launchers_main(
            ["data-overview", "run", str(config_path)]
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
