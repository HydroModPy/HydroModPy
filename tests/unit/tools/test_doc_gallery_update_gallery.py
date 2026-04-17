"""Unit tests for capability-gallery refresh robustness."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from tools.doc_gallery.gallery_manifest import GalleryCaseSpec, GalleryImageAsset
from tools.doc_gallery import update_gallery


def test_reset_generated_dirs_retries_transient_permission_error(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Transient Windows locks should not fail gallery cleanup."""

    docs_root = tmp_path / "source"
    gallery_dir = docs_root / "capability_gallery"
    static_dir = docs_root / "_static" / "capability_gallery"
    gallery_dir.mkdir(parents=True)
    static_dir.mkdir(parents=True)
    (gallery_dir / "stale.rst").write_text("stale", encoding="utf-8")
    (static_dir / "stale.png").write_text("stale", encoding="utf-8")

    calls = {"count": 0}
    sleeps: list[float] = []
    real_rmtree = shutil.rmtree

    def flaky_rmtree(path, *args, **kwargs):
        target = Path(path)
        if target == gallery_dir and calls["count"] == 0:
            calls["count"] += 1
            raise PermissionError(32, "The process cannot access the file")
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(update_gallery.shutil, "rmtree", flaky_rmtree)
    monkeypatch.setattr(update_gallery.time, "sleep", sleeps.append)
    monkeypatch.setattr(update_gallery.gc, "collect", lambda: None)

    update_gallery._reset_generated_dirs(docs_root)

    assert gallery_dir.exists()
    assert static_dir.exists()
    assert list(gallery_dir.iterdir()) == []
    assert list(static_dir.iterdir()) == []
    assert calls["count"] == 1
    assert sleeps == [update_gallery._remove_tree_with_retry.__kwdefaults__["base_delay_s"]]


def _build_spec(*, slug: str, category: str) -> GalleryCaseSpec:
    return GalleryCaseSpec(
        slug=slug,
        title=f"Title {slug}",
        category=category,
        deck=f"Deck {slug}",
        summary=f"Summary {slug}",
        what_it_shows=("Point",),
        reproduction_command=f"python -m {slug}",
        source_paths=(f"examples/{slug}.toml",),
        generator="copy_assets",
        image_assets=(
            GalleryImageAsset(
                filename=f"{slug}.png",
                caption=f"Caption {slug}",
                alt_text=f"Alt {slug}",
                source_path=f"examples/{slug}.png",
            ),
        ),
    )


def test_normalize_filter_values_supports_repeat_and_csv() -> None:
    assert update_gallery._normalize_filter_values(["a,b", "b", " c "]) == ("a", "b", "c")


def test_select_gallery_specs_filters_by_slug_and_category() -> None:
    specs = (
        _build_spec(slug="geo_alpha", category="geographic"),
        _build_spec(slug="geo_beta", category="geographic"),
        _build_spec(slug="sim_alpha", category="simulation"),
    )

    selected = update_gallery._select_gallery_specs(
        specs,
        only_slugs=("sim_alpha",),
        categories=("geographic",),
    )

    assert [spec.slug for spec in selected] == ["geo_alpha", "geo_beta", "sim_alpha"]


def test_select_gallery_specs_rejects_unknown_filters() -> None:
    specs = (_build_spec(slug="geo_alpha", category="geographic"),)

    with pytest.raises(ValueError, match="Unknown gallery slugs"):
        update_gallery._select_gallery_specs(specs, only_slugs=("missing_slug",))

    with pytest.raises(ValueError, match="Unknown gallery categories"):
        update_gallery._select_gallery_specs(specs, categories=("missing_category",))


def test_main_list_respects_selection_filters(monkeypatch, capsys) -> None:
    specs = (
        _build_spec(slug="geo_alpha", category="geographic"),
        _build_spec(slug="sim_alpha", category="simulation"),
    )
    monkeypatch.setattr(update_gallery, "build_gallery_specs", lambda: specs)

    exit_code = update_gallery.main(["--list", "--category", "geographic"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "[geographic] geo_alpha" in captured.out
    assert "sim_alpha" not in captured.out


def test_reset_generated_dirs_retries_when_onerror_hits_locked_file(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Locked files raised from ``rmtree`` onerror should defer to the retry loop."""

    docs_root = tmp_path / "source"
    gallery_dir = docs_root / "capability_gallery"
    static_dir = docs_root / "_static" / "capability_gallery"
    gallery_dir.mkdir(parents=True)
    static_dir.mkdir(parents=True)
    locked_file = gallery_dir / "stale.rst"
    locked_file.write_text("stale", encoding="utf-8")

    calls = {"count": 0}
    sleeps: list[float] = []
    real_rmtree = shutil.rmtree

    def flaky_rmtree(path, *args, **kwargs):
        target = Path(path)
        if target == gallery_dir and calls["count"] == 0:
            calls["count"] += 1
            onerror = kwargs["onerror"]

            def locked_unlink(target_path):
                raise PermissionError(
                    32,
                    "The process cannot access the file",
                    str(target_path),
                )

            onerror(
                locked_unlink,
                str(locked_file),
                (
                    PermissionError,
                    PermissionError(
                        32,
                        "The process cannot access the file",
                        str(locked_file),
                    ),
                    None,
                ),
            )
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(update_gallery.shutil, "rmtree", flaky_rmtree)
    monkeypatch.setattr(update_gallery.time, "sleep", sleeps.append)
    monkeypatch.setattr(update_gallery.gc, "collect", lambda: None)

    update_gallery._reset_generated_dirs(docs_root)

    assert gallery_dir.exists()
    assert static_dir.exists()
    assert list(gallery_dir.iterdir()) == []
    assert list(static_dir.iterdir()) == []
    assert calls["count"] == 1
    assert sleeps == [update_gallery._remove_tree_with_retry.__kwdefaults__["base_delay_s"]]
