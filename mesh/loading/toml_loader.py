"""Lecture et validation TOML pour la distribution des maillages."""

from __future__ import annotations

from pathlib import Path
import re
import tomllib

from mesh.loading.toml_schema import (
    MeshDistributionTomlSchema,
    ValidationError,
)
from mesh.schema import (
    DEFAULT_TOML_SECTION,
    VisualizationConfig,
)


def _looks_like_windows_absolute_path(raw_value: str) -> bool:
    """Detecte un chemin absolu Windows meme sur une plateforme POSIX."""
    return bool(re.match(r"^[A-Za-z]:[\\/]", raw_value))


def _resolve_config_path(
    *,
    config_path: Path,
    raw_value: Path | None,
) -> Path | None:
    """Resout un chemin relatif depuis le dossier du fichier TOML."""
    if raw_value is None:
        return None
    raw_text = str(raw_value).strip()
    path = Path(raw_text).expanduser()
    if path.is_absolute():
        return path.resolve()
    if _looks_like_windows_absolute_path(raw_text):
        raise ValueError(
            "Le TOML contient un chemin absolu Windows qui n'est pas portable sur "
            f"cette machine: '{raw_text}'. Remplacer par un chemin local valide ou "
            "un chemin relatif au fichier TOML."
        )
    return (config_path.parent / path).resolve()


def load_toml_config(
    toml_path: str | Path,
    *,
    section: str = DEFAULT_TOML_SECTION,
) -> VisualizationConfig:
    """Charge la configuration TOML du module de distribution."""

    config_path = Path(toml_path).resolve()
    content = tomllib.loads(config_path.read_text(encoding="utf-8-sig"))

    try:
        parsed = MeshDistributionTomlSchema.from_mapping(content.get(section))
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
