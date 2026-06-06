"""Entry point: ``python -m tools.doc_config``."""

from __future__ import annotations

import argparse
import shutil
import tempfile
from pathlib import Path

from tools.doc_config.generate import REPO_ROOT, generate_all


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""

    parser = argparse.ArgumentParser(description="Generate HydroModPy config reference assets.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail if committed generated config-reference assets are stale.",
    )
    return parser


def changed_generated_paths(
    generated_paths: list[Path],
    *,
    generated_root: Path,
    repo_root: Path = REPO_ROOT,
) -> tuple[str, ...]:
    """Return generated repo-relative paths whose committed copy differs."""

    changed: list[str] = []
    for generated_path in generated_paths:
        rel = generated_path.resolve().relative_to(generated_root.resolve())
        repo_path = repo_root / rel
        if not repo_path.is_file() or repo_path.read_bytes() != generated_path.read_bytes():
            changed.append(rel.as_posix())
    return tuple(changed)


def check_generated_assets() -> int:
    """Generate config docs in a temp tree and compare them to committed files."""

    with tempfile.TemporaryDirectory(prefix="hmp-doc-config-check-") as tmp:
        generated_root = Path(tmp)
        generated_reference_dir = (
            generated_root / "docs" / "source" / "user_guide" / "config_reference"
        )
        committed_diagrams = (
            REPO_ROOT / "docs" / "source" / "user_guide" / "config_reference" / "_diagrams"
        )
        if committed_diagrams.is_dir():
            shutil.copytree(committed_diagrams, generated_reference_dir / "_diagrams")
        written = generate_all(
            output_dir=generated_reference_dir,
            static_dir=generated_root / "docs" / "source" / "_static",
        )
        changed = changed_generated_paths(written, generated_root=generated_root)

    if not changed:
        print("Generated config-reference assets are up to date.")
        return 0

    print("Generated config-reference assets are stale.")
    print("Run: python -m tools.doc_config")
    print("")
    print("Changed generated paths:")
    for path in changed:
        print(f"- {path}")
    return 1


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.check:
        return check_generated_assets()

    written = generate_all()
    print(f"Wrote {len(written)} files under {written[0].parent}")
    for path in written:
        print(f"  {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
