"""
Generate a TOML configuration template from the command line.

Usage:
    python -m hydromodpy.config my_config.toml
    python -m hydromodpy.config --profile user --modules geographic
    python -m hydromodpy.config --profile expert
    python -m hydromodpy.config --list-modules
"""

import sys
import argparse
from pathlib import Path


def main():
    from .generate_toml import generate_toml, available_modules, PROFILES

    parser = argparse.ArgumentParser(
        description="Generate a TOML configuration template for HydroModPy",
    )
    parser.add_argument(
        "output",
        nargs="?",
        help="Output file path (prints to stdout if not provided)",
    )
    parser.add_argument(
        "--profile",
        choices=list(PROFILES.keys()),
        default="expert",
        help="Parameter visibility level (default: expert)",
    )
    parser.add_argument(
        "--modules",
        nargs="+",
        help="Module sections to include (default: all). Use --list-modules to see available.",
    )
    parser.add_argument(
        "--list-modules",
        action="store_true",
        help="List available module names and exit",
    )
    args = parser.parse_args()

    if args.list_modules:
        for name in available_modules():
            print(name)
        return

    # If the user passed a directory, generate a default filename inside it
    if args.output and Path(args.output).is_dir():
        args.output = str(Path(args.output) / "config.toml")

    content = generate_toml(
        output_path=args.output,
        modules=args.modules,
        profile=args.profile,
    )

    if args.output:
        print(f"Written to: {Path(args.output).resolve()}", file=sys.stderr)
    else:
        print(content)


if __name__ == "__main__":
    main()
