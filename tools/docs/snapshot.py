"""Build the field snapshot of a released version, from its git tag.

Usage: python -m tools.docs.snapshot TAG [TAG ...] [--out DIR]

The package of the tag is exported with ``git archive`` into a cache folder, and
the field registry of this tree is run against it in a separate process, so the
snapshot describes the models of the tag. It is written to
``tools/docs/snapshots/fields-<version>.json``, ``<version>`` being the tag
without its leading ``v``. The changes page compares these snapshots.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from tools.docs.toml_changelog import snapshot

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOTS = Path(__file__).with_name("snapshots")
REGISTRY_SCRIPT = Path(__file__).with_name("field_registry.py")


def version_of(tag: str) -> str:
    return tag[1:] if tag.startswith("v") else tag


def export_tree(tag: str, dest: Path) -> None:
    """Write the ``hydromodpy`` package of ``tag`` under ``dest``."""
    archive = subprocess.run(
        ["git", "-C", str(ROOT), "archive", "--format=tar", tag, "hydromodpy"],
        check=True,
        capture_output=True,
    ).stdout
    subprocess.run(["tar", "-x", "-C", str(dest)], input=archive, check=True)


def registry_of(tree: Path, label: str) -> dict:
    """The registry payload of the package exported under ``tree``.

    The script runs from ``tree`` with ``PYTHONPATH=tree``, so ``import
    hydromodpy`` reads the tag and not this checkout.
    """
    out = tree / "registry.json"
    env = {**os.environ, "PYTHONPATH": str(tree)}
    subprocess.run(
        [sys.executable, str(REGISTRY_SCRIPT), str(out), "--label", label],
        cwd=tree,
        env=env,
        check=True,
    )
    return json.loads(out.read_text())


def build(tag: str, out_dir: Path = SNAPSHOTS) -> Path:
    """Write the snapshot of ``tag`` and return its path."""
    label = version_of(tag)
    cache = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "hmp-snapshots"
    cache.mkdir(parents=True, exist_ok=True)
    tree = Path(tempfile.mkdtemp(prefix=f"{label}-", dir=cache))
    try:
        export_tree(tag, tree)
        payload = registry_of(tree, label)
    finally:
        shutil.rmtree(tree, ignore_errors=True)
    snap = snapshot(payload)
    snap["meta"] = {"label": label, "source": f"tag {tag}, registry of HydroModPyConfig"}
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"fields-{label}.json"
    path.write_text(json.dumps(snap, separators=(",", ":"), sort_keys=True, ensure_ascii=False))
    return path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("tags", nargs="+")
    ap.add_argument("--out", type=Path, default=SNAPSHOTS)
    args = ap.parse_args()
    for tag in args.tags:
        path = build(tag, args.out)
        print(f"{tag}: {path} ({len(json.loads(path.read_text())['nodes'])} paths)")


if __name__ == "__main__":
    main()
