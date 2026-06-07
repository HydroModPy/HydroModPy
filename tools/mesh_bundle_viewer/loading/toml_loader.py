"""Read, validate, and resolve TOML config for the standalone viewer.

This module is the bridge between the stable public TOML contract and the
runtime ``VisualizationConfig`` used by the rest of the package.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from ..schema import (
    DEFAULT_TOML_SECTION,
    VisualizationConfig,
)
from .toml_contracts import (
    MeshVisualizationTomlSchema,
)
from .toml_validation import (
    ValidationError,
)


def _looks_like_windows_absolute_path(raw_value: str) -> bool:
    """Detect a Windows absolute path even when running on a POSIX platform."""
    return bool(re.match(r"^[A-Za-z]:[\\/]", raw_value))


def _resolve_config_path(
    *,
    config_path: Path,
    raw_value: Path | None,
) -> Path | None:
    """Resolve one optional TOML path relative to the TOML file location."""
    if raw_value is None:
        return None
    raw_text = str(raw_value).strip()
    path = Path(raw_text).expanduser()
    if path.is_absolute():
        return path.resolve()
    if _looks_like_windows_absolute_path(raw_text):
        raise ValueError(
            "The TOML file contains a Windows absolute path that is not portable "
            f"on this machine: '{raw_text}'. Replace it with a valid local path "
            "or a path relative to the TOML file."
        )
    return (config_path.parent / path).resolve()


def load_toml_config(
    toml_path: str | Path,
    *,
    section: str = DEFAULT_TOML_SECTION,
) -> VisualizationConfig:
    """Load one public TOML config into a resolved runtime config.

    This is the recommended low-level entry point when a caller wants the
    validated ``VisualizationConfig`` object but does not want to execute the
    full visualization pipeline yet.
    """

    config_path = Path(toml_path).resolve()
    content = tomllib.loads(config_path.read_text(encoding="utf-8-sig"))

    try:
        parsed = MeshVisualizationTomlSchema.from_mapping(content.get(section))
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc

    return VisualizationConfig(
        bundle_dir=_resolve_config_path(
            config_path=config_path,
            raw_value=parsed.bundle_dir,
        ),
        figure_output_path=_resolve_config_path(
            config_path=config_path,
            raw_value=parsed.figure_output_path,
        ),
        summary_output_path=_resolve_config_path(
            config_path=config_path,
            raw_value=parsed.summary_output_path,
        ),
        show_window=parsed.show_window,
        plot=parsed.plot.to_plot_config(),
    )


__all__ = [
    "load_toml_config",
]
