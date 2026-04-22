"""Selective publication of launcher outputs for the documentation gallery."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from hydromodpy.core.config.profile import Profile
from hydromodpy.core.config.base import HydroModelBase


DEFAULT_FLOW_GALLERY_ASSETS: tuple[str, ...] = (
    "flow_state_triptych.png",
    "recharge_discharge_cumulative.png",
    "watertable_elevation.png",
    "watertable_depth.png",
    "flow_support_overview.png",
)


class CapabilityGalleryConfig(HydroModelBase):
    """Optional publication target for stable, versionable run figures."""

    model_config = ConfigDict(extra="forbid")

    enabled: Annotated[bool, Profile.USER] = Field(
        default=False,
        description="Copy selected postprocess figures into a versionable gallery folder.",
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
            "Figure filenames copied from `<run>/_postprocess/_figures`. "
            "Nested paths are not accepted."
        ),
    )


def _safe_asset_name(value: str) -> str:
    """Return one safe relative asset filename."""
    name = str(value).strip().replace("\\", "/")
    path = Path(name)
    if name == "" or path.is_absolute() or ".." in path.parts or len(path.parts) != 1:
        raise ValueError(f"Invalid capability gallery asset name: {value!r}")
    return path.name


def _relative_to_cwd(path: Path) -> str:
    """Return a readable path relative to cwd when possible."""
    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


def publish_run_to_capability_gallery(
    *,
    run_id: str,
    run_folder: Path,
    config: CapabilityGalleryConfig,
    solvers: tuple[str, ...] = (),
) -> dict[str, object] | None:
    """Copy selected run figures into one stable gallery source folder.

    The publication is intentionally selective: large solver workspaces stay in
    `results_simulations`, while a handful of figures and one manifest can be
    committed under `examples/capability_gallery`.
    """
    if not config.enabled:
        return None
    if config.output_dir is None:
        raise ValueError("[capability_gallery] is enabled but output_dir is not configured.")

    source_figure_dir = Path(run_folder) / "_postprocess" / "_figures"
    output_dir = Path(config.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    copied_assets: list[dict[str, object]] = []
    missing_assets: list[str] = []
    for raw_asset in config.assets:
        asset_name = _safe_asset_name(raw_asset)
        source_path = source_figure_dir / asset_name
        if not source_path.exists():
            missing_assets.append(asset_name)
            continue
        target_path = output_dir / asset_name
        shutil.copy2(source_path, target_path)
        copied_assets.append(
            {
                "filename": asset_name,
                "source_path": _relative_to_cwd(source_path),
                "target_path": _relative_to_cwd(target_path),
            }
        )

    manifest: dict[str, object] = {
        "schema_version": "hydromodpy_capability_gallery_publication_v1",
        "case_slug": str(config.case_slug),
        "run_id": str(run_id),
        "published_at_utc": datetime.now(timezone.utc).isoformat(),
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
