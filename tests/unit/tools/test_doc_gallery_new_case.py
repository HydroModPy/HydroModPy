"""Unit tests for the doc-gallery case scaffold helper."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.doc_gallery.manifest_loader import load_json_gallery_case_specs
from tools.doc_gallery.new_case import scaffold_copy_assets_case


def test_scaffold_copy_assets_case_updates_manifest_and_assets(tmp_path: Path) -> None:
    manifest_path = tmp_path / "tools" / "doc_gallery" / "manifests" / "demo_cases.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            {
                "defaults": {
                    "category": "geographic",
                    "generator": "copy_assets",
                    "reproduction_command": "python -m demo",
                },
                "cases": [],
            },
            indent=2,
            ensure_ascii=True,
        )
        + "\n",
        encoding="utf-8",
    )

    updated_manifest_path, asset_dir_path = scaffold_copy_assets_case(
        manifest=str(manifest_path),
        slug="geographic_demo_case",
        title="Geographic Demo Case",
        category="geographic",
        reproduction_command="python -m demo",
        repo_root=tmp_path,
    )

    payload = json.loads(updated_manifest_path.read_text(encoding="utf-8"))
    assert updated_manifest_path == manifest_path
    assert (
        asset_dir_path
        == tmp_path
        / "examples"
        / "projects"
        / "09_capability_gallery"
        / "geographic"
        / "geographic_demo_case"
    )
    assert payload["cases"][0]["slug"] == "geographic_demo_case"
    assert "category" not in payload["cases"][0]
    assert "generator" not in payload["cases"][0]
    assert "reproduction_command" not in payload["cases"][0]
    assert (asset_dir_path / "README.md").exists()
    assert "python -m tools.doc_gallery --only geographic_demo_case" in (
        asset_dir_path / "README.md"
    ).read_text(encoding="utf-8")

    specs = load_json_gallery_case_specs(
        manifest_path.name,
        manifests_dir=manifest_path.parent,
    )
    assert specs[0].slug == "geographic_demo_case"
    assert specs[0].image_assets[0].source_path == (
        "examples/projects/09_capability_gallery/geographic/"
        "geographic_demo_case/geographic_demo_case.png"
    )


def test_scaffold_copy_assets_case_rejects_duplicate_slug(tmp_path: Path) -> None:
    manifest_path = tmp_path / "tools" / "doc_gallery" / "manifests" / "demo_cases.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            {
                "defaults": {
                    "category": "geographic",
                    "generator": "copy_assets",
                },
                "cases": [
                    {
                        "slug": "geographic_demo_case",
                        "title": "Existing",
                        "deck": "Deck",
                        "summary": "Summary",
                        "what_it_shows": ["Point"],
                        "reproduction_command": "python -m demo",
                        "image_assets": [
                            {
                                "filename": "existing.png",
                                "caption": "Caption",
                                "alt_text": "Alt",
                                "source_path": "examples/capability_gallery/geographic/geographic_demo_case/existing.png",
                            }
                        ],
                    }
                ],
            },
            indent=2,
            ensure_ascii=True,
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="already exists"):
        scaffold_copy_assets_case(
            manifest=str(manifest_path),
            slug="geographic_demo_case",
            title="Geographic Demo Case",
            category="geographic",
            repo_root=tmp_path,
        )
