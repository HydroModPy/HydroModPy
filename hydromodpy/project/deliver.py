"""Deliver the export files of a sealed run to folders and remote servers.

A block of the ``[[export]]`` table that names ``deliver_to`` sends each file
it wrote, once the run is sealed: to a local or UNC folder or file, or to an
``ftp://``, ``ftps://`` or ``sftp://`` address. Every destination is checked
before the run computes (:func:`preflight`), each file is pushed through a
``.part`` name in at most three attempts (:func:`deliver_run`), and each
attempt is recorded in ``published.jsonl``. :func:`deliver_pending` resumes
what the lines say is not delivered. Nothing raises for a delivery reason
after the seal: a refusal becomes a ``failed`` line, and the run stays sealed
and successful.

A destination is never created; the subfolders below it are. A local folder is
a folder, a local file names one file, and an address names a folder when it
ends with ``/``. The identity of an address comes from ``credentials.toml``,
read once through :mod:`hydromodpy.project.credentials`.
"""

from __future__ import annotations

import contextlib
import ftplib
import hashlib
import importlib.util
import os
import posixpath
import shutil
import ssl
import sys
import time
import tomllib
from base64 import b64encode
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Final

from hydromodpy.core.exceptions import ConfigError, CredentialsError, ExportError, NetworkError
from hydromodpy.core.io.fetch import guard_host
from hydromodpy.core.io.file_digest import sha256_and_size, sha256_of
from hydromodpy.core.logging import get_logger
from hydromodpy.core.runtime.bounds import Bounds
from hydromodpy.core.workspace.resolve import find_data_workspace
from hydromodpy.project.credentials import HostCredential, credential_for, load_credentials
from hydromodpy.project.environment import Environment
from hydromodpy.results.exporters.destination import (
    DELIVER_TO_KEY,
    LOCAL_SCHEME,
    Destination,
    address_of,
    parse_destination,
)
from hydromodpy.results.exporters.export_spec import ExportRequest, load_export_requests
from hydromodpy.results.exporters.request import EXPORT_PRODUCER
from hydromodpy.results.ledger import Ledger
from hydromodpy.results.publication import (
    DELIVERY_ATTEMPTS,
    PublishedLine,
    append_published,
    latest_by_pair,
    read_published,
)
from hydromodpy.results.record.manifest import is_sealed
from hydromodpy.results.storage.contract import RUN_CONFIG_FILENAME, RUN_EXPORTS_DIRNAME

logger = get_logger(__name__)

RETRY_DELAYS_S: Final[tuple[float, ...]] = (1.0, 2.0)
"""The wait after each failed try but the last, in seconds."""

PART_SUFFIX: Final = ".part"
"""What a name carries while its bytes are still being pushed."""

NO_ANSWER: Final = (
    "{address} does not answer: {error}. Nothing was computed; check the address and "
    "the server and run again."
)
"""What a probe says when the server or the remote folder is not there."""

MISSING_FOLDER: Final = (
    "the folder {folder} of deliver_to does not exist or cannot be written. Create it, "
    "or correct deliver_to."
)
"""What a local probe says when its folder is gone or read-only."""

NO_CREDENTIALS_FILE: Final = (
    "this call reads no credentials file, and {address} needs one: pass --credentials."
)
"""What a remote delivery says when the call named no file to read."""


@dataclass(frozen=True)
class _Pair:
    """One file of a run going to one destination."""

    source: Path
    file: str
    """The path of the file relative to the run, ``exports/...``."""
    relative: str
    """The path of the file relative to ``exports/``, with forward slashes."""
    destination: Destination
    address: str
    """Where the file lands, as a delivery line records it."""

    @property
    def key(self) -> tuple[str, str]:
        """Return what names the pair in ``published.jsonl``."""
        return (self.file, self.address)


def _authority(destination: Destination) -> str:
    """Return ``scheme://host[:port]``, the start a ``[[host]]`` prefix compares."""
    port = f":{destination.port}" if destination.port is not None else ""
    return f"{destination.scheme}://{destination.host}{port}"


