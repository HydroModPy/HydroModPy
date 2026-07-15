"""Path-resolution helpers for the zone-conformal meshing orchestration."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _resolve_config_path(raw_config: str | Path, *, script_dir: Path | None = None) -> Path:
    candidate = Path(raw_config).expanduser()
    if candidate.is_absolute() and candidate.exists():
        return candidate.resolve()
    cwd_candidate = candidate.resolve()
    if cwd_candidate.exists():
        return cwd_candidate
    if script_dir is not None:
        script_candidate = (script_dir / candidate).resolve()
        if script_candidate.exists():
            return script_candidate
    raise FileNotFoundError(f"Config TOML not found: '{raw_config}'")


def _resolve_optional_output_path(
    config_toml: Path,
    config_value: Any,
    override_value: str | None,
) -> Path | None:
    raw = override_value if override_value is not None else config_value
    if raw is None:
        return None
    text = str(raw).strip()
    if text == "":
        return None
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = (config_toml.parent / path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


__all__ = [
    "_resolve_config_path",
    "_resolve_optional_output_path",
]
