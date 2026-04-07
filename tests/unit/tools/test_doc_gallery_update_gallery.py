"""Unit tests for capability-gallery refresh robustness."""

from __future__ import annotations

import shutil
from pathlib import Path

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