class _Blocks:
    """The ``[[host]]`` blocks of one delivery, read once, a refusal kept."""

    def __init__(self, environment: Environment, project_root: Path) -> None:
        self._environment = environment
        self._project_root = Path(project_root)
        self._blocks: tuple[HostCredential, ...] | None = None
        self._refusal: CredentialsError | None = None

    def for_destination(self, destination: Destination) -> HostCredential:
        """Return the block that answers *destination*, or refuse with one sentence."""
        blocks = self._loaded(destination.text)
        credential = credential_for(destination.text, blocks)
        if credential is None:
            raise CredentialsError(
                f"no [[host]] block of {self._path()} answers {destination.text}. Add one with "
                f'prefix = "{_authority(destination)}/", user and password or '
                "password_file, or remove deliver_to."
            )
        return credential

    def _path(self) -> Path:
        return Path(self._environment.credentials or "").expanduser()

    def _loaded(self, address: str) -> tuple[HostCredential, ...]:
        if self._refusal is not None:
            raise self._refusal
        if self._blocks is not None:
            return self._blocks
        path = self._environment.credentials
        if path is None or not Path(path).expanduser().exists():
            raise CredentialsError(NO_CREDENTIALS_FILE.format(address=address))
        workspace_root = find_data_workspace(self._project_root) or self._project_root
        try:
            self._blocks = load_credentials(
                Path(path).expanduser(),
                forbidden_roots=(self._project_root, workspace_root),
            )
        except CredentialsError as exc:
            self._refusal = exc
            raise
        return self._blocks


def preflight(
    requests: Sequence[ExportRequest], environment: Environment, *, project_root: Path
) -> None:
    """Check every destination of *requests* before the run computes anything.

    A refused destination stops the verb with the sentence a reader acts on,
    and no directory is claimed. One probe covers every window of the run.
    """
    blocks = _Blocks(environment, Path(project_root))
    seen: set[str] = set()
    for request in requests:
        for text in request.deliver_to or ():
            if text in seen:
                continue
            seen.add(text)
            _check(parse_destination(text), environment, blocks)


def deliver_run(
    run_dir: Path,
    requests: Sequence[ExportRequest],
    environment: Environment,
    *,
    project_root: Path,
    delays: Sequence[float] = RETRY_DELAYS_S,
) -> tuple[PublishedLine, ...]:
    """Deliver the files of *requests* for the sealed run at *run_dir*.

    One line per file and destination is appended to ``published.jsonl`` as
    ``pending``, then as ``delivered`` or ``failed``. The final lines are
    returned in the order the pairs were planned. A refusal at this point is a
    ``failed`` line, never an exception: the run is already sealed.
    """
    run_dir = Path(run_dir)
    return _deliver_pairs(run_dir, _pairs_of(run_dir, requests), environment, project_root, delays)


def deliver_pending(
    run_dir: Path,
    environment: Environment,
    *,
    project_root: Path,
    delays: Sequence[float] = RETRY_DELAYS_S,
) -> tuple[PublishedLine, ...]:
    """Deliver again what the lines of a sealed run say is not delivered.

    The pairs come from the ``[[export]]`` blocks of the sealed
    ``config.toml`` and from the lines of ``published.jsonl`` themselves, so a
    run skipped for an identical one delivers too. A delivered pair is pushed
    again only when the bytes of its file changed, which a promotion or
    ``--regen`` does.
    """
    run_dir = Path(run_dir)
    if not is_sealed(run_dir):
        raise ExportError(f"{run_dir} has no seal: only a sealed run is delivered.")
    planned = _pairs_of(run_dir, _sealed_requests(run_dir))
    lines = [line for line in read_published(run_dir) if line.kind == "delivery"]
    state = latest_by_pair(lines)
    wanted: list[_Pair] = []
    seen: set[tuple[str, str]] = set()
    for pair in planned:
        if _holds(pair, state.get(pair.key)):
            continue
        seen.add(pair.key)
        wanted.append(pair)
    for key, line in state.items():
        if key in seen or _state_is_current(run_dir, line):
            continue
        pair = _pair_of_line(run_dir, line)
        if pair is None:
            continue
        seen.add(key)
        wanted.append(pair)
    return _deliver_pairs(run_dir, wanted, environment, project_root, delays)


def _check(destination: Destination, environment: Environment, blocks: _Blocks) -> None:
    """Check one destination before the run computes, then probe it."""
    credential = _check_reach(destination, environment.bounds, blocks)
    if credential is not None:
        _check_sftp(destination, credential)
    PROBES[destination.scheme](destination, credential, environment.bounds)


