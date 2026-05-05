"""SHA-256 drift check for capability-gallery PNG figures.

Hashes every PNG under ``docs/source/_static/capability_gallery/`` and
compares against a committed baseline (``tools/doc_gallery/png_baseline.json``)
to flag unexpected figure changes after a generator run.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
GALLERY_PNG_ROOT = REPO_ROOT / "docs" / "source" / "_static" / "capability_gallery"
BASELINE_PATH = Path(__file__).resolve().parent / "png_baseline.json"


@dataclass(frozen=True)
class DriftReport:
    """Result of comparing the live PNG tree against a baseline."""

    mismatched: tuple[tuple[str, str, str], ...]
    missing: tuple[str, ...]
    added: tuple[str, ...]

    @property
    def has_drift(self) -> bool:
        return bool(self.mismatched or self.missing or self.added)

    def format_lines(self) -> list[str]:
        lines: list[str] = []
        for relative_path, baseline_hash, current_hash in self.mismatched:
            lines.append(
                f"changed: {relative_path} (baseline {baseline_hash[:12]}, "
                f"current {current_hash[:12]})"
            )
        for relative_path in self.missing:
            lines.append(f"missing: {relative_path}")
        for relative_path in self.added:
            lines.append(f"added: {relative_path}")
        return lines


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _iter_png_files(root: Path) -> Iterable[Path]:
    if not root.is_dir():
        return ()
    return sorted(path for path in root.rglob("*.png") if path.is_file())


def hash_png_tree(root: Path = GALLERY_PNG_ROOT) -> dict[str, str]:
    """Return one ``{relative_posix_path: sha256}`` map for the PNG tree."""

    hashes: dict[str, str] = {}
    for path in _iter_png_files(root):
        relative_path = path.relative_to(root).as_posix()
        hashes[relative_path] = _sha256(path)
    return dict(sorted(hashes.items()))


def load_baseline(path: Path = BASELINE_PATH) -> dict[str, str]:
    """Load the committed baseline mapping from disk."""

    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Baseline file {path} must contain one JSON object.")
    files_section = payload.get("files", {})
    if not isinstance(files_section, dict):
        raise ValueError(f"Baseline file {path} is missing one 'files' object.")
    return {str(key): str(value) for key, value in files_section.items()}


def write_baseline(
    hashes: dict[str, str],
    path: Path = BASELINE_PATH,
    *,
    root_label: str = "docs/source/_static/capability_gallery",
) -> None:
    """Write the baseline JSON in deterministic order."""

    payload = {
        "format_version": 1,
        "algorithm": "sha256",
        "root": root_label,
        "files": dict(sorted(hashes.items())),
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def compare_hashes(
    baseline: dict[str, str],
    current: dict[str, str],
) -> DriftReport:
    """Compare two hash maps and return one ``DriftReport``."""

    baseline_keys = set(baseline)
    current_keys = set(current)
    common_keys = baseline_keys & current_keys

    mismatched = tuple(
        sorted(
            (key, baseline[key], current[key])
            for key in common_keys
            if baseline[key] != current[key]
        )
    )
    missing = tuple(sorted(baseline_keys - current_keys))
    added = tuple(sorted(current_keys - baseline_keys))
    return DriftReport(mismatched=mismatched, missing=missing, added=added)


def check_drift(
    *,
    gallery_root: Path = GALLERY_PNG_ROOT,
    baseline_path: Path = BASELINE_PATH,
) -> DriftReport:
    """Run one full drift check between the live PNG tree and the baseline."""

    return compare_hashes(load_baseline(baseline_path), hash_png_tree(gallery_root))


def update_baseline(
    *,
    gallery_root: Path = GALLERY_PNG_ROOT,
    baseline_path: Path = BASELINE_PATH,
) -> dict[str, str]:
    """Recompute the baseline from the live PNG tree and persist it."""

    hashes = hash_png_tree(gallery_root)
    write_baseline(hashes, baseline_path)
    return hashes


__all__ = [
    "BASELINE_PATH",
    "DriftReport",
    "GALLERY_PNG_ROOT",
    "check_drift",
    "compare_hashes",
    "hash_png_tree",
    "load_baseline",
    "update_baseline",
    "write_baseline",
]
