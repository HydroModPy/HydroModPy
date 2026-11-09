"""The reader of ``credentials.toml``, the file that holds one identity per address prefix.

The file lives outside every project and every workspace, one ``[[host]]``
block per address prefix, with the password written in clear or named by a
file. The block is chosen by the longest prefix that matches a destination,
so no credential name is ever written in a project TOML, in ``request.json``
or in a seal. A refused file stops the verb that opened it, before any step.

``credential_for`` is used by delivery; at this lot only the loader
(:func:`load_credentials`, through ``Environment.check``) and the tests below
read what it returns.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from hydromodpy.core.exceptions import CredentialsError

_SCHEMES = ("ftp", "ftps", "sftp", "http", "https")
"""The schemes a prefix may carry; anything else is refused by name."""

_SCHEME_LIST = "one of ftp, ftps, sftp, http or https"
"""The same schemes, as a refusal says them. The message of both refusals
reads the same words, because a user should learn one list."""


class HostCredential(BaseModel):
    """One ``[[host]]`` block: who reaches one address prefix, and how.

    ``password`` carries the secret in clear, the question's answer allowed
    both ways; ``password_file`` names a file read at the moment a caller
    needs the value, so a rotated file needs no re-reading of this one.
    ``key_file`` and ``host_fingerprint`` are the SFTP fields, refused on any
    other scheme.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    prefix: str
    user: str = ""
    password: SecretStr | None = None
    password_file: Path | None = None
    key_file: Path | None = None
    host_fingerprint: str | None = None

    def secret(self) -> str | None:
        """Return the password of the block, reading its file when named."""
        if self.password is not None:
            return self.password.get_secret_value()
        if self.password_file is not None:
            try:
                text = self.password_file.read_text(encoding="utf-8")
            except OSError as exc:
                raise CredentialsError(
                    f"the password file {self.password_file} declared for "
                    f"{self.prefix!r} cannot be read: {exc}."
                ) from exc
            return text.rstrip("\r\n")
        return None


class _CredentialsFile(BaseModel):
    """The whole TOML: only ``[[host]]`` blocks, every key known."""

    model_config = ConfigDict(extra="forbid")

    host: list[HostCredential] = Field(default_factory=list)


def _prefix_scheme(prefix: str) -> str:
    """Return the scheme of ``prefix``, refused when it is not one this file serves."""
    if "://" not in prefix:
        raise CredentialsError(
            f"the [[host]] block prefix {prefix!r} carries no scheme. A prefix starts "
            f"with {_SCHEME_LIST}."
        )
    scheme = urlsplit(prefix).scheme.lower()
    if scheme not in _SCHEMES:
        raise CredentialsError(
            f"the [[host]] block prefix {prefix!r} carries the scheme {scheme!r}; "
            f"a prefix starts with {_SCHEME_LIST}."
        )
    return scheme


def _is_private(path: Path) -> bool:
    """Answer whether ``path`` is readable at most by its group, POSIX only."""
    if os.name != "posix":
        return True
    return not (path.stat().st_mode & 0o077)


def _check_private(path: Path, what: str) -> None:
    if not _is_private(path):
        raise CredentialsError(
            f"{what} {path} is readable by the group or by others "
            f"(mode {oct(path.stat().st_mode & 0o777)}). Make it private with chmod 600."
        )


def load_credentials(
    path: Path | str, *, forbidden_roots: tuple[Path | str, ...] = ()
) -> tuple[HostCredential, ...]:
    """Read ``path`` and return its blocks, or refuse it with one sentence.

    A named file that does not exist is a refusal, never a bare
    :class:`FileNotFoundError`, so the exit code stays the one a fixed
    configuration asks for. The file is refused under any root of
    ``forbidden_roots`` (a project or a workspace) and when it is readable
    beyond its owner.
    """
    path = Path(path)
    if not path.exists():
        raise CredentialsError(
            f"the credentials file {path} does not exist. Name an existing one, "
            "or drop the file to run without credentials."
        )
    resolved = path.expanduser().resolve()
    for root in forbidden_roots:
        root = Path(root).expanduser().resolve()
        if resolved.is_relative_to(root):
            raise CredentialsError(
                f"the credentials file {resolved} is under {root}, a project or a "
                "workspace. Credentials live outside every project and workspace, "
                "named from the command line or by the server."
            )
    _check_private(resolved, "the credentials file")
    try:
        text = resolved.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise CredentialsError(f"the credentials file {resolved} cannot be read: {exc}.") from exc
    try:
        document = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise CredentialsError(
            f"the credentials file {resolved} is not a valid TOML file: {exc}."
        ) from exc
    try:
        file = _CredentialsFile.model_validate(document)
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(loc) for loc in first["loc"])
        raise CredentialsError(
            f"the credentials file {resolved} refuses a block ({where}): {first['msg']}."
        ) from exc
    for host in file.host:
        scheme = _prefix_scheme(host.prefix)
        if host.password is not None and host.password_file is not None:
            raise CredentialsError(
                f"the [[host]] block {host.prefix!r} carries password and "
                "password_file together. Give one of them."
            )
        if host.password_file is not None:
            password_file = host.password_file
            if not password_file.exists():
                raise CredentialsError(
                    f"the password file {password_file} named by the [[host]] block "
                    f"{host.prefix!r} does not exist."
                )
            if not _is_private(password_file):
                raise CredentialsError(
                    f"the password file {password_file} named by the [[host]] block "
                    f"{host.prefix!r} is readable by others "
                    f"(mode {oct(password_file.stat().st_mode & 0o777)}). "
                    "Make it private with chmod 600."
                )
        if (host.key_file is not None or host.host_fingerprint is not None) and scheme != "sftp":
            raise CredentialsError(
                f"the [[host]] block {host.prefix!r} carries key_file or "
                "host_fingerprint, which only an sftp:// prefix serves."
            )
    duplicated = {
        host.prefix: index
        for index, host in enumerate(file.host)
        if [item.prefix for item in file.host].count(host.prefix) > 1
    }
    if duplicated:
        raise CredentialsError(
            f"the credentials file {resolved} carries two [[host]] blocks with the "
            f"same prefix ({', '.join(sorted(duplicated, key=duplicated.get))}). "
            "Write one block per address prefix."
        )
    return tuple(file.host)


def _url_key(url: str) -> str:
    """Return ``url`` with its scheme and authority lowered, its path as written."""
    scheme, sep, rest = url.partition("://")
    if not sep:
        return url
    cut = rest.find("/")
    authority = rest if cut == -1 else rest[:cut]
    tail = "" if cut == -1 else rest[cut:]
    return scheme.lower() + "://" + authority.lower() + tail


def credential_for(
    url: str, credentials: tuple[HostCredential, ...] | list[HostCredential]
) -> HostCredential | None:
    """Return the block of the longest prefix that matches ``url``, or ``None``.

    Scheme and host compare in lower case, the path at a segment boundary:
    a prefix ``ftp://h/a`` does not answer for ``ftp://h/ab/``.
    """
    url = _url_key(url)
    best: HostCredential | None = None
    best_prefix = ""
    for credential in credentials:
        prefix = _url_key(credential.prefix)
        if not url.startswith(prefix):
            continue
        if len(url) > len(prefix) and url[len(prefix)] != "/" and not prefix.endswith("/"):
            continue
        if len(prefix) > len(best_prefix):
            best, best_prefix = credential, prefix
    return best


__all__ = [
    "HostCredential",
    "credential_for",
    "load_credentials",
]