def _check_reach(
    destination: Destination, bounds: Bounds, blocks: _Blocks
) -> HostCredential | None:
    """Refuse a destination the bounds do not reach; return the block of a remote one.

    The first delivery and every resumed one pass here, so both refuse the
    same hosts and paths, and both warn of a clear ftp password.
    """
    if destination.scheme == LOCAL_SCHEME:
        _check_local(destination, bounds)
        return None
    bounds.require_hosts([destination.host or ""], why=f"delivery to {destination.text}")
    guard_host(destination.host or "", bounds, what=f"delivery to {destination.text}")
    credential = blocks.for_destination(destination)
    if destination.scheme == "ftp" and credential.secret() is not None:
        logger.warning(
            "ftp://%s sends its password in clear; use ftps:// when the server offers it.",
            destination.host,
        )
    return credential


def _check_local(destination: Destination, bounds: Bounds) -> None:
    if destination.text.startswith("\\\\") and os.name != "nt":
        raise ConfigError(
            f"deliver_to = {destination.text!r} is a UNC path, which only Windows reaches. "
            "Mount the share and write its local path."
        )
    bounds.require_path(destination.path, why=f"delivery to {destination.text}")


def _check_sftp(destination: Destination, credential: HostCredential) -> None:
    if destination.scheme != "sftp":
        return
    if not credential.host_fingerprint:
        raise CredentialsError(
            f"the [[host]] block {credential.prefix!r} has no host_fingerprint, which sftp:// "
            "needs to know the server. Write the SHA256 fingerprint the server shows."
        )
    if credential.secret() is None and credential.key_file is None:
        raise CredentialsError(
            f"the [[host]] block {credential.prefix!r} carries neither password nor key_file, "
            "which sftp:// needs to reach the server."
        )
    if not _has_paramiko():
        raise ConfigError("sftp:// needs the sftp extra: pip install 'hydromodpy[sftp]'.")


def _has_paramiko() -> bool:
    """Answer whether the ``sftp`` extra can be imported, without importing it."""
    return "paramiko" in sys.modules or importlib.util.find_spec("paramiko") is not None


# -- What goes where --------------------------------------------------------- #


def _pairs_of(run_dir: Path, requests: Iterable[ExportRequest]) -> list[_Pair]:
    """Return the files and destinations of *requests*, in block, file, address order."""
    exports_dir = run_dir / RUN_EXPORTS_DIRNAME
    ledger = Ledger.read(exports_dir)
    pairs: list[_Pair] = []
    seen: set[tuple[str, str]] = set()
    for request in requests:
        destinations = [parse_destination(text) for text in request.deliver_to or ()]
        if not destinations:
            continue
        wanted = request.model_dump(mode="json", exclude_none=True, exclude={DELIVER_TO_KEY})
        names = [
            entry.file
            for entry in ledger.entries
            if entry.producer == EXPORT_PRODUCER and entry.options == wanted
        ]
        if not names:
            logger.warning(
                "the export block variables = %r names deliver_to but wrote no file; "
                "nothing is delivered for it.",
                request.variables,
            )
            continue
        for name in names:
            for destination in destinations:
                pair = _Pair(
                    source=exports_dir / name,
                    file=f"{RUN_EXPORTS_DIRNAME}/{name}",
                    relative=name,
                    destination=destination,
                    address=address_of(destination, name),
                )
                if pair.key in seen:
                    continue
                seen.add(pair.key)
                pairs.append(pair)
    return pairs


def _sealed_requests(run_dir: Path) -> list[ExportRequest]:
    """Return the export blocks of the sealed configuration that carry ``deliver_to``."""
    target = run_dir / RUN_CONFIG_FILENAME
    try:
        document = tomllib.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ExportError(f"{target} cannot be read: {exc}") from exc
    return [
        request
        for request in load_export_requests(document.get("export", []))
        if request.deliver_to
    ]


def _holds(pair: _Pair, line: PublishedLine | None) -> bool:
    """Answer whether *line* already records the bytes *pair* would push."""
    if line is None or line.state != "delivered":
        return False
    return pair.source.is_file() and sha256_of(pair.source) == line.sha256


