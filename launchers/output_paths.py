"""Shared runtime policy for launcher output roots."""

from __future__ import annotations

import os
from pathlib import Path


DEFAULT_USER_OUTPUT_ROOT = Path.home() / "HydroModPy_outputs"
_REPO_ROOT = Path(__file__).resolve().parents[1]


def _path_is_within(path: Path, root: Path) -> bool:
    """Return True when ``path`` is located under ``root``."""
    return path.resolve().is_relative_to(root.resolve())


def resolve_launcher_output_root(
    configured_out_dir: str | Path,
    *,
    env_var_name: str = "HYDROMODPY_OUT_PATH",
    repo_root: str | Path | None = None,
    fallback_root: str | Path | None = None,
) -> tuple[Path, str]:
    """Resolve the effective launcher output root.

    Resolution order:
    1. explicit environment override,
    2. configured path when it is already outside the repository,
    3. user-local fallback when the configured path points inside the repo.
    """
    env_override = os.environ.get(env_var_name)
    if env_override:
        return Path(env_override).expanduser().resolve(), "env_override"

    configured = Path(configured_out_dir).expanduser().resolve()
    effective_repo_root = Path(repo_root or _REPO_ROOT).expanduser().resolve()
    effective_fallback_root = Path(
        fallback_root or DEFAULT_USER_OUTPUT_ROOT
    ).expanduser().resolve()

    if _path_is_within(configured, effective_repo_root):
        return effective_fallback_root, "repo_redirect"
    return configured, "configured"


def build_repo_output_redirect_notice(
    *,
    entrypoint_name: str,
    resolved_out_dir: str | Path,
    env_var_name: str = "HYDROMODPY_OUT_PATH",
) -> str:
    """Build the user-facing notice for repo-local output redirection."""
    resolved = Path(resolved_out_dir).expanduser().resolve()
    return (
        f"[{entrypoint_name}] workspace.out_dir_path points inside the repository; "
        f"redirecting outputs to {resolved}. Set {env_var_name} to override."
    )
