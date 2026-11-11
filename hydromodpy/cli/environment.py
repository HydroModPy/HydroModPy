"""The CLI arguments that build an :class:`~hydromodpy.project.environment.Environment`.

``hmp run``, ``calibrate``, ``spinup``, ``export``, ``data get`` and
``campaign array`` share these three options. The command builds the object
and hands it to the verb it wraps; the library reads no environment variable
for this.

The options are ``--credentials``, ``--allow-host`` and ``--max-download-bytes``.
``add_environment_arguments(parser)`` registers them, ``environment_from_args(args)``
builds the ``Environment``, and ``environment_flags_of(args)`` serializes them onto the
command line of a launched case. The environment is never written into the request.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from hydromodpy.cli.exit_codes import EXIT_USAGE, refuse
from hydromodpy.core.runtime.bounds import DEFAULT_MAX_DOWNLOAD_BYTES, Bounds
from hydromodpy.project.environment import Environment


def add_environment_arguments(parser: argparse.ArgumentParser) -> None:
    """Register ``--credentials``, ``--allow-host`` and ``--max-download-bytes``."""
    parser.add_argument(
        "--credentials",
        type=Path,
        default=None,
        metavar="PATH",
        help=(
            "Credentials file outside the project, read by the verb. Default: "
            "<state home>/credentials.toml"
        ),
    )
    parser.add_argument(
        "--allow-host",
        action="append",
        default=[],
        metavar="HOST",
        help=(
            "Host a download may reach, exact name, repeatable. Default: no "
            "list, the bounds allow every public host"
        ),
    )
    parser.add_argument(
        "--max-download-bytes",
        type=int,
        default=None,
        metavar="N",
        help="Raise the byte ceiling of this call past its 2 GiB default",
    )
    parser.set_defaults(allow_host=[])


def environment_from_args(args: argparse.Namespace) -> Environment:
    """Build the :class:`Environment` of a verb from the three options.

    The command registered :func:`add_environment_arguments` first, so the
    three attributes of ``args`` always exist. ``--credentials`` absent reads
    the default path of :meth:`Environment.default`, where an absent file is
    an answer and not a refusal. ``--allow-host`` repeats, absent meaning the
    default of ``None``. A ceiling of zero or less refuses at once with
    :data:`EXIT_USAGE`, so it never stands for the default.
    """
    if args.max_download_bytes is not None and args.max_download_bytes <= 0:
        refuse(
            "--max-download-bytes is a byte count: a value of 0 or less is not a "
            f"ceiling. Got {args.max_download_bytes}.",
            EXIT_USAGE,
        )
    bounds = Bounds(
        allowed_hosts=frozenset(args.allow_host) if args.allow_host else None,
        max_download_bytes=DEFAULT_MAX_DOWNLOAD_BYTES
        if args.max_download_bytes is None
        else int(args.max_download_bytes),
    )
    if args.credentials is None:
        return Environment(credentials=Environment.default().credentials, bounds=bounds)
    credentials = Path(args.credentials).expanduser().resolve()
    return Environment(credentials=credentials, bounds=bounds)


def environment_flags_of(args: argparse.Namespace) -> tuple[str, ...]:
    """Return ``--credentials``, ``--allow-host`` and ``--max-download-bytes`` as argv.

    A launched case carries the same three options on its own command line:
    the worker of a case is ``hmp run`` again and builds the same
    :class:`Environment` from what it reads there. The launcher passes only
    the options its caller named, empty when none of the three is named, so
    the command line of a case stays what it was. A ``--credentials`` path is
    resolved before it crosses, because the worker runs from the folder of
    its case and would read a relative path elsewhere.
    """
    flags: list[str] = []
    if args.credentials is not None:
        flags += ["--credentials", str(Path(args.credentials).expanduser().resolve())]
    for host in args.allow_host:
        flags += ["--allow-host", host]
    if args.max_download_bytes is not None:
        flags += ["--max-download-bytes", str(args.max_download_bytes)]
    return tuple(flags)


__all__ = [
    "add_environment_arguments",
    "environment_flags_of",
    "environment_from_args",
]
