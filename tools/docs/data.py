"""Write every data file the documentation reads, from the code and the tests.

Usage: python -m tools.docs.data OUT_DIR [--label TEXT]

The Sphinx extension calls ``write_all`` at builder-inited. The files are build
products: git ignores them.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from packaging.version import Version

from tools.docs import api_registry, field_registry, tests_index, toml_changelog

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOTS = Path(__file__).with_name("snapshots")


def latest_snapshot() -> Path | None:
    """The field snapshot of the newest release, or None."""
    snaps = list(SNAPSHOTS.glob("fields-*.json"))
    if not snaps:
        return None
    return max(snaps, key=lambda p: Version(p.stem.removeprefix("fields-")))


def write_all(out_dir: Path, label: str = "") -> dict[str, Path]:
    """Build the registry, the API index, the test index and the TOML changelog."""
    out_dir.mkdir(parents=True, exist_ok=True)
    registry, gates = field_registry.build_payload(label)
    payloads = {
        "registry": registry,
        "gates": gates,
        "api": api_registry.build(registry["nodes"]),
        "tests": tests_index.build(ROOT),
    }
    snap = latest_snapshot()
    if snap is not None:
        payloads["changelog"] = toml_changelog.diff(json.loads(snap.read_text()), registry)
    paths = {}
    for name, payload in payloads.items():
        path = out_dir / f"{name}.json"
        path.write_text(json.dumps(payload, indent=1, ensure_ascii=False, default=str))
        paths[name] = path
    return paths


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("out_dir")
    ap.add_argument("--label", default="")
    args = ap.parse_args()
    for name, path in write_all(Path(args.out_dir), args.label).items():
        print(f"{name}: {path}")


if __name__ == "__main__":
    main()
