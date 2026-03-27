"""Load one exported mesh bundle for the standalone visualization workflow."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from .toml_loader import load_toml_config
from ..reader import (
    load_catchment_mesh_bundle as load_internal_catchment_mesh_bundle,
)
from ..bundle_contracts import (
    MeshBundleLike,
)
from ..schema import (
    DEFAULT_TOML_SECTION,
    MeshVisualizationData,
    VisualizationConfig,
)


def _resolve_bundle_dir(bundle_dir: Path) -> Path:
    """Validate one bundle directory before trying to read it."""
    resolved = Path(bundle_dir).resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"Bundle directory not found: {resolved}")
    if not resolved.is_dir():
        raise NotADirectoryError(f"Bundle path is not a directory: {resolved}")
    return resolved


def _load_bundle(bundle_dir: Path) -> MeshBundleLike:
    """Load one bundle with the versioned reader shipped in ``mesh_bundle_viewer/``."""
    resolved_dir = _resolve_bundle_dir(bundle_dir)
    try:
        return cast(MeshBundleLike, load_internal_catchment_mesh_bundle(resolved_dir))
    except Exception as exc:
        raise RuntimeError(
            "Failed to load the bundle with the versioned reader shipped in "
            f"mesh_bundle_viewer/reader.py. Bundle: {resolved_dir}. Error: {exc}"
        ) from exc


def load_visualization_data(
    config: VisualizationConfig,
) -> MeshVisualizationData:
    """Load the bundle and assemble the final runtime payload."""
    mesh = _load_bundle(config.bundle_dir)
    return MeshVisualizationData(mesh=mesh, config=config)


def load_visualization_data_from_toml(
    toml_path: str | Path,
    *,
    section: str = DEFAULT_TOML_SECTION,
) -> MeshVisualizationData:
    """Load TOML config first, then load the referenced bundle."""
    config = load_toml_config(toml_path, section=section)
    return load_visualization_data(config)


__all__ = [
    "load_visualization_data",
    "load_visualization_data_from_toml",
]


