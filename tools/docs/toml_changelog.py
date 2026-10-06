"""Diff two field registries into a TOML changelog.

Usage: python -m tools.docs.toml_changelog OLD.json NEW.json OUT.json
An added or removed table is listed once, not field by field.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

WATCH = ("default", "profile", "required", "form", "unit")


def _norm(value):
    """An empty value and a missing one are the same: snapshots drop empty keys."""
    return None if value in (None, "", [], {}, False) else value


def parent(path: str) -> str:
    return path.rsplit(".", 1)[0] if "." in path else ""


def diff(old_doc: dict, new_doc: dict) -> dict:
    """Keys added, removed and changed between two registry payloads."""
    old, new = old_doc["nodes"], new_doc["nodes"]
    added = {p for p in new if p and p not in old}
    removed = {p for p in old if p and p not in new}
    changed = []
    for p in sorted(set(old) & set(new)):
        a, b = old[p], new[p]
        if a.get("kind") != "leaf" or b.get("kind") != "leaf":
            continue
        changes = {k: [a.get(k), b.get(k)] for k in WATCH if _norm(a.get(k)) != _norm(b.get(k))}
        if changes:
            changed.append({"path": p, "changes": changes})
    return {
        "from": old_doc["meta"].get("label"),
        "to": new_doc["meta"].get("label"),
        "added": sorted(p for p in added if parent(p) not in added),
        "removed": sorted(p for p in removed if parent(p) not in removed),
        "changed": changed,
    }


def main() -> None:
    out = diff(json.loads(Path(sys.argv[1]).read_text()), json.loads(Path(sys.argv[2]).read_text()))
    Path(sys.argv[3]).write_text(json.dumps(out, indent=1, ensure_ascii=False))
    print(
        f"added {len(out['added'])}, removed {len(out['removed'])}, changed {len(out['changed'])}"
    )


if __name__ == "__main__":
    main()
