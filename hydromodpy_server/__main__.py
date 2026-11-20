"""``python -m hydromodpy_server``: serve the verbs of HydroModPy over HTTP."""

from __future__ import annotations

import argparse
import json
import signal
import sys
import threading
from pathlib import Path
from typing import NoReturn

import hydromodpy as hmp
from hydromodpy.core.exceptions import ConfigError, HydroModPyError
from hydromodpy.core.runtime.bounds import Bounds
from hydromodpy.core.runtime.image import image_of
from hydromodpy_server.app import Settings, serve

WARM = Path(__file__).with_name("warm.json")


def refuse(message: str) -> NoReturn:
    """Say why the server does not start, and stop with the usage code."""
    print(f"hydromodpy_server: {message}", file=sys.stderr)
    raise SystemExit(2)


def prepare(argv: list[str] | None = None) -> tuple[Settings, str, int, list[Path]]:
    """Read the options and refuse a start that would be wrong. Return what ``main`` serves."""
    parser = argparse.ArgumentParser(prog="python -m hydromodpy_server")
    parser.add_argument("--root", type=Path, required=True, help="folder of the spaces")
    parser.add_argument("--credentials-dir", type=Path, help="one <organisation>.toml per space")
    parser.add_argument("--allow-host", action="append", help="host a call may fetch from")
    parser.add_argument("--max-download-bytes", type=int, default=Bounds().max_download_bytes)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765, help="0 takes a free port")
    parser.add_argument("--warm", type=Path, action="append", help="document to check first")
    args = parser.parse_args(argv)
    root = args.root.expanduser().resolve()
    if not root.is_dir():
        refuse(f"the root {root} does not exist")
    credentials = None
    if args.credentials_dir is not None:
        credentials = args.credentials_dir.expanduser().resolve()
        if credentials == root or root in credentials.parents:
            refuse(
                f"the credentials folder {credentials} is under the root {root}: "
                "a client would read the identifiers of another organisation"
            )
        if not credentials.is_dir():
            refuse(f"the credentials folder {credentials} does not exist")
    try:
        image = image_of()
        bounds = Bounds(
            allowed_hosts=None if args.allow_host is None else frozenset(args.allow_host),
            max_download_bytes=args.max_download_bytes,
        )
    except (ConfigError, HydroModPyError) as exc:
        refuse(str(exc))
    if image and "digest" not in image:
        refuse(
            f"this server runs in the image {image['tag']} without HMP_IMAGE_DIGEST: "
            "start the container with -e HMP_IMAGE_DIGEST=<digest>, "
            "so each run seals the image it ran in"
        )
    warm = args.warm or [WARM]
    for file in warm:
        if not file.is_file():
            refuse(f"the warm-up file {file} does not exist")
    return Settings(root, credentials, bounds), args.host, args.port, warm


def clean_inbox(root: Path) -> None:
    """Remove the half-written uploads a stopped server left in ``<root>/.inbox``."""
    for part in (root / ".inbox").glob("*.part"):
        part.unlink(missing_ok=True)


def warm_up(files: list[Path], base: Path) -> None:
    """Check each document once, then an empty one, so the first call of a client is warm."""
    for file in files:
        document = json.loads(file.read_text("utf-8")) if file.suffix == ".json" else file
        hmp.check(document, base=base)
    hmp.check({}, base=base)


def main(argv: list[str] | None = None) -> None:
    settings, host, port, warm = prepare(argv)
    clean_inbox(settings.root)
    warm_up(warm, settings.root)
    server = serve(settings, host, port)
    print(f"serving on http://{host}:{server.server_address[1]}", flush=True)
    signal.signal(signal.SIGTERM, lambda *_: threading.Thread(target=server.shutdown).start())
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass  # the usual way to stop a server from a terminal
    finally:
        server.server_close()
        settings.stop_jobs()


if __name__ == "__main__":
    main()