def _pair_of_line(run_dir: Path, line: PublishedLine) -> _Pair | None:
    """Return the pair a delivery line records, or ``None`` when its file is gone."""
    if not line.file or not line.destination:
        return None
    source = run_dir / line.file
    if not source.is_file():
        logger.warning("cannot deliver %s again: the file is not in the run.", line.file)
        return None
    relative = line.file
    prefix = RUN_EXPORTS_DIRNAME + "/"
    if relative.startswith(prefix):
        relative = relative[len(prefix) :]
    return _Pair(
        source=source,
        file=line.file,
        relative=relative,
        destination=parse_destination(line.destination),
        address=line.destination,
    )


def _state_is_current(run_dir: Path, line: PublishedLine) -> bool:
    """Answer whether a line read from the file still stands."""
    if line.state != "delivered" or not line.file:
        return False
    source = run_dir / line.file
    return source.is_file() and sha256_of(source) == line.sha256


# -- The pushes -------------------------------------------------------------- #


def _deliver_pairs(
    run_dir: Path,
    pairs: Sequence[_Pair],
    environment: Environment,
    project_root: Path,
    delays: Sequence[float],
) -> tuple[PublishedLine, ...]:
    """Push every pair, one pending line then one final line each.

    Each destination passes :func:`_check_reach` once, before its first push.
    A refused destination, or a file that cannot be read, gives a ``failed``
    line with ``attempts = 1`` and no push.
    """
    blocks = _Blocks(environment, Path(project_root))
    refusals: dict[str, Exception | None] = {}
    written: list[PublishedLine] = []
    for pair in pairs:
        text = pair.destination.text
        if text not in refusals:
            refusals[text] = _reach_refusal(pair.destination, environment.bounds, blocks)
        refusal = refusals[text]
        try:
            digest, size = sha256_and_size(pair.source)
        except OSError as exc:
            refusal = refusal or OSError(f"{pair.file} cannot be read: {exc}")
            digest, size = None, None
        if refusal is not None:
            line = _line(pair, "failed", digest, size, attempts=1, error=str(refusal))
            logger.warning(
                "could not deliver %s to %s: %s. The run is sealed; deliver it again with "
                "hmp export %s --deliver.",
                pair.file,
                pair.address,
                str(refusal).rstrip("."),
                run_dir.name,
            )
            append_published(run_dir, line)
            written.append(line)
            continue
        append_published(run_dir, _line(pair, "pending", digest, size, attempts=0))
        attempts, error, secret = _attempts(pair, environment, blocks, delays)
        if error is None:
            line = _line(pair, "delivered", digest, size, attempts=attempts)
            logger.info("delivered %s to %s", pair.file, pair.address)
        else:
            message = _scrub(str(error), secret)
            line = _line(pair, "failed", digest, size, attempts=attempts, error=message)
            logger.warning(
                "could not deliver %s to %s after %d attempts: %s. The run is sealed; "
                "deliver it again with hmp export %s --deliver.",
                pair.file,
                pair.address,
                attempts,
                message.rstrip("."),
                run_dir.name,
            )
        append_published(run_dir, line)
        written.append(line)
    return tuple(written)


def _reach_refusal(destination: Destination, bounds: Bounds, blocks: _Blocks) -> Exception | None:
    """Return why :func:`_check_reach` refuses *destination*, or ``None``.

    A credentials refusal is left to the attempts, which read the same block
    and record its sentence.
    """
    try:
        _check_reach(destination, bounds, blocks)
    except CredentialsError:
        return None
    except Exception as exc:  # noqa: BLE001 - after the seal a refusal is a failed line
        return exc
    return None


def _attempts(
    pair: _Pair, environment: Environment, blocks: _Blocks, delays: Sequence[float]
) -> tuple[int, Exception | None, str | None]:
    """Try a pair up to ``DELIVERY_ATTEMPTS`` times; return the count, the error and the secret."""
    last: Exception | None = None
    secret: str | None = None
    attempt = 0
    for attempt in range(1, DELIVERY_ATTEMPTS + 1):
        try:
            credential = _credential_for(pair.destination, blocks)
            secret = credential.secret() if credential is not None else None
            PUSHERS[pair.destination.scheme](
                pair.source, pair.destination, pair.relative, credential, environment.bounds
            )
            return attempt, None, secret
        except Exception as exc:  # noqa: BLE001 - every failure becomes a failed line
            last = exc
            if attempt < DELIVERY_ATTEMPTS:
                time.sleep(delays[attempt - 1] if attempt <= len(delays) else delays[-1])
    return attempt, last, secret


