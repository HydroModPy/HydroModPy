"""The bounds of one call: the hosts it may reach, the roots it may use.

``Bounds`` says which hosts a call may reach, under which roots it may read
or write, and how many bytes and seconds a download may take. It is carried
by :class:`hydromodpy.project.environment.Environment` and by every
:class:`~hydromodpy.data.source.port.FetchRequest`; the fetch client applies
it. The class reads no environment variable and writes none: a caller builds
it, from the command line or from the server, and passes it along.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from hydromodpy.core.exceptions import BoundsError

DEFAULT_MAX_DOWNLOAD_BYTES = 2_147_483_648
"""The 2 GiB ceiling of one download; the fetch client applies it."""

DEFAULT_TIMEOUT_S = 30.0
"""The delay of one network request.

The value of ``DEFAULT_TIMEOUT`` in ``core/io/http_client.py``, which the
fetch client replaces by this member.
"""


def _host_key(host: str) -> str:
    """Return the comparison form of ``host``: lower case, IDNA, port removed.

    A port is never part of what a bounds allows, an IPv6 literal may carry
    one and is compared whole, and a label the IDNA codec refuses (a label
    longer than 63 bytes) keeps its lowered form.
    """
    name = host.strip().lower()
    if name.startswith("[") and name.endswith("]"):
        name = name[1:-1]
    head, sep, port = name.rpartition(":")
    if sep and ":" not in head and port.isdigit():
        name = head
    try:
        return name.encode("idna").decode("ascii").lower()
    except UnicodeError:
        return name


@dataclass(frozen=True, slots=True)
class Bounds:
    """What one call may reach, and how much of it.

    ``allowed_hosts`` of ``None`` permits every public host, the default of a
    machine in an office; an empty set declares the call offline. Named sets
    are exact host names, compared after lower case and IDNA with the port
    removed, no glob. ``allowed_roots`` of ``None`` bounds nothing, the same
    default; on a server the caller names the roots a path may sit under.

    The object is pickled to worker processes and is part of neither ``config``
    nor ``request.json``: it says where and with what rights a call plays, not
    what the call computes.
    """

    allowed_hosts: frozenset[str] | None = None
    allowed_roots: tuple[Path, ...] | None = None
    max_download_bytes: int = DEFAULT_MAX_DOWNLOAD_BYTES
    timeout_s: float = DEFAULT_TIMEOUT_S

    def __post_init__(self) -> None:
        if (
            isinstance(self.max_download_bytes, bool)
            or not isinstance(self.max_download_bytes, int)
            or self.max_download_bytes <= 0
        ):
            raise BoundsError(
                f"max_download_bytes={self.max_download_bytes!r} is not a positive number of bytes."
            )
        if (
            isinstance(self.timeout_s, bool)
            or not isinstance(self.timeout_s, (int, float))
            or self.timeout_s <= 0
        ):
            raise BoundsError(f"timeout_s={self.timeout_s!r} is not a positive delay.")
        if self.allowed_hosts is not None:
            allowed_hosts = frozenset(self._check_host(host) for host in self.allowed_hosts)
            object.__setattr__(self, "allowed_hosts", allowed_hosts)
        if self.allowed_roots is not None:
            allowed_roots = tuple(self._check_root(root) for root in self.allowed_roots)
            object.__setattr__(self, "allowed_roots", allowed_roots)

    @staticmethod
    def _check_host(host: str) -> str:
        """Return the stored form of one allowed host, or refuse it."""
        if not isinstance(host, str) or not host.strip():
            raise BoundsError(f"allowed_hosts carries {host!r}, which is not a host name.")
        if "://" in host:
            raise BoundsError(f"allowed_hosts carries {host!r} with a scheme. Name the host only.")
        if "/" in host or "?" in host or "#" in host:
            raise BoundsError(f"allowed_hosts carries {host!r} with a path. Name the host only.")
        return _host_key(host)

    @staticmethod
    def _check_root(root: Path | str) -> Path:
        """Return the stored form of one allowed root, or refuse it."""
        if isinstance(root, str):
            root = Path(root)
        if not isinstance(root, Path):
            raise BoundsError(f"allowed_roots carries {root!r}, which is not a path.")
        candidate = root.expanduser()
        if not candidate.is_absolute():
            raise BoundsError(
                f"allowed_roots carries {root}, a relative path. Pass an absolute one."
            )
        return candidate.resolve()

    # -- What the object permits ------------------------------------------- #

    def permits_host(self, host: str) -> bool:
        """Answer whether ``host`` is one this call may contact."""
        if self.allowed_hosts is None:
            return True
        if not self.allowed_hosts:
            return False
        return _host_key(host) in self.allowed_hosts

    def permits_path(self, path: Path | str) -> bool:
        """Answer whether ``path`` sits under a root this call may use.

        The path is resolved, so a link out of the roots is refused. Applied
        to the paths the caller names (a configuration, the project root, an
        export folder), never to the cache or the state of this installation.
        """
        if self.allowed_roots is None:
            return True
        candidate = Path(path).expanduser().resolve()
        return any(candidate.is_relative_to(root) for root in (self.allowed_roots or ()))

    # -- What it refuses, by name ------------------------------------------ #

    def require_host(self, host: str, *, why: str) -> None:
        """Refuse ``host`` with the sentence a reader acts on."""
        if self.permits_host(host):
            return
        allowed = ", ".join(sorted(self.allowed_hosts or ())) or "none: this call is offline"
        raise BoundsError(
            f"{why}: the host {host!r} is not among the hosts this call allows "
            f"({allowed}). Allow it with --allow-host {host}, or name it in "
            "Bounds(allowed_hosts=...)."
        )

    def require_hosts(self, hosts: tuple[str, ...] | list[str], *, why: str) -> None:
        """Refuse every host of ``hosts`` this call does not allow, in one line."""
        if self.allowed_hosts is None:
            return
        refused = sorted(host for host in hosts if not self.permits_host(host))
        if not refused:
            return
        allowed = ", ".join(sorted(self.allowed_hosts)) or "none: this call is offline"
        raise BoundsError(
            f"{why}: the hosts {refused} are not among the hosts this call allows "
            f"({allowed}). Allow one with --allow-host, or name it in "
            "Bounds(allowed_hosts=...)."
        )

    def require_path(self, path: Path | str, *, why: str) -> None:
        """Refuse a named path that leaves the roots the call allows."""
        if self.permits_path(path):
            return
        roots = ", ".join(str(root) for root in (self.allowed_roots or ()))
        raise BoundsError(
            f"{why}: the path {Path(path)} is outside the roots this call allows "
            f"({roots or 'none'}). Name the root that holds it in "
            "Bounds(allowed_roots=...)."
        )


__all__ = [
    "DEFAULT_MAX_DOWNLOAD_BYTES",
    "DEFAULT_TIMEOUT_S",
    "Bounds",
]
