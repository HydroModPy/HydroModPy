"""Chargement du bundle exporte pour la distribution des maillages."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from mesh.loading.toml_loader import load_toml_config
from mesh.reader import (
    load_catchment_mesh_bundle as load_internal_catchment_mesh_bundle,
)
from mesh.schema import (
    DEFAULT_TOML_SECTION,
    MeshBundleLike,
    MeshVisualizationData,
    VisualizationConfig,
)


def _resolve_bundle_dir(bundle_dir: Path) -> Path:
    """Validate one bundle directory before trying to read it."""
    resolved = Path(bundle_dir).resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"Dossier bundle introuvable : {resolved}")
    if not resolved.is_dir():
        raise NotADirectoryError(f"Le chemin bundle n'est pas un dossier : {resolved}")
    return resolved


def _load_bundle(bundle_dir: Path) -> MeshBundleLike:
    """Load one bundle with the versioned reader shipped in ``mesh/``."""
    resolved_dir = _resolve_bundle_dir(bundle_dir)
    try:
        return cast(MeshBundleLike, load_internal_catchment_mesh_bundle(resolved_dir))
    except Exception as exc:
        raise RuntimeError(
            "Impossible de charger le bundle avec le lecteur versionne dans "
            f"mesh/reader.py. Bundle: {resolved_dir}. Erreur: {exc}"
        ) from exc


def load_visualization_data(
    config: VisualizationConfig,
) -> MeshVisualizationData:
    """Charge le bundle et assemble l'objet de travail final."""
    mesh = _load_bundle(config.bundle_dir)
    return MeshVisualizationData(mesh=mesh, config=config)


def load_visualization_data_from_toml(
    toml_path: str | Path,
    *,
    section: str = DEFAULT_TOML_SECTION,
) -> MeshVisualizationData:
    """Enchaine lecture du TOML puis lecture du bundle."""
    config = load_toml_config(toml_path, section=section)
    return load_visualization_data(config)


__all__ = [
    "load_visualization_data",
    "load_visualization_data_from_toml",
]