def _line(
    pair: _Pair,
    state: str,
    digest: str | None,
    size: int | None,
    *,
    attempts: int,
    error: str | None = None,
) -> PublishedLine:
    """Return one delivery line of *pair*."""
    return PublishedLine(
        kind="delivery",
        published_at=datetime.now(UTC),
        file=pair.file,
        destination=pair.address,
        state=state,
        sha256=digest,
        bytes=size,
        attempts=attempts,
        error=error,
    )


def _scrub(text: str, secret: str | None) -> str:
    """Return *text* without the password it may quote."""
    if secret:
        return text.replace(secret, "<secret>")
    return text


def _credential_for(destination: Destination, blocks: _Blocks) -> HostCredential | None:
    """Return the block that answers a remote destination; a local one needs none."""
    if destination.scheme == LOCAL_SCHEME:
        return None
    return blocks.for_destination(destination)


def _identity(credential: HostCredential | None, destination: Destination) -> tuple[str, str]:
    """Return the user and the secret a remote destination is reached with."""
    if credential is None:
        raise CredentialsError(NO_CREDENTIALS_FILE.format(address=destination.text))
    return credential.user, credential.secret() or ""


def _remote_name(destination: Destination, relative: str) -> str:
    """Return the name to write, once the client sits in the right remote folder."""
    if destination.folder:
        return PurePosixPath(relative).name
    return posixpath.basename(destination.path)


def _remote_dir(destination: Destination) -> str:
    """Return the remote folder to enter before writing the file."""
    if destination.folder:
        return destination.path
    return posixpath.dirname(destination.path) or "/"


def _local_target(destination: Destination, relative: str) -> Path:
    """Return the path a local destination gives *relative*."""
    if destination.folder:
        return Path(destination.path) / PurePosixPath(relative)
    return Path(destination.path)


def _make_subfolders(root: Path, relative: str) -> None:
    """Create the subfolders of a folder destination, never the destination itself."""
    current = root
    for part in PurePosixPath(relative).parent.parts:
        if part in ("", "/"):
            continue
        current = current / part
        current.mkdir(exist_ok=True)


def _push_path(
    source: Path,
    destination: Destination,
    relative: str,
    credential: HostCredential | None,
    bounds: Bounds,
) -> None:
    """Copy a file under a local folder or file through a ``.part`` name."""
    del credential, bounds
    target = _local_target(destination, relative)
    if destination.folder:
        _make_subfolders(Path(destination.path), relative)
    part = target.with_name(target.name + PART_SUFFIX)
    try:
        shutil.copyfile(source, part)
        os.replace(part, target)
        size = target.stat().st_size
        expected = source.stat().st_size
        if size != expected:
            raise OSError(f"{target} holds {size} bytes, not {expected}.")
    except Exception:
        with contextlib.suppress(OSError):
            part.unlink()
        raise


def _probe_path(
    destination: Destination, credential: HostCredential | None, bounds: Bounds
) -> None:
    """Refuse a local folder that is absent or that this call cannot write."""
    del credential, bounds
    folder = Path(destination.path) if destination.folder else Path(destination.path).parent
    if not folder.is_dir() or not os.access(folder, os.W_OK):
        raise ConfigError(MISSING_FOLDER.format(folder=folder))


def _ftp_client(
    destination: Destination, bounds: Bounds, scheme: str, context: ssl.SSLContext | None
) -> ftplib.FTP:
    """Return a connected client, plain or under explicit TLS."""
    if scheme == "ftps":
        client: ftplib.FTP = ftplib.FTP_TLS(
            context=context or ssl.create_default_context(), timeout=bounds.timeout_s
        )
    else:
        client = ftplib.FTP(timeout=bounds.timeout_s)
    client.connect(destination.host or "", destination.port or 21)
    return client


def _ftp_enter(client: ftplib.FTP, destination: Destination, relative: str) -> None:
    """Enter the remote folder of the destination, creating its subfolders."""
    if not destination.folder:
        client.cwd(_remote_dir(destination))
        return
    client.cwd(destination.path)
    for part in PurePosixPath(relative).parent.parts:
        if part in ("", "/"):
            continue
        try:
            client.cwd(part)
        except ftplib.error_perm:
            client.mkd(part)
            client.cwd(part)


