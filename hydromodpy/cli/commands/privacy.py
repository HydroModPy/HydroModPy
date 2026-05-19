"""``hmp privacy`` - thin wrappers around :func:`hydromodpy.purge_simulation` and ``verify_purge_certificate``."""

from __future__ import annotations

import argparse
import sys

from hydromodpy.cli.helpers import EXIT_CONFIG, EXIT_NOT_FOUND, EXIT_OK

NAME: str = "privacy"
HELP: str = "Privacy-preserving operations (purge a sim with audit certificate)"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    sub = parser.add_subparsers(dest="privacy_command")

    purge = sub.add_parser("purge", help="Hard-delete a simulation + emit a JSON purge certificate")
    purge.add_argument("sim_ref", help="Full sim_id, unique prefix, or simulation name")
    purge.add_argument("--workspace", default=None, help="Project catalog root")
    purge.add_argument(
        "--reason", default="unspecified", help="Free-form reason recorded in the certificate"
    )
    purge.add_argument("-y", "--yes", action="store_true", help="Skip the interactive prompt")
    purge.add_argument(
        "--archive-pii",
        action="store_true",
        help="Also write the snapshot to a sibling 0o600 archive",
    )

    verify = sub.add_parser("verify", help="Verify a purge certificate JSON")
    verify.add_argument("certificate", help="Path to a purge certificate JSON file")
    verify.add_argument("--strict", action="store_true", help="Require POSIX 0o600 permissions")

    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    sub = getattr(args, "privacy_command", None)
    if sub == "purge":
        _cmd_purge(args)
        return
    if sub == "verify":
        _cmd_verify(args)
        return
    print("Usage: hmp privacy {purge|verify} [options]", file=sys.stderr)
    sys.exit(EXIT_CONFIG)


def _cmd_purge(args: argparse.Namespace) -> None:
    import hydromodpy as hmp

    if not args.yes:
        if not sys.stdin.isatty():
            print("Refusing to purge without -y in non-interactive mode.", file=sys.stderr)
            sys.exit(EXIT_CONFIG)
        try:
            resp = input(f"Purge simulation {args.sim_ref!r}? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.", file=sys.stderr)
            sys.exit(EXIT_CONFIG)
        if resp not in {"y", "yes"}:
            print("Aborted.", file=sys.stderr)
            sys.exit(EXIT_CONFIG)

    try:
        result = hmp.purge_simulation(
            args.sim_ref,
            workspace=args.workspace,
            reason=args.reason,
            archive_pii=args.archive_pii,
        )
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)

    print(f"Purged simulation {result['sim_id']}")
    for path in result["removed_paths"]:
        print(f"  removed: {path}")
    print(f"Certificate: {result['certificate']}")
    if result["archive"]:
        print(f"PII archive (0o600): {result['archive']}")
    sys.exit(EXIT_OK)


def _cmd_verify(args: argparse.Namespace) -> None:
    import hydromodpy as hmp

    try:
        result = hmp.verify_purge_certificate(args.certificate, strict=args.strict)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(EXIT_NOT_FOUND)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(EXIT_CONFIG)

    if not result["permissions_ok"] and result["permissions"]:
        print(
            f"WARNING: certificate permissions {result['permissions']}, expected 0o600",
            file=sys.stderr,
        )
    payload = result["payload"]
    print(f"OK: certificate {result['certificate']} verifies")
    print(f"  sim_id      : {payload['sim_id']}")
    print(f"  timestamp   : {payload['timestamp_utc']}")
    print(f"  operator    : {payload['operator']}")
    print(f"  sha256      : {payload['sha256_snapshot'][:16]}...")
    sys.exit(EXIT_OK)


__all__ = ("NAME", "HELP", "register", "run")
