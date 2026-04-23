"""Scaffold one new declarative doc-gallery case."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .gallery_schema import CATEGORY_SPECS
from .manifest_loader import load_json_gallery_case_specs

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFESTS_DIR = Path(__file__).resolve().parent / "manifests"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Scaffold one new copy-assets gallery case and append it to one JSON manifest."
    )
    parser.add_argument("--manifest", required=True, help="Manifest filename or path to update.")
    parser.add_argument("--slug", required=True, help="Stable gallery slug.")
    parser.add_argument("--title", required=True, help="Human-readable gallery title.")
    parser.add_argument(
        "--category",
        required=True,
        choices=sorted(CATEGORY_SPECS),
        help="Gallery category for the new case.",
    )
    parser.add_argument(
        "--asset-dir",
        help=(
            "Repository-relative asset directory. Defaults to "
            "`examples/projects/09_capability_gallery/<category>/<slug>`."
        ),
    )
    parser.add_argument(
        "--image-filename",
        help="Primary committed image filename. Defaults to `<slug>.png`.",
    )
    parser.add_argument(
        "--reproduction-command",
        default="python -m tools.doc_gallery",
        help="Command shown on the case page.",
    )
    parser.add_argument(
        "--deck",
        default="TODO: one-line deck for the gallery card.",
        help="Short card description.",
    )
    parser.add_argument(
        "--summary",
        default="TODO: longer case summary for the case page.",
        help="Longer paragraph for the case page.",
    )
    return parser


def _repo_relative(path: Path, *, repo_root: Path) -> str:
    return path.resolve().relative_to(repo_root.resolve()).as_posix()


def _resolve_manifest_path(manifest: str, *, repo_root: Path) -> Path:
    candidate = Path(manifest)
    if candidate.is_absolute():
        return candidate
    if candidate.parent != Path("."):
        return (repo_root / candidate).resolve()
    return (MANIFESTS_DIR / candidate.name).resolve()


def _load_manifest_payload(manifest_path: Path) -> dict[str, Any]:
    if manifest_path.exists():
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    else:
        payload = {"defaults": {}, "cases": []}
    if not isinstance(payload, dict):
        raise TypeError(f"{manifest_path.as_posix()} must define one top-level mapping.")
    payload.setdefault("defaults", {})
    payload.setdefault("cases", [])
    if not isinstance(payload["defaults"], dict):
        raise TypeError(f"{manifest_path.as_posix()} 'defaults' must be one mapping.")
    if not isinstance(payload["cases"], list):
        raise TypeError(f"{manifest_path.as_posix()} 'cases' must be one list.")
    return payload


def _build_case_entry(
    *,
    slug: str,
    title: str,
    category: str,
    deck: str,
    summary: str,
    reproduction_command: str,
    asset_dir_repo: str,
    image_filename: str,
    defaults: dict[str, Any],
) -> dict[str, Any]:
    image_repo_path = f"{asset_dir_repo}/{image_filename}"
    entry: dict[str, Any] = {
        "slug": slug,
        "title": title,
        "deck": deck,
        "summary": summary,
        "what_it_shows": [
            "TODO: first reading point.",
            "TODO: second reading point.",
        ],
        "source_paths": [
            f"{asset_dir_repo}/README.md",
            image_repo_path,
        ],
        "image_assets": [
            {
                "filename": image_filename,
                "caption": f"TODO: caption for {title}.",
                "alt_text": f"TODO: alt text for {title}",
                "source_path": image_repo_path,
            }
        ],
    }
    if defaults.get("category") != category:
        entry["category"] = category
    if defaults.get("generator") != "copy_assets":
        entry["generator"] = "copy_assets"
    if defaults.get("reproduction_command") != reproduction_command:
        entry["reproduction_command"] = reproduction_command
    return entry


def _write_asset_readme(
    asset_dir: Path,
    *,
    slug: str,
    title: str,
    manifest_repo_path: str,
    image_filename: str,
) -> None:
    readme_path = asset_dir / "README.md"
    if readme_path.exists():
        return
    readme_path.write_text(
        "\n".join(
            [
                f"# {title}",
                "",
                f"Committed source assets for gallery case `{slug}`.",
                "",
                "## Checklist",
                "",
                f"- Replace or add `{image_filename}` in this directory.",
                f"- Review the manifest entry in `{manifest_repo_path}`.",
                f"- Refresh with `python -m tools.doc_gallery --only {slug}`.",
                f"- Verify with `python -m tools.doc_gallery --check --only {slug}`.",
                "",
            ]
        ),
        encoding="utf-8",
    )


def scaffold_copy_assets_case(
    *,
    manifest: str,
    slug: str,
    title: str,
    category: str,
    asset_dir: str | None = None,
    image_filename: str | None = None,
    reproduction_command: str = "python -m tools.doc_gallery",
    deck: str = "TODO: one-line deck for the gallery card.",
    summary: str = "TODO: longer case summary for the case page.",
    repo_root: Path = REPO_ROOT,
) -> tuple[Path, Path]:
    manifest_path = _resolve_manifest_path(manifest, repo_root=repo_root)
    payload = _load_manifest_payload(manifest_path)
    existing_slugs = {
        str(case.get("slug", "")).strip() for case in payload["cases"] if isinstance(case, dict)
    }
    if slug in existing_slugs:
        raise ValueError(f"Gallery slug already exists in {manifest_path.name}: {slug}")

    image_filename = image_filename or f"{slug}.png"
    asset_dir_path = (
        (repo_root / asset_dir).resolve()
        if asset_dir
        else (repo_root / "examples" / "capability_gallery" / category / slug).resolve()
    )
    asset_dir_path.mkdir(parents=True, exist_ok=True)
    asset_dir_repo = _repo_relative(asset_dir_path, repo_root=repo_root)
    manifest_repo_path = _repo_relative(manifest_path, repo_root=repo_root)

    entry = _build_case_entry(
        slug=slug,
        title=title,
        category=category,
        deck=deck,
        summary=summary,
        reproduction_command=reproduction_command,
        asset_dir_repo=asset_dir_repo,
        image_filename=image_filename,
        defaults=dict(payload["defaults"]),
    )
    payload["cases"].append(entry)
    payload["cases"].sort(key=lambda case: str(case.get("slug", "")))
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    _write_asset_readme(
        asset_dir_path,
        slug=slug,
        title=title,
        manifest_repo_path=manifest_repo_path,
        image_filename=image_filename,
    )
    load_json_gallery_case_specs(manifest_path.name, manifests_dir=manifest_path.parent)
    return manifest_path, asset_dir_path


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    manifest_path, asset_dir_path = scaffold_copy_assets_case(
        manifest=args.manifest,
        slug=args.slug,
        title=args.title,
        category=args.category,
        asset_dir=args.asset_dir,
        image_filename=args.image_filename,
        reproduction_command=args.reproduction_command,
        deck=args.deck,
        summary=args.summary,
    )
    print(f"Manifest updated: {manifest_path.as_posix()}")
    print(f"Asset directory ready: {asset_dir_path.as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
