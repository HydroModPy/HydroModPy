"""``hmp viz serve`` - launch the Streamlit-based HydroModPy UI."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from hydromodpy.cli.helpers import EXIT_CONFIG, EXIT_NOT_FOUND

NAME: str = "serve"
HELP: str = "Launch the Streamlit config / inspection UI"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    parser.add_argument(
        "--port",
        type=int,
        default=8501,
        help="Port to bind the Streamlit server on (default: 8501)",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Optional TOML config to preload in the UI",
    )
    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    try:
        import streamlit  # noqa: F401
    except ImportError:
        print(
            "streamlit is required for 'hmp viz serve'. Install it with: pip install streamlit",
            file=sys.stderr,
        )
        sys.exit(EXIT_CONFIG)

    target = Path(__file__).resolve().parents[3] / "reporting" / "streamlit_config.py"
    if not target.is_file():
        print(f"Streamlit entry point missing: {target}", file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)

    cmd = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(target),
        "--server.port",
        str(args.port),
    ]
    if args.config is not None:
        cmd.extend(["--", "--load", str(Path(args.config).expanduser().resolve())])
    print(f"Launching Streamlit on http://localhost:{args.port}", file=sys.stderr)
    subprocess.run(cmd, check=False)
