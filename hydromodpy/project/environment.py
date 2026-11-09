"""The environment of one verb call: its credentials file and its bounds.

A verb that launches, downloads or delivers receives an ``Environment``, built
by the command line or by the server, and the library reads no environment
variable for it. The object is passed by argument the whole way down, is part
of neither ``request.json`` nor the seal, because it says where and with what
rights a call plays, not what the call computes.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from hydromodpy.core.exceptions import CredentialsError
from hydromodpy.core.runtime.bounds import Bounds
from hydromodpy.core.state.portable import state_dir
from hydromodpy.project.credentials import load_credentials

CREDENTIALS_FILENAME = "credentials.toml"
"""The file name of the credentials at their default place."""


@dataclass(frozen=True, slots=True)
class Environment:
    """The credentials file and the bounds of one call.

    ``credentials`` of ``None`` says no file is read: a caller that wants no
    identity at all passes a bare ``Environment``. An absent file at the
    default place of :meth:`default` is an answer (there are no identifiers
    to carry), an absent file named explicitly is a refusal.
    """

    credentials: Path | None = None
    bounds: Bounds = Bounds()

    @classmethod
    def default(cls) -> Environment:
        """Return the environment of a machine, no credentials file named."""
        return cls(credentials=state_dir() / CREDENTIALS_FILENAME, bounds=Bounds())

    def check(self, *, project_root: Path | str, workspace_root: Path | str) -> None:
        """Refuse, at open time, anything the call could only regret later.

        The project root must sit under the roots ``bounds.allowed_roots``
        names when the caller named roots. A credentials file that exists is
        read once here, so a refused file stops the verb before its first
        step instead of stopping a delivery after hours of solve; a file
        named and missing is refused too, unless it is the default one.
        """
        self.bounds.require_path(project_root, why="opening the project")
        if self.credentials is None:
            return
        credentials = Path(self.credentials).expanduser()
        if not credentials.exists():
            default = Path(state_dir()) / CREDENTIALS_FILENAME
            if credentials.resolve() == default.resolve():
                return
            raise CredentialsError(
                f"the credentials file {credentials} does not exist. Name an "
                "existing one, or drop the file to run without credentials."
            )
        load_credentials(
            credentials,
            forbidden_roots=(Path(project_root), Path(workspace_root)),
        )

    def flags(self) -> tuple[str, ...]:
        """Return this environment as the ``--credentials``, ``--allow-host`` and
        ``--max-download-bytes`` options a launched case reads on its own
        command line.

        Only what a command line can say crosses: the credentials file, the
        named hosts and a ceiling away from its default. A credentials file
        equal to the one of :meth:`default` emits no option, because the
        worker builds the same default when it reads none. ``allowed_roots``
        has no option and does not cross: a server that names roots launches
        its cases under its own object.
        """
        from hydromodpy.core.runtime.bounds import DEFAULT_MAX_DOWNLOAD_BYTES

        out: list[str] = []
        if self.credentials is not None:
            default = Path(state_dir()) / CREDENTIALS_FILENAME
            credentials = Path(self.credentials).expanduser()
            if credentials.resolve() != default.resolve():
                out += ["--credentials", str(credentials.resolve())]
        for host in sorted(self.bounds.allowed_hosts or ()):
            out += ["--allow-host", host]
        if self.bounds.max_download_bytes != DEFAULT_MAX_DOWNLOAD_BYTES:
            out += ["--max-download-bytes", str(self.bounds.max_download_bytes)]
        return tuple(out)


__all__ = [
    "CREDENTIALS_FILENAME",
    "Environment",
]
