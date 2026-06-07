"""Generate WebP siblings for the capability gallery PNG figures.

The doc gallery commits its rendered PNG bitmaps under
``docs/source/_static/capability_gallery/``. This helper produces a ``.webp``
copy next to every ``.png`` so the HTML build can emit ``<picture>`` blocks
with a WebP source and a PNG fallback. The conversion is idempotent and
skipped when the target ``.webp`` is newer than the PNG.

Usage::

    python -m tools.doc_gallery --convert-webp
    python -m tools.doc_gallery.png_to_webp  # equivalent direct entry
"""

from __future__ import annotations

import argparse
import logging
from collections.abc import Iterable
from pathlib import Path

from PIL import Image

from hydromodpy.core.logging import get_logger

LOGGER = get_logger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GALLERY_ROOTS: tuple[Path, ...] = (
    REPO_ROOT / "docs" / "source" / "_static" / "capability_gallery",
)
DEFAULT_QUALITY = 85
DEFAULT_METHOD = 6
# Stay under the pre-commit ``check-added-large-files`` threshold (1000 KB).
DEFAULT_MAX_BYTES = 950 * 1024
MIN_QUALITY = 30
QUALITY_STEP = 5


def _iter_png_files(roots: Iterable[Path]) -> Iterable[Path]:
    for root in roots:
        if not root.is_dir():
            continue
        yield from sorted(root.rglob("*.png"))


def convert_png_to_webp(
    png_path: Path,
    *,
    quality: int = DEFAULT_QUALITY,
    method: int = DEFAULT_METHOD,
    force: bool = False,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> Path | None:
    """Write a sibling ``.webp`` for ``png_path``.

    The encoder steps the quality down until the WebP fits under ``max_bytes``
    or the floor at :data:`MIN_QUALITY` is reached. Returns the produced WebP
    path, or ``None`` when the existing WebP is already up to date.
    """
    webp_path = png_path.with_suffix(".webp")
    if not force and webp_path.exists() and webp_path.stat().st_mtime >= png_path.stat().st_mtime:
        return None
    with Image.open(png_path) as image:
        if image.mode in {"P", "LA"}:
            image = image.convert("RGBA")
        is_rgba = image.mode == "RGBA"
        current_quality = quality
        while True:
            save_kwargs: dict[str, object] = {
                "quality": current_quality,
                "method": method,
            }
            if is_rgba:
                save_kwargs["lossless"] = False
            image.save(webp_path, format="WEBP", **save_kwargs)
            if webp_path.stat().st_size <= max_bytes or current_quality <= MIN_QUALITY:
                break
            current_quality = max(MIN_QUALITY, current_quality - QUALITY_STEP)
    return webp_path


def convert_gallery_pngs(
    roots: Iterable[Path] = DEFAULT_GALLERY_ROOTS,
    *,
    quality: int = DEFAULT_QUALITY,
    method: int = DEFAULT_METHOD,
    force: bool = False,
) -> list[Path]:
    """Convert every PNG under ``roots`` to a sibling WebP.

    Returns the list of WebP paths actually written this run.
    """
    written: list[Path] = []
    for png_path in _iter_png_files(roots):
        produced = convert_png_to_webp(png_path, quality=quality, method=method, force=force)
        if produced is not None:
            written.append(produced)
    return written


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--quality",
        type=int,
        default=DEFAULT_QUALITY,
        help="WebP quality (0-100, default %(default)s).",
    )
    parser.add_argument(
        "--method",
        type=int,
        default=DEFAULT_METHOD,
        help="WebP compression method (0-6, default %(default)s).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-encode even when the WebP is newer than the PNG.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        action="append",
        default=None,
        help="Override the gallery root (repeatable).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    roots = tuple(args.root) if args.root else DEFAULT_GALLERY_ROOTS
    produced = convert_gallery_pngs(
        roots,
        quality=args.quality,
        method=args.method,
        force=args.force,
    )
    LOGGER.info("Wrote %d WebP file(s).", len(produced))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
