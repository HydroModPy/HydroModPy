"""Unit tests for the capability-gallery PNG drift check."""

from __future__ import annotations

from pathlib import Path

from tools.doc_gallery import png_drift


def _png_bytes(seed: int) -> bytes:
    return f"fake-png-content-{seed}".encode()


def _make_tree(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "geographic").mkdir()
    (root / "mesh").mkdir()
    (root / "geographic" / "case_a.png").write_bytes(_png_bytes(1))
    (root / "geographic" / "case_b.png").write_bytes(_png_bytes(2))
    (root / "mesh" / "case_c.png").write_bytes(_png_bytes(3))


def test_hash_png_tree_collects_every_png(tmp_path: Path) -> None:
    _make_tree(tmp_path)

    hashes = png_drift.hash_png_tree(tmp_path)

    assert set(hashes) == {
        "geographic/case_a.png",
        "geographic/case_b.png",
        "mesh/case_c.png",
    }
    for value in hashes.values():
        assert len(value) == 64


def test_drift_detects_change_missing_and_added(tmp_path: Path) -> None:
    gallery_root = tmp_path / "gallery"
    baseline_path = tmp_path / "baseline.json"
    _make_tree(gallery_root)

    png_drift.write_baseline(png_drift.hash_png_tree(gallery_root), baseline_path)

    no_drift = png_drift.check_drift(
        gallery_root=gallery_root,
        baseline_path=baseline_path,
    )
    assert no_drift.has_drift is False
    assert no_drift.format_lines() == []

    (gallery_root / "geographic" / "case_a.png").write_bytes(b"changed-bytes")
    (gallery_root / "geographic" / "case_b.png").unlink()
    (gallery_root / "mesh" / "case_d.png").write_bytes(_png_bytes(4))

    report = png_drift.check_drift(
        gallery_root=gallery_root,
        baseline_path=baseline_path,
    )

    assert report.has_drift is True
    assert [entry[0] for entry in report.mismatched] == ["geographic/case_a.png"]
    assert report.missing == ("geographic/case_b.png",)
    assert report.added == ("mesh/case_d.png",)

    formatted = report.format_lines()
    assert any(line.startswith("changed: geographic/case_a.png") for line in formatted)
    assert "missing: geographic/case_b.png" in formatted
    assert "added: mesh/case_d.png" in formatted


def test_update_baseline_round_trip(tmp_path: Path) -> None:
    gallery_root = tmp_path / "gallery"
    baseline_path = tmp_path / "baseline.json"
    _make_tree(gallery_root)

    written = png_drift.update_baseline(
        gallery_root=gallery_root,
        baseline_path=baseline_path,
    )

    loaded = png_drift.load_baseline(baseline_path)

    assert written == loaded
    assert set(loaded) == {
        "geographic/case_a.png",
        "geographic/case_b.png",
        "mesh/case_c.png",
    }
