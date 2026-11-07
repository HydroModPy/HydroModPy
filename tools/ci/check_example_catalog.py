"""Check that ``hydromodpy/project/examples/catalog.toml`` matches the files of the tree.

Run it from a checkout of the commit to release. ``hmp example add`` fetches each
file at the tag of the installed version and compares it to the sha256 of the
catalog, so a catalog that drifted from the tree makes every download fail. The
script hashes each file the catalog names and exits 1 on a missing file, a size
or a sha256 that differs.
"""

from __future__ import annotations

import hashlib
import sys
import tomllib
from pathlib import Path

CATALOG = Path("hydromodpy/project/examples/catalog.toml")


def main(root: Path = Path()) -> int:
    catalog = tomllib.loads((root / CATALOG).read_text(encoding="utf-8"))
    problems: list[str] = []
    checked = 0
    for example in catalog.get("example", []):
        files = [*example.get("file", []), *example.get("data", []), *example.get("station", [])]
        for item in files:
            if not isinstance(item, dict) or "repo_path" not in item:
                continue
            checked += 1
            path = root / item["repo_path"]
            if not path.is_file():
                problems.append(f"missing: {item['repo_path']}")
                continue
            payload = path.read_bytes()
            if hashlib.sha256(payload).hexdigest() != item["sha256"]:
                problems.append(f"sha256 differs: {item['repo_path']}")
            elif len(payload) != item["size"]:
                problems.append(f"size differs: {item['repo_path']}")
    for line in problems:
        print(line, file=sys.stderr)
    print(f"{checked} files checked, {len(problems)} problem(s)")
    if checked == 0:
        print("the catalog names no file", file=sys.stderr)
        return 1
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
