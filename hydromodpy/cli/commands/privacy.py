"""``hmp privacy`` - remove a run for good with a purge certificate, and verify one."""

from __future__ import annotations

import argparse
import sys

from hydromodpy.cli.helpers import EXIT_CONFIG, EXIT_NOT_FOUND, EXIT_OK, exit_code_for

NAME: str = "privacy"
HELP: str = "Remove a run for good with a purge certificate, and verify one"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    sub = parser.add_subparsers(dest="privacy_command", metavar="<action>", required=True)

    purge = sub.add_parser(
        "purge",
        help="Remove a run for good (its name stays taken) and write a JSON purge certificate",
        epilog='Example:\n  hmp privacy purge ab12cd34 --reason "data withdrawn" -y',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    purge.add_argument("sim_ref", help="Run directory name, rel_dir, sim_id or unique prefix")
    purge.add_argument("--workspace", default=None, help="Project root")
    purge.add_argument(
        "--reason", default="unspecified", help="Free-form reason recorded in the certificate"
    )
    purge.add_argument("-y", "--yes", action="store_true", help="Skip the interactive prompt")
    purge.add_argument(
        "--archive-pii",
        action="store_true",
        help="Also write the snapshot to a sibling 0o600 archive",
    )

    verify = sub.add_parser(
        "verify",
        help="Verify a purge certificate JSON",
        epilog="Example:\n  hmp privacy verify purge-certificate.json --strict",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
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
    from hydromodpy.cli._workers.privacy import purge_simulation

    if not args.yes:
        if not sys.stdin.isatty():
            print("Refusing to purge without -y in non-interactive mode.", file=sys.stderr)
            sys.exit(EXIT_CONFIG)
        try:
            resp = input(f"Purge {args.sim_ref!r} for good? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.", file=sys.stderr)
            sys.exit(EXIT_CONFIG)
        if resp not in {"y", "yes"}:
            print("Aborted.", file=sys.stderr)
            sys.exit(EXIT_CONFIG)

    try:
        result = purge_simulation(
            args.sim_ref,
            workspace=args.workspace,
            reason=args.reason,
            archive_pii=args.archive_pii,
        )
    except Exception as exc:  # noqa: BLE001 - map resolver, in-use and IO errors
        print(str(exc), file=sys.stderr)
        sys.exit(exit_code_for(exc))

    print(f"Purged {result['rel_dir']} ({result['sim_id']}); its name stays taken")
    for path in result["removed_paths"]:
        print(f"  removed: {path}")
    print(f"Certificate: {result['certificate']}")
    if result["archive"]:
        print(f"PII archive (0o600): {result['archive']}")
    sys.exit(EXIT_OK)


def _cmd_verify(args: argparse.Namespace) -> None:
    from hydromodpy.cli._workers.privacy import verify_purge_certificate

    try:
        result = verify_purge_certificate(args.certificate, strict=args.strict)
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
