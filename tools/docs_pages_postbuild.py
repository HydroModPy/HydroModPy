"""Post-process the built HTML tree before the GitHub Pages deploy.

Write a pydata-theme ``switcher.json`` listing the deployed versions so the
version dropdown can offer v1 alongside the development versions (main, dev).
The source assets are never touched.

Usage::

    python tools/docs_pages_postbuild.py site https://hydromodpy.github.io --versions main,dev,v1
"""

from __future__ import annotations

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
# Stable trunk first, then dev, then everything else sorted by name.
_VERSION_ORDER = {"main": 0, "dev": 1}


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

    html_root = Path(positional[0] if positional else "site")
    base_url = positional[1] if len(positional) > 1 else "https://hydromodpy.github.io"
    if not html_root.is_dir():
        print(f"no html dir at {html_root}", file=sys.stderr)
        return 1

    # Incremental deploy passes the full version set explicitly (only one version
    # is built locally); without it, discover the folders already in the tree.
    if versions_csv is not None:
        versions = _order([item.strip() for item in versions_csv.split(",") if item.strip()])
    else:
        versions = discover_versions(html_root)

    write_switcher(html_root, base_url, versions)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