def _ftp_size(client: ftplib.FTP, name: str) -> int | None:
    """Return the size the server gives, or ``None`` when it does not serve ``SIZE``."""
    try:
        return client.size(name)
    except ftplib.all_errors:
        return None


def _push_ftp(
    source: Path,
    destination: Destination,
    relative: str,
    credential: HostCredential | None,
    bounds: Bounds,
) -> None:
    """Push a file over plain FTP, through ``.part``, a rename and a size check."""
    _push_ftp_like(source, destination, relative, credential, bounds, "ftp")


def _push_ftps(
    source: Path,
    destination: Destination,
    relative: str,
    credential: HostCredential | None,
    bounds: Bounds,
    *,
    context: ssl.SSLContext | None = None,
) -> None:
    """Push a file over explicit TLS, the same way as plain FTP."""
    _push_ftp_like(source, destination, relative, credential, bounds, "ftps", context=context)


def _push_ftp_like(
    source: Path,
    destination: Destination,
    relative: str,
    credential: HostCredential | None,
    bounds: Bounds,
    scheme: str,
    *,
    context: ssl.SSLContext | None = None,
) -> None:
    """Push a file over FTP or FTPS, one connection for the whole attempt."""
    user, secret = _identity(credential, destination)
    name = _remote_name(destination, relative)
    part = name + PART_SUFFIX
    client = _ftp_client(destination, bounds, scheme, context)
    try:
        client.login(user, secret)
        if scheme == "ftps":
            client.prot_p()
        _ftp_enter(client, destination, relative)
        expected = source.stat().st_size
        with source.open("rb") as handle:
            client.storbinary(f"STOR {part}", handle)
        try:
            client.rename(part, name)
        except ftplib.error_perm:
            with contextlib.suppress(ftplib.all_errors):
                client.delete(name)
            client.rename(part, name)
        served = _ftp_size(client, name)
        if served is not None and served != expected:
            raise OSError(f"the server holds {served} bytes of {name}, not {expected}.")
    except Exception:
        with contextlib.suppress(ftplib.all_errors, OSError):
            client.delete(part)
        raise
    finally:
        with contextlib.suppress(Exception):
            client.close()


def _probe_ftp(destination: Destination, credential: HostCredential | None, bounds: Bounds) -> None:
    """Connect, enter the remote folder and close."""
    _probe_ftp_like(destination, credential, bounds, "ftp")


def _probe_ftps(
    destination: Destination,
    credential: HostCredential | None,
    bounds: Bounds,
    *,
    context: ssl.SSLContext | None = None,
) -> None:
    """Connect under explicit TLS, enter the remote folder and close."""
    _probe_ftp_like(destination, credential, bounds, "ftps", context=context)


def _probe_ftp_like(
    destination: Destination,
    credential: HostCredential | None,
    bounds: Bounds,
    scheme: str,
    *,
    context: ssl.SSLContext | None = None,
) -> None:
    """Connect, log in, enter the remote folder and close, in one sentence on failure."""
    user, secret = _identity(credential, destination)
    try:
        client = _ftp_client(destination, bounds, scheme, context)
        try:
            client.login(user, secret)
            if scheme == "ftps":
                client.prot_p()
            client.cwd(_remote_dir(destination))
        finally:
            with contextlib.suppress(Exception):
                client.close()
    except ftplib.all_errors as exc:
        raise NetworkError(NO_ANSWER.format(address=destination.text, error=exc)) from exc


def _fingerprint(key: bytes) -> str:
    """Return the SHA256 fingerprint a server prints for *key*, without padding."""
    digest = hashlib.sha256(key).digest()
    return b64encode(digest).decode("ascii").rstrip("=")


def _check_fingerprint(key: bytes, credential: HostCredential, destination: Destination) -> None:
    """Refuse a server whose key is not the one the block names."""
    shown = _fingerprint(key)
    given = (credential.host_fingerprint or "").strip()
    if given.startswith("SHA256:"):
        given = given[len("SHA256:") :]
    if given != shown:
        raise CredentialsError(
            f"the server {destination.host} shows the fingerprint SHA256:{shown}, not "
            f"{credential.host_fingerprint!r}. Write the fingerprint that server shows."
        )


