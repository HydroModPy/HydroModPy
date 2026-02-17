"""
Generate a TOML configuration template from the command line.

Usage:
    python -m hydromodpy.config my_config.toml
    python -m hydromodpy.config                   # prints to stdout
"""

import sys
import argparse
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(
        description="Generate a TOML configuration template for HydroModPy",
    )
    parser.add_argument(
        "output",
        nargs="?",
        help="Output file path (prints to stdout if not provided)",
    )
    args = parser.parse_args()

    from .generate_toml import generate_toml

    if args.output:
        generate_toml(output_path=args.output)
        print(f"Written to: {Path(args.output).resolve()}", file=sys.stderr)
    else:
        print(generate_toml())


if __name__ == "__main__":
    main()
