"""Import one local mesh bundle into the canonical repo layout for the doc gallery."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
from pathlib import Path

from .mesh_case_registry import (
    MESH_GALLERY_REQUIRED_BUNDLE_FILES,
    MESH_GALLERY_VARIANT_SPECS,
    REPO_ROOT,
    build_case_readme_text,
    build_default_case_metadata,
    build_viewer_config_text,
    case_paths,
    default_case_slug,
    default_launcher_config_for_scale,
    load_bundle_summary,
    repo_relative,
    validate_bundle_dir,
)


def build_parser() -> argparse.ArgumentParser:
    """Build the public CLI parser for bundle imports."""

    parser = argparse.ArgumentParser(
        description=(
            "Copy one mesh bundle from a local results folder into the canonical repository "
            "layout used by the documentation capability gallery."
        )
    )
    parser.add_argument(
        "--source-bundle", required=True, help="Path to one existing bundle directory."
    )
    parser.add_argument(
        "--scale",
        required=True,
        choices=("10km2", "100km2", "1000km2"),
        help="Gallery scale bucket used under examples/projects/07_mesh_gallery/.",
    )
    parser.add_argument(
        "--variant",
        required=True,
        choices=tuple(MESH_GALLERY_VARIANT_SPECS),
        help="Canonical gallery variant for the imported case.",
    )
    parser.add_argument(
        "--outlet-id", required=True, help="Outlet identifier used in titles and slugs."
    )
    parser.add_argument("--case-slug", default=None, help="Optional case slug override.")
    parser.add_argument("--title", default=None, help="Optional case title override.")
    parser.add_argument("--deck", default=None, help="Optional card deck override.")
    parser.add_argument("--summary", default=None, help="Optional page summary override.")
    parser.add_argument(
        "--what-it-shows",
        action="append",
        default=None,
        help="Optional bullet override. Repeat the flag for multiple bullets.",
    )
    parser.add_argument(
        "--reproduction-command",
        default=None,
        help="Optional reproduction command shown on the gallery page.",
    )
    parser.add_argument(
        "--launcher-config",
        default=None,
        help=(
            "Optional repo-relative launcher config path. When omitted, one default config is selected from the scale."
        ),
    )
    parser.add_argument(
        "--destination-root",
        default=None,
        help=(
            "Optional destination root overriding the canonical examples/projects/07_mesh_gallery "
            "directory. Mostly useful for tests."
        ),
    )
    parser.add_argument(
        "--repo-root",
        default=str(REPO_ROOT),
        help="Repository root used to compute repo-relative paths inside case metadata.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing imported case directory if it already exists.",
    )
    return parser


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def _windows_extended_length_path(path: Path) -> str:
    """Return a Windows long-path spelling while keeping normal paths unchanged."""
    normalized = path.expanduser().resolve()
    text = str(normalized)
    if not text.startswith("\\\\"):
        return "\\\\?\\" + text
    if text.startswith("\\\\?\\"):
        return text
    return "\\\\?\\UNC\\" + text.lstrip("\\")


def _copy_file(source_path: Path, destination_path: Path) -> None:
    """Copy one file, using extended-length paths on Windows."""
    if os.name == "nt":
        shutil.copy2(
            _windows_extended_length_path(source_path),
            _windows_extended_length_path(destination_path),
        )
        return
    shutil.copy2(source_path, destination_path)


def _resolve_existing_path(candidate: object, *, base_dir: Path) -> Path | None:
    token = "" if candidate is None else str(candidate).strip()
    if token == "":
        return None

    path = Path(token).expanduser()
    candidates = [path.resolve()]
    if not path.is_absolute():
        candidates.insert(0, (base_dir / path).resolve())
    for resolved in candidates:
        if resolved.exists():
            return resolved
    return None


def _copy_optional_figure(source_path: Path | None, destination_path: Path) -> Path | None:
    if source_path is None:
        return None
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    _copy_file(source_path, destination_path)
    return destination_path


def import_mesh_bundle_case(
    *,
    source_bundle: Path,
    scale: str,
    variant: str,
    outlet_id: str,
    repo_root: Path = REPO_ROOT,
    destination_root: Path | None = None,
    case_slug: str | None = None,
    title: str | None = None,
    deck: str | None = None,
    summary: str | None = None,
    what_it_shows: tuple[str, ...] | None = None,
    reproduction_command: str | None = None,
    launcher_config_path: str | None = None,
    force: bool = False,
) -> Path:
    """Import one local bundle into the canonical gallery-case layout."""

    source_bundle_dir = source_bundle.expanduser().resolve()
    validate_bundle_dir(source_bundle_dir)
    repo_root = repo_root.expanduser().resolve()
    gallery_root = (
        destination_root.expanduser().resolve()
        if destination_root is not None
        else repo_root / "examples" / "mesh_gallery"
    )

    slug = case_slug or default_case_slug(scale=scale, outlet_id=outlet_id, variant=variant)
    paths = case_paths(scale=scale, slug=slug, repo_root=repo_root)
    if destination_root is not None:
        paths = case_paths(scale=scale, slug=slug, repo_root=repo_root)
        base_scale_dir = gallery_root / scale
        paths = paths.__class__(
            case_dir=base_scale_dir / slug,
            bundle_dir=base_scale_dir / slug / "bundle",
            figures_dir=base_scale_dir / slug / "figures",
            case_json_path=base_scale_dir / slug / "case.json",
            viewer_config_path=base_scale_dir / slug / "viewer_config.toml",
            readme_path=base_scale_dir / slug / "README.md",
        )

    temp_source_root: tempfile.TemporaryDirectory[str] | None = None
    bundle_dir = source_bundle_dir
    try:
        if paths.case_dir.exists():
            if not force:
                raise FileExistsError(
                    f"Destination case directory already exists: {paths.case_dir}. Use --force to overwrite it."
                )
            # When re-importing an already versioned case, stage the current bundle before deleting it.
            if source_bundle_dir == paths.bundle_dir or paths.case_dir in source_bundle_dir.parents:
                temp_source_root = tempfile.TemporaryDirectory(
                    prefix="hydromodpy_mesh_gallery_import_"
                )
                staged_bundle_dir = Path(temp_source_root.name) / source_bundle_dir.name
                shutil.copytree(source_bundle_dir, staged_bundle_dir)
                bundle_dir = staged_bundle_dir
            shutil.rmtree(paths.case_dir)
        paths.bundle_dir.mkdir(parents=True, exist_ok=True)

        copied_filenames: list[str] = []
        for child in sorted(bundle_dir.iterdir()):
            if not child.is_file():
                continue
            _copy_file(child, paths.bundle_dir / child.name)
            copied_filenames.append(child.name)

        imported_summary = load_bundle_summary(paths.bundle_dir)
        imported_summary["bundle_readme_present"] = "README.md" in copied_filenames

        preferred_doc_figure = _copy_optional_figure(
            _resolve_existing_path(
                imported_summary.get("output_figure"), base_dir=bundle_dir.parent
            ),
            paths.figures_dir / "mesh_overview.png",
        )
        preferred_doc_regional_figure = _copy_optional_figure(
            _resolve_existing_path(
                imported_summary.get("output_figure_regional"), base_dir=bundle_dir.parent
            ),
            paths.figures_dir / "mesh_regional.png",
        )

        launcher_config = launcher_config_path or default_launcher_config_for_scale(scale)
        launcher_abs = repo_root / launcher_config
        if not launcher_abs.exists():
            raise FileNotFoundError(
                f"Launcher config path does not exist under repo root: {launcher_config}"
            )

        case_rel_dir = repo_relative(paths.case_dir, repo_root=repo_root)
        metadata = build_default_case_metadata(
            scale=scale,
            variant=variant,
            outlet_id=outlet_id,
            slug=slug,
            case_rel_dir=case_rel_dir,
            launcher_config_path=launcher_config,
            source_bundle_summary=imported_summary,
            title=title,
            deck=deck,
            summary=summary,
            what_it_shows=what_it_shows,
            reproduction_command=reproduction_command,
            preferred_doc_figure_path=(
                None
                if preferred_doc_figure is None
                else repo_relative(preferred_doc_figure, repo_root=repo_root)
            ),
            preferred_doc_regional_figure_path=(
                None
                if preferred_doc_regional_figure is None
                else repo_relative(preferred_doc_regional_figure, repo_root=repo_root)
            ),
        )

        color_field = str(MESH_GALLERY_VARIANT_SPECS[variant]["color_field"])
        viewer_config_text = build_viewer_config_text(
            title=str(metadata["title"]),
            color_field=color_field,
        )
        _write_text(paths.viewer_config_path, viewer_config_text)
        _write_json(paths.case_json_path, metadata)
        _write_text(paths.readme_path, build_case_readme_text(metadata))
        return paths.case_dir
    finally:
        if temp_source_root is not None:
            temp_source_root.cleanup()


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for importing one mesh bundle."""

    args = build_parser().parse_args(argv)
    case_dir = import_mesh_bundle_case(
        source_bundle=Path(args.source_bundle),
        scale=str(args.scale),
        variant=str(args.variant),
        outlet_id=str(args.outlet_id),
        repo_root=Path(args.repo_root),
        destination_root=None if args.destination_root is None else Path(args.destination_root),
        case_slug=args.case_slug,
        title=args.title,
        deck=args.deck,
        summary=args.summary,
        what_it_shows=None if args.what_it_shows is None else tuple(args.what_it_shows),
        reproduction_command=args.reproduction_command,
        launcher_config_path=args.launcher_config,
        force=bool(args.force),
    )
    print("Imported mesh-gallery case:")
    print(f"  {case_dir}")
    print("Bundle files copied:")
    for filename in MESH_GALLERY_REQUIRED_BUNDLE_FILES:
        print(f"  - {filename}")
    print("Next steps:")
    print("  1. Review case.json / viewer_config.toml wording and imported figure selection.")
    print("  2. Run `python -m tools.doc_gallery` to regenerate the documentation pages.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
