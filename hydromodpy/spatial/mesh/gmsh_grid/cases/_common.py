"""Shared helpers for runnable ``gmsh_grid.cases`` scripts.

The goal of this module is to keep case runners focused on the didactic
workflow while centralizing the repetitive plumbing used by many cases:

- robust config-path resolution
- TOML section loading
- optional output-path resolution
- stable JSON sidecar writing
"""

from __future__ import annotations

import json
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from hydromodpy.core.toml_io.paths import get_nested_section


def resolve_case_config_path(raw_config: str | Path, *, script_dir: str | Path) -> Path:
    """Resolve one case TOML path for both module and direct-script execution."""

    candidate = Path(raw_config).expanduser()
    if candidate.is_absolute() and candidate.exists():
        return candidate.resolve()

    cwd_candidate = candidate.resolve()
    if cwd_candidate.exists():
        return cwd_candidate

    script_candidate = (Path(script_dir).resolve() / candidate).resolve()
    if script_candidate.exists():
        return script_candidate

    raise FileNotFoundError(
        f"Config TOML not found: '{raw_config}'. Tried '{cwd_candidate}' and '{script_candidate}'."
    )


def load_case_section(
    config_toml: str | Path,
    *,
    section: str = "case",
) -> dict[str, Any]:
    """Load one TOML section used by a runnable reference case."""

    payload = tomllib.loads(Path(config_toml).read_text(encoding="utf-8-sig"))
    return dict(get_nested_section(payload, section))


def optional_case_output_path(
    config_toml: str | Path,
    *,
    config_value: Any,
    override_value: str | Path | None,
) -> Path | None:
    """Resolve one optional output path relative to the case TOML location."""

    raw = config_value if override_value is None else override_value
    if raw is None:
        return None
    text = str(raw).strip()
    if text == "":
        return None
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = (Path(config_toml).resolve().parent / path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def write_case_json(path: str | Path, payload: Mapping[str, Any]) -> Path:
    """Write one stable UTF-8 JSON sidecar for a reference case."""

    path_obj = Path(path).resolve()
    path_obj.parent.mkdir(parents=True, exist_ok=True)
    with path_obj.open("w", encoding="utf-8") as stream:
        json.dump(dict(payload), stream, indent=2, ensure_ascii=True)
        stream.write("\n")
    return path_obj


__all__ = [
    "load_case_section",
    "optional_case_output_path",
    "resolve_case_config_path",
    "write_case_json",
]
