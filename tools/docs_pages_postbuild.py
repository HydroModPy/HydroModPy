"""Prepare one docs deploy: the files of the site root and the versions it keeps.

The site keeps main, dev and the stable release tags (vX.Y or vX.Y.Z); it does
not publish pre-releases (a, b, rc). For one built version this script:

- drops the source maps the theme ships (about 3 MB, read only by browser
  developer tools);
- writes the root files: ``switcher.json`` (the kept versions, main preferred),
  an ``index.html`` that sends to main, a ``404.html`` that offers the same page
  in main, and ``robots.txt``;
- lists the version folders of the site that are not kept, one per line, so the
  deploy removes them.

Usage::

    python tools/docs_pages_postbuild.py --version-dir site/main --root-dir site-root \
        --existing main,dev,v1.0 --remove-list remove.txt
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

BASE_URL = "https://docs.hydromodpy.fr"
_STABLE_TAG = re.compile(r"v\d+\.\d+(\.\d+)?")
# Stable trunk first, then dev, then tags sorted by name.
_VERSION_ORDER = {"main": 0, "dev": 1}

_INDEX = """<!doctype html><meta charset="utf-8">
<meta http-equiv="refresh" content="0; url=./main/">
<link rel="canonical" href="{base}/main/">
<title>HydroModPy documentation</title>
<a href="./main/">HydroModPy documentation</a>
"""

_NOT_FOUND = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>Page not found - HydroModPy documentation</title>
<style>
body {{ font-family: system-ui, sans-serif; max-width: 40rem; margin: 4rem auto; padding: 0 1rem;
       line-height: 1.5; color: #1f2933; background: #fff; }}
a {{ color: #0a6d80; }}
@media (prefers-color-scheme: dark) {{
  body {{ color: #e5e7eb; background: #14181e; }}
  a {{ color: #5ec4d6; }}
}}
</style>
</head>
<body>
<h1>Page not found</h1>
<p>This address may come from an older version of the HydroModPy documentation,
which was reorganised in 2026, or from a pre-release that is no longer published.</p>
<p id="same" hidden>Try <a id="same-link" href="{base}/main/">the same page in the current
documentation</a>.</p>
<ul>
<li><a href="{base}/main/">Home of the current documentation</a></li>
<li><a href="{base}/main/search.html">Search the documentation</a></li>
<li><a href="{base}/main/reference/parameters/explorer.html">Find a TOML parameter</a></li>
</ul>
<script>
(function () {{
  var parts = location.pathname.split("/").filter(Boolean);
  if (!parts.length || parts[0] === "main") return;
  var rest = (parts[0] === "dev" || /^v\\d/.test(parts[0])) ? parts.slice(1) : parts;
  document.getElementById("same-link").href = "{base}/main/" + rest.join("/");
  document.getElementById("same").hidden = false;
}})();
</script>
</body>
</html>
"""

_ROBOTS = """User-agent: *
Allow: /
Sitemap: {base}/main/sitemap.xml
"""


def is_version(name: str) -> bool:
    """A folder of the site root that holds a documentation version."""
    return name in _VERSION_ORDER or bool(re.match(r"v\d", name))


def is_kept(name: str) -> bool:
    """main, dev and the stable release tags; never a pre-release."""
    return name in _VERSION_ORDER or bool(_STABLE_TAG.fullmatch(name))


def order(versions: list[str]) -> list[str]:
    return sorted(versions, key=lambda name: (_VERSION_ORDER.get(name, 2), name))


def write_switcher(root_dir: Path, versions: list[str], base_url: str = BASE_URL) -> None:
    """Write a pydata-sphinx-theme switcher.json with main preferred."""
    entries: list[dict[str, object]] = []
    for name in versions:
        entry: dict[str, object] = {"name": name, "version": name, "url": f"{base_url}/{name}/"}
        if name == "main":
            entry["preferred"] = True
        entries.append(entry)
    (root_dir / "switcher.json").write_text(json.dumps(entries, indent=2) + "\n")
    print(f"switcher.json -> {versions}")


def write_root_pages(root_dir: Path, base_url: str = BASE_URL) -> None:
    """Write index.html, 404.html and robots.txt of the site root."""
    (root_dir / "index.html").write_text(_INDEX.format(base=base_url))
    (root_dir / "404.html").write_text(_NOT_FOUND.format(base=base_url))
    (root_dir / "robots.txt").write_text(_ROBOTS.format(base=base_url))


def drop_source_maps(version_dir: Path) -> None:
    """Remove the ``.map`` files of the built version."""
    maps = list(version_dir.rglob("*.map"))
    for path in maps:
        path.unlink()
    print(f"removed {len(maps)} source maps")


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare one docs deploy.")
    parser.add_argument("--version-dir", type=Path, required=True)
    parser.add_argument("--root-dir", type=Path, required=True)
    parser.add_argument("--existing", default="", help="comma-separated folders of the site")
    parser.add_argument("--remove-list", type=Path, required=True)
    parser.add_argument("--base-url", default=BASE_URL)
    args = parser.parse_args()

    version = args.version_dir.name
    existing = [name.strip() for name in args.existing.split(",") if name.strip()]
    kept = order(sorted({name for name in existing if is_kept(name)} | {version}))
    remove = [name for name in existing if is_version(name) and not is_kept(name)]

    drop_source_maps(args.version_dir)
    args.root_dir.mkdir(parents=True, exist_ok=True)
    write_switcher(args.root_dir, kept, args.base_url)
    write_root_pages(args.root_dir, args.base_url)
    args.remove_list.write_text("".join(f"{name}\n" for name in remove))
    print(f"versions to remove: {remove}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
