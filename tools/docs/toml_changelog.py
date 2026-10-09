"""Diff two field registries into a TOML changelog.

Usage: python -m tools.docs.toml_changelog OLD.json NEW.json OUT.json

An added or removed table is listed once, not field by field. A removed path
that a field of the new tree declares in ``renamed_from`` is listed as renamed,
not as removed. Pseudo-nodes (named instances such as ``flow.param.K``) are not
fields of the file and never count as a change. Nor do the keys of another file
(the catchment report file), which the project file does not hold.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

WATCH = ("default", "profile", "required", "form", "unit")
SNAPSHOT_KEYS = ("kind", *WATCH, "renamed_from")


def _norm(value):
    """An empty value and a missing one are the same: snapshots drop empty keys."""
    return None if value in (None, "", [], {}, False) else value


def parent(path: str) -> str:
    return path.rsplit(".", 1)[0] if "." in path else ""


def snapshot(payload: dict) -> dict:
    """The part of a registry payload a changelog compares, empty values dropped."""
    nodes = {}
    for path, node in payload["nodes"].items():
        if node.get("pseudo") or node.get("file"):
            continue
        nodes[path] = {k: node[k] for k in SNAPSHOT_KEYS if _norm(node.get(k)) is not None}
    return {"meta": dict(payload.get("meta", {})), "nodes": nodes}


def _renames(new: dict[str, dict]) -> dict[str, str]:
    """Old path -> new path, from the ``renamed_from`` the new fields declare."""
    out = {}
    for path, node in new.items():
        for old in node.get("renamed_from") or []:
            out[old] = path
    return out


def _renamed_to(path: str, renames: dict[str, str]) -> str | None:
    """The new path of an old one, through a rename of the path or of an ancestor."""
    probe = path
    while probe:
        if probe in renames:
            return renames[probe]
        probe = parent(probe)
    return None


def diff(old_doc: dict, new_doc: dict) -> dict:
    """Keys added, removed, renamed and changed between two registry payloads."""
    old = {p: n for p, n in old_doc["nodes"].items() if not (n.get("pseudo") or n.get("file"))}
    new = {p: n for p, n in new_doc["nodes"].items() if not (n.get("pseudo") or n.get("file"))}
    added = {p for p in new if p and p not in old}
    removed = {p for p in old if p and p not in new}
    renames = _renames(new)
    renamed = []
    for p in sorted(p for p in removed if parent(p) not in removed):
        target = _renamed_to(p, renames)
        if target is not None:
            renamed.append({"from": p, "to": target})
    renamed_from = {r["from"] for r in renamed}
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
        "removed": sorted(p for p in removed if parent(p) not in removed and p not in renamed_from),
        "renamed": renamed,
        "changed": changed,
    }


def history(docs: list[dict]) -> dict[str, Any]:
    """Every pair (older, newer) of a list of registry payloads, oldest first."""
    labels = [d["meta"].get("label") for d in docs]
    pairs = []
    for i, older in enumerate(docs):
        for newer in docs[i + 1 :]:
            pairs.append(diff(older, newer))
    return {"versions": labels, "pairs": pairs}


def main() -> None:
    out = diff(json.loads(Path(sys.argv[1]).read_text()), json.loads(Path(sys.argv[2]).read_text()))
    Path(sys.argv[3]).write_text(json.dumps(out, indent=1, ensure_ascii=False))
    print(
        f"added {len(out['added'])}, removed {len(out['removed'])}, "
        f"renamed {len(out['renamed'])}, changed {len(out['changed'])}"
    )


if __name__ == "__main__":
    main()
