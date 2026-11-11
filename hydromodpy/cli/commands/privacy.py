"""``hmp privacy`` - remove a run for good with a purge certificate, and verify one."""

from __future__ import annotations

import argparse
import sys

from hydromodpy.cli.conventions import (
    confirm_parser,
    dry_run_parser,
    format_parser,
    workspace_parser,
)
from hydromodpy.cli.exit_codes import EXIT_CONFIG, confirm, refuse
from hydromodpy.cli.output import emit
from hydromodpy.cli.refs import project_root_of

NAME: str = "privacy"
HELP: str = "Remove a run for good with a purge certificate, and verify one"


def register(subparsers) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(NAME, help=HELP)
    sub = parser.add_subparsers(dest="privacy_command", metavar="<action>", required=True)

    purge = sub.add_parser(
        "purge",
        parents=[workspace_parser(), confirm_parser(), dry_run_parser(), format_parser()],
        help="Remove a run for good (its name stays taken) and write a JSON purge certificate",
        epilog='Example:\n  hmp privacy purge ab12cd34 --reason "data withdrawn" -y',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    purge.add_argument("sim_ref", help="Run directory name, rel_dir, sim_id or unique prefix")
    purge.add_argument(
        "--reason", default="unspecified", help="Free-form reason recorded in the certificate"
    )
    purge.add_argument(
        "--archive-pii",
        action="store_true",
        help="Also write the snapshot to a sibling 0o600 archive",
    )

    verify = sub.add_parser(
        "verify",
        parents=[workspace_parser(reads_none=True), format_parser()],
        help="Verify a purge certificate JSON",
        epilog="Example:\n  hmp privacy verify purge-certificate.json --strict",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    verify.add_argument("certificate", help="Path to a purge certificate JSON file")
    verify.add_argument("--strict", action="store_true", help="Require POSIX 0o600 permissions")

    parser.set_defaults(_handler=run)
    return parser


def run(args: argparse.Namespace) -> None:
    {"purge": _cmd_purge, "verify": _cmd_verify}[args.privacy_command](args)


def _cmd_purge(args: argparse.Namespace) -> None:
    from hydromodpy.results.catalog.discovery import resolve_rel_dir
    from hydromodpy.results.catalog.privacy import purge_simulation

    if args.dry_run:
        rel_dir = resolve_rel_dir(project_root_of(args), args.sim_ref, unambiguous=True)
        emit(
            args,
            "privacy purge",
            {"applied": False, "rel_dir": rel_dir},
            table=lambda: print(f"would purge {rel_dir} for good"),
        )
        return
    confirm(args, f"Purge {args.sim_ref!r} for good?", doing="purge")

    result = purge_simulation(
        args.sim_ref,
        workspace=args.workspace,
        reason=args.reason,
        archive_pii=args.archive_pii,
        operator=_purge_resolve_operator(),
    )

    def table() -> None:
        print(f"Purged {result['rel_dir']} ({result['sim_id']}); its name stays taken")
        for path in result["removed_paths"]:
            print(f"  removed: {path}")
        print(f"Certificate: {result['certificate']}")
        if result["archive"]:
            print(f"PII archive (0o600): {result['archive']}")

    emit(args, "privacy purge", {**result, "applied": True}, table=table)


def _purge_resolve_operator() -> str:
    """Resolve the purge operator through ``AuthBackend``.

    Delegates to :class:`hydromodpy.cli.auth.AuthBackend`. Falls back
    to ``"anonymous"`` if the backend itself fails: a purge must not stop on
    an identity probe.
    """
    try:
        from hydromodpy.cli.auth import AuthBackend

        return AuthBackend().current_user() or "anonymous"
    except Exception:  # noqa: BLE001 - purge must not crash on identity probe
        return "anonymous"


def _cmd_verify(args: argparse.Namespace) -> None:
    from hydromodpy.results.catalog.privacy import verify_purge_certificate

    try:
        result = verify_purge_certificate(args.certificate, strict=args.strict)
    except ValueError as exc:
        refuse(str(exc), EXIT_CONFIG, cause=exc)

    if not result["permissions_ok"] and result["permissions"]:
        print(
            f"WARNING: certificate permissions {result['permissions']}, expected 0o600",
            file=sys.stderr,
        )
    payload = result["payload"]

    def table() -> None:
        print(f"OK: certificate {result['certificate']} verifies")
        print(f"  sim_id      : {payload['sim_id']}")
        print(f"  timestamp   : {payload['timestamp_utc']}")
        print(f"  operator    : {payload['operator']}")
        print(f"  sha256      : {payload['sha256_snapshot'][:16]}...")

    emit(
        args,
        "privacy verify",
        {
            "certificate": result["certificate"],
            "permissions_ok": result["permissions_ok"],
            "permissions": result["permissions"],
            **{
                key: payload.get(key)
                for key in ("sim_id", "timestamp_utc", "operator", "reason", "sha256_snapshot")
            },
        },
        table=table,
    )


__all__ = ("NAME", "HELP", "register", "run")
