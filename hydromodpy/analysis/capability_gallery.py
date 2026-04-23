"""Selective publication of run figures into the documentation gallery.

Two production paths are supported:

1. **Render on demand** (preferred) - when a ``Run`` is provided, each asset
   name is interpreted as ``<figure_name>.png`` and rendered through
   ``run.plot(figure_name, save=...)``. Figure names come from the canonical
   registry in ``hydromodpy.display``.
2. **Copy existing file** (fallback) - if no ``Run`` is available or the
   figure cannot be rendered, the publisher looks for a matching PNG in one
   of the candidate subdirectories of the run folder
   (``_postprocess/_figures``, ``figures``, ``_figures``) and copies it
   verbatim. Missing assets are listed in the manifest.
"""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

from pydantic import ConfigDict, Field

from hydromodpy.core.config.base import HydroModelBase
from hydromodpy.core.config.profile import Profile

if TYPE_CHECKING:
    from hydromodpy.results.run import Run

DEFAULT_FLOW_GALLERY_ASSETS: tuple[str, ...] = (
    "piezometric_map.png",
    "seepage_map.png",
    "hydrograph.png",
    "water_budget.png",
    "watershed_id_card.png",
)

_CANDIDATE_SOURCE_SUBDIRS: tuple[str, ...] = (
    "_postprocess/_figures",
    "figures",
    "_figures",
)


class CapabilityGalleryConfig(HydroModelBase):
    """Optional publication target for stable, versionable run figures."""

    model_config = ConfigDict(extra="forbid")

    enabled: Annotated[bool, Profile.USER] = Field(
        default=False,
        description="Render (or copy) selected figures into a versionable gallery folder.",
    )
    output_dir: Annotated[Path | None, Profile.USER] = Field(
        default=None,
        description=(
            "Destination directory for selected gallery assets. Relative paths "
            "are resolved against the TOML directory."
        ),
    )
    case_slug: Annotated[str, Profile.USER] = Field(
        default="launcher_simulation_flow_case",
        description="Stable identifier used in the gallery manifest.",
    )
    assets: Annotated[tuple[str, ...], Profile.USER] = Field(
        default=DEFAULT_FLOW_GALLERY_ASSETS,
        description=(
            "Asset filenames. Each ``<name>.png`` is first rendered via "
            "``run.plot(<name>)`` when a Run is available, otherwise copied "
            "from one of the standard figure subdirs of the run folder."
        ),
    )


def _safe_asset_name(value: str) -> str:
    name = str(value).strip().replace("\\", "/")
    path = Path(name)
    if name == "" or path.is_absolute() or ".." in path.parts or len(path.parts) != 1:
        raise ValueError(f"Invalid capability gallery asset name: {value!r}")
    return path.name


def _relative_to_cwd(path: Path) -> str:
    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


def _find_existing_asset(run_folder: Path, asset_name: str) -> Path | None:
    for subdir in _CANDIDATE_SOURCE_SUBDIRS:
        candidate = Path(run_folder) / subdir / asset_name
        if candidate.exists():
            return candidate
    return None


def _try_render(run: Run, figure_name: str, target_path: Path) -> bool:
    try:
        capabilities = list(run.display_capabilities)
    except Exception:
        capabilities = []
    if figure_name not in capabilities:
        return False
    try:
        run.plot(figure_name, save=target_path)
    except Exception:
        return False
    return target_path.exists()


def publish_run_to_capability_gallery(
    *,
    run_id: str,
    run_folder: Path,
    config: CapabilityGalleryConfig,
    solvers: tuple[str, ...] = (),
    run: Run | None = None,
) -> dict[str, object] | None:
    """Publish selected figures into the versioned gallery folder.

    Each asset named ``<figure_name>.png`` is produced as follows:

    - if ``run`` is provided and ``figure_name`` is in
      ``run.display_capabilities``, it is rendered through
      ``run.plot(figure_name, save=...)``;
    - otherwise, the publisher looks for a pre-existing PNG of the same
      name in standard subfolders of ``run_folder`` and copies it;
    - otherwise, the asset is listed as missing in the manifest.
    """
    if not config.enabled:
        return None
    if config.output_dir is None:
        raise ValueError("[capability_gallery] is enabled but output_dir is not configured.")

    output_dir = Path(config.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    copied_assets: list[dict[str, object]] = []
    missing_assets: list[str] = []
    for raw_asset in config.assets:
        asset_name = _safe_asset_name(raw_asset)
        target_path = output_dir / asset_name

        rendered = False
        if run is not None:
            figure_name = Path(asset_name).stem
            rendered = _try_render(run, figure_name, target_path)

        if rendered:
            copied_assets.append(
                {
                    "filename": asset_name,
                    "source": "rendered",
                    "target_path": _relative_to_cwd(target_path),
                }
            )
            continue

        existing = _find_existing_asset(Path(run_folder), asset_name)
        if existing is None:
            missing_assets.append(asset_name)
            continue

        shutil.copy2(existing, target_path)
        copied_assets.append(
            {
                "filename": asset_name,
                "source": "copied",
                "source_path": _relative_to_cwd(existing),
                "target_path": _relative_to_cwd(target_path),
            }
        )

    manifest: dict[str, object] = {
        "schema_version": "hydromodpy_capability_gallery_publication_v2",
        "case_slug": str(config.case_slug),
        "run_id": str(run_id),
        "published_at_utc": datetime.now(UTC).isoformat(),
        "source_run_folder": _relative_to_cwd(Path(run_folder)),
        "solvers": [str(solver) for solver in solvers],
        "assets": copied_assets,
        "missing_assets": missing_assets,
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )
    return manifest


__all__ = [
    "CapabilityGalleryConfig",
    "DEFAULT_FLOW_GALLERY_ASSETS",
    "publish_run_to_capability_gallery",
]
