"""Post-process the multi-version HTML tree before the GitHub Pages deploy.

Two jobs, both on the built output only. The source assets are never touched,
so the capability-gallery SHA-256 gate and the nightly refresh stay valid.

1. Write a pydata-theme ``switcher.json`` listing the deployed versions.
2. Shrink the heavy capability-gallery PNG fallbacks. The served format is
   webp (the ``gallery-figure`` directive emits ``<picture>`` with a webp
   source); the PNG is only the fallback, so a smaller PNG keeps the published
   site under the GitHub Pages ~1 GB limit across versions without any visible
   change.

Usage::

    python tools/docs_pages_postbuild.py docs/build/html https://docs.hydromodpy.fr
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

# Top-level entries of the merged tree that are not version folders.
_SKIP_TOP = {
    "_static",
    "_images",
    "_sources",
    "_downloads",
    "_sphinx_design_static",
    "_plantuml",
    "_modules",
}
# Stable trunk first, then dev, then tags sorted by name.
_VERSION_ORDER = {"main": 0, "dev": 1}
_MAX_WIDTH = 1920
_MIN_BYTES = 150_000


def discover_versions(html_root: Path) -> list[str]:
    """Return the version folders at the root of the merged site."""
    versions = [
        path.name
        for path in html_root.iterdir()
        if path.is_dir()
        and not path.name.startswith("_")
        and path.name not in _SKIP_TOP
        and (path / "index.html").exists()
    ]
    versions.sort(key=lambda name: (_VERSION_ORDER.get(name, 2), name))
    return versions


def write_switcher(html_root: Path, base_url: str, versions: list[str]) -> None:
    """Write a pydata-sphinx-theme switcher.json at the site root."""
    base = base_url.rstrip("/")
    entries: list[dict[str, object]] = []
    for name in versions:
        entry: dict[str, object] = {"name": name, "version": name, "url": f"{base}/{name}/"}
        if name == "main":
            entry["preferred"] = True
        entries.append(entry)
    (html_root / "switcher.json").write_text(json.dumps(entries, indent=2))
    print(f"switcher.json -> {[str(entry['version']) for entry in entries]}")


def shrink_gallery_pngs(html_root: Path) -> None:
    """Downscale and palette-compress capability-gallery PNG fallbacks in place."""
    try:
        from PIL import Image
    except ImportError:
        print("Pillow missing, skipping PNG shrink")
        return

    saved = 0
    count = 0
    for png in html_root.rglob("*.png"):
        if "capability_gallery" not in png.parts:
            continue
        size = png.stat().st_size
        if size < _MIN_BYTES:
            continue
        try:
            image = Image.open(png)
            width, height = image.size
            if width > _MAX_WIDTH:
                new_height = round(height * _MAX_WIDTH / width)
                image = image.resize((_MAX_WIDTH, new_height), Image.LANCZOS)
            if image.mode != "P":
                image = image.convert("RGBA").convert("P", palette=Image.ADAPTIVE, colors=256)
            buffer = io.BytesIO()
            image.save(buffer, format="PNG", optimize=True)
            if buffer.getbuffer().nbytes < size:
                png.write_bytes(buffer.getvalue())
                saved += size - buffer.getbuffer().nbytes
                count += 1
        except Exception as exc:  # noqa: BLE001 - never fail the deploy on one bad image
            print(f"skip {png}: {exc}")
    print(f"shrunk {count} gallery PNGs, saved {saved / 1e6:.1f} MB")


def _order(versions: list[str]) -> list[str]:
    return sorted(versions, key=lambda name: (_VERSION_ORDER.get(name, 2), name))


def main() -> int:
    argv = sys.argv[1:]
    versions_csv: str | None = None
    positional: list[str] = []
    index = 0
    while index < len(argv):
        if argv[index] == "--versions" and index + 1 < len(argv):
            versions_csv = argv[index + 1]
            index += 2
        else:
            positional.append(argv[index])
            index += 1

    html_root = Path(positional[0] if positional else "docs/build/html")
    base_url = positional[1] if len(positional) > 1 else "https://docs.hydromodpy.fr"
    if not html_root.is_dir():
        print(f"no html dir at {html_root}", file=sys.stderr)
        return 1

    # Incremental deploy passes the full version set explicitly (only one version
    # is built locally); the polyversion full build discovers them from the tree.
    if versions_csv is not None:
        versions = _order([item.strip() for item in versions_csv.split(",") if item.strip()])
    else:
        versions = discover_versions(html_root)

    write_switcher(html_root, base_url, versions)
    shrink_gallery_pngs(html_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