def _sftp_session(destination: Destination, credential: HostCredential | None, bounds: Bounds):
    """Open an SFTP transport, its server key checked before any authentication."""
    import paramiko

    if credential is None:
        raise CredentialsError(NO_CREDENTIALS_FILE.format(address=destination.text))
    transport = paramiko.Transport((destination.host, destination.port or 22))
    try:
        transport.start_client(timeout=bounds.timeout_s)
        _check_fingerprint(transport.get_remote_server_key().asbytes(), credential, destination)
        if credential.secret() is not None:
            transport.auth_password(credential.user, credential.secret() or "")
        else:
            key = paramiko.PKey.from_path(str(credential.key_file))
            transport.auth_publickey(credential.user, key)
    except BaseException:
        with contextlib.suppress(Exception):
            transport.close()
        raise
    return transport


def _sftp_enter(client, destination: Destination, relative: str) -> None:
    """Enter the remote folder of the destination, creating its subfolders."""
    if not destination.folder:
        client.chdir(_remote_dir(destination))
        return
    client.chdir(destination.path)
    for part in PurePosixPath(relative).parent.parts:
        if part in ("", "/"):
            continue
        try:
            client.chdir(part)
        except OSError:
            client.mkdir(part)
            client.chdir(part)


def _push_sftp(
    source: Path,
    destination: Destination,
    relative: str,
    credential: HostCredential | None,
    bounds: Bounds,
) -> None:
    """Push a file over SFTP, through ``.part``, a rename and a size check."""
    name = _remote_name(destination, relative)
    part = name + PART_SUFFIX
    transport = _sftp_session(destination, credential, bounds)
    client = None
    try:
        client = transport.open_sftp()
        _sftp_enter(client, destination, relative)
        expected = source.stat().st_size
        with source.open("rb") as handle:
            client.putfo(handle, part, file_size=expected)
        try:
            client.posix_rename(part, name)
        except OSError:
            with contextlib.suppress(Exception):
                client.remove(name)
            client.posix_rename(part, name)
        served = client.stat(name).st_size
        if served != expected:
            raise OSError(f"the server holds {served} bytes of {name}, not {expected}.")
    except Exception:
        if client is not None:
            with contextlib.suppress(Exception):
                client.remove(part)
        raise
    finally:
        if client is not None:
            with contextlib.suppress(Exception):
                client.close()
        with contextlib.suppress(Exception):
            transport.close()


def _probe_sftp(
    destination: Destination, credential: HostCredential | None, bounds: Bounds
) -> None:
    """Open the transport, enter the remote folder and close."""
    try:
        transport = _sftp_session(destination, credential, bounds)
    except CredentialsError:
        raise
    except Exception as exc:  # noqa: BLE001 - every transport failure reads the same way
        raise NetworkError(NO_ANSWER.format(address=destination.text, error=exc)) from exc
    try:
        client = transport.open_sftp()
        try:
            client.chdir(_remote_dir(destination))
        finally:
            with contextlib.suppress(Exception):
                client.close()
    except Exception as exc:  # noqa: BLE001 - every remote folder failure reads the same way
        raise NetworkError(NO_ANSWER.format(address=destination.text, error=exc)) from exc
    finally:
        with contextlib.suppress(Exception):
            transport.close()


Pusher = Callable[[Path, Destination, str, HostCredential | None, Bounds], None]
"""What a push takes: the source, the destination, its path under ``exports/``, who, bounds."""

Probe = Callable[[Destination, HostCredential | None, Bounds], None]
"""What a probe takes: the destination, who, bounds."""

PUSHERS: dict[str, Pusher] = {
    LOCAL_SCHEME: _push_path,
    "ftp": _push_ftp,
    "ftps": _push_ftps,
    "sftp": _push_sftp,
}
"""One push per scheme; each one creates no destination and removes its ``.part``."""

PROBES: dict[str, Probe] = {
    LOCAL_SCHEME: _probe_path,
    "ftp": _probe_ftp,
    "ftps": _probe_ftps,
    "sftp": _probe_sftp,
}
"""One probe per scheme, run before the run computes."""

__all__ = [
    "PART_SUFFIX",
    "PROBES",
    "PUSHERS",
    "RETRY_DELAYS_S",
    "deliver_pending",
    "deliver_run",
    "preflight",
]
