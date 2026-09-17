"""The one directory a capability process is allowed to touch.

The caller creates the directory, writes ``request.json`` into it, and passes
its path. Everything the process reads that it did not put there is a path the
request declared, and everything it writes is under this root. That is what
makes "wrote nothing outside the job directory" a single assertion rather than
a hope, and it is why this type resolves every path instead of the callers
joining strings.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

from hydromodpy.core.exceptions import JobUsageError
from hydromodpy.schema.job.layout import (
    INPUTSET_FILENAME,
    JOB_LOG_FILENAME,
    JOB_MANIFEST_FILENAME,
    JOB_PROVENANCE_FILENAME,
    LOGS_DIRNAME,
    OUTCOME_FILENAME,
    OUTPUTS_DIRNAME,
    PROGRESS_FILENAME,
    REQUEST_FILENAME,
)
from hydromodpy.schema.job.refusal import refuse_request

_SCHEME_PATTERN = re.compile(r"^(?P<scheme>[A-Za-z][A-Za-z0-9+.\-]*):")


def _strip_file_scheme(href: str, *, loc: Sequence[str]) -> str:
    """Return the local path *href* names, refusing every non-local scheme.

    A single-letter scheme is a Windows drive letter and not a scheme at all,
    which is the one case a naive RFC 3986 reading gets wrong.
    """
    match = _SCHEME_PATTERN.match(href)
    if match is None:
        return href
    scheme = match.group("scheme")
    if len(scheme) == 1:
        return href
    if scheme.lower() != "file":
        raise refuse_request(
            f"input {href!r} uses the {scheme!r} scheme; a capability reads local paths only "
            "and never opens the network",
            loc=loc,
            msg=f"unsupported URI scheme {scheme!r}",
        )
    parsed = urlparse(href)
    if parsed.netloc not in ("", "localhost"):
        raise refuse_request(
            f"input {href!r} names the host {parsed.netloc!r}; a capability reads local paths only",
            loc=loc,
            msg="a file: URI must name a local path",
        )
    return unquote(parsed.path)


@dataclass(frozen=True, slots=True)
class JobDirectory:
    """One job directory, resolved once so containment is decidable."""

    root: Path

    @classmethod
    def open(cls, path: str | Path) -> JobDirectory:
        """Open an existing job directory that already carries its request.

        Refuses with :class:`JobUsageError` rather than a generic failure: a
        missing directory or a missing request is the caller's mistake about
        how to invoke the process, and it is the one failure that must stay
        distinguishable from the process failing at its work.
        """
        root = Path(path).expanduser()
        if not root.is_dir():
            raise JobUsageError(f"job directory {root} does not exist")
        job = cls(root.resolve())
        if not job.request_path.is_file():
            raise JobUsageError(f"job directory {job.root} carries no {REQUEST_FILENAME}")
        return job

    @classmethod
    def create(cls, path: str | Path) -> JobDirectory:
        """Create the directory and return it, without requiring a request.

        The invocation contract gives this step to the caller. It is here for
        the caller that is a test or a staging verb, never for a capability
        body.
        """
        root = Path(path).expanduser()
        root.mkdir(parents=True, exist_ok=True)
        return cls(root.resolve())

    @property
    def request_path(self) -> Path:
        return self.root / REQUEST_FILENAME

    @property
    def inputset_path(self) -> Path:
        return self.root / INPUTSET_FILENAME

    @property
    def provenance_path(self) -> Path:
        return self.root / JOB_PROVENANCE_FILENAME

    @property
    def outcome_path(self) -> Path:
        return self.root / OUTCOME_FILENAME

    @property
    def manifest_path(self) -> Path:
        return self.root / JOB_MANIFEST_FILENAME

    @property
    def outputs_dir(self) -> Path:
        return self.root / OUTPUTS_DIRNAME

    @property
    def logs_dir(self) -> Path:
        return self.root / LOGS_DIRNAME

    @property
    def log_path(self) -> Path:
        return self.logs_dir / JOB_LOG_FILENAME

    @property
    def progress_path(self) -> Path:
        return self.root / PROGRESS_FILENAME

    @property
    def is_sealed(self) -> bool:
        """Whether the seal is present. Its absence is never ambiguous."""
        return self.manifest_path.is_file()

    def contains(self, path: str | Path) -> bool:
        """Whether *path* is inside this job directory, symlinks followed."""
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = self.root / candidate
        return candidate.resolve().is_relative_to(self.root)

    def resolve_output(self, relative: str | Path) -> Path:
        """Resolve a path the capability writes, and prove it stays inside.

        Raised as a programming error, not as a refused document: an output
        path comes from a declaration this repository ships, never from the
        caller, so a path that escapes is a bug here and not bad input.
        """
        resolved = (self.root / Path(relative)).resolve()
        if not resolved.is_relative_to(self.root):
            raise ValueError(f"output path {relative!r} resolves outside {self.root}")
        return resolved

    def resolve_input(self, href: str, *, loc: Sequence[str]) -> Path:
        """Resolve a path the request declared, relative to this directory.

        An absolute path is read where it is: an orchestrator stages its data
        once and points several jobs at it. A relative path is resolved against
        the job directory and must stay inside it, so a ``..`` that walks out
        of the only directory the caller granted is refused as bad input,
        pointed at the member that carries it.
        """
        raw = _strip_file_scheme(href, loc=loc)
        if not raw:
            raise refuse_request(
                "input path is empty", loc=loc, msg="an input path cannot be empty"
            )
        candidate = Path(raw)
        if candidate.is_absolute():
            return candidate.resolve()
        resolved = (self.root / candidate).resolve()
        if not resolved.is_relative_to(self.root):
            raise refuse_request(
                f"input path {href!r} resolves outside the job directory {self.root}",
                loc=loc,
                msg="a relative input path must stay inside the job directory",
            )
        return resolved

    def relative(self, path: str | Path) -> str:
        """Render *path* the way the seal names it: relative, forward slashes."""
        resolved = Path(path)
        if not resolved.is_absolute():
            resolved = self.root / resolved
        resolved = resolved.resolve()
        if not resolved.is_relative_to(self.root):
            raise ValueError(f"{path!r} is not inside {self.root}")
        return resolved.relative_to(self.root).as_posix()

    def ensure_workspace(self) -> None:
        """Create the two directories a running job appends into."""
        self.outputs_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)


__all__ = ["JobDirectory"]
