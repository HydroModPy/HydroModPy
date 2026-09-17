"""What a capability declares about itself, before any of it runs.

A capability is a function from a validated input document to a directory of
sealed artefacts. This module holds the declaration of one: the identity a
caller pins, the model its inputs are validated against, the artefacts it
promises, and the failures it can return.

Nothing here executes and nothing here imports a runtime. The declaration is
what the machine-readable process description is generated from, so it must
stay readable by a layer that owns no engine: stdlib only, and a request model
carried as an opaque type.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

CAPABILITY_ID_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
"""Lowercase kebab-case, the spelling a shim puts in a URL and a file name."""

CAPABILITY_VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")
"""Three-part semantic version. The major is what a caller pins."""

HOST_PATTERN = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*$")
"""One host, lowercase: a DNS name, or an address literal a caller pins instead.

An address literal is accepted on purpose, and the pattern happens to admit an
IPv4 one. The gate compares a *connection* to this same list, so pinning an
address is a declaration that means something rather than a spelling mistake. An
IPv6 literal does not pass, and cannot: its colons are the port separator this
member refuses.
"""

MAX_HOST_LABEL = 63
MAX_HOST_LENGTH = 253
"""RFC 1035 limits. Past either one, no resolver ever hands the name back."""

NAMES_THE_JOB_DOES_NOT_PRODUCE = frozenset({"manifest.json", "request.json"})
"""Two names an output may not take: the seal, and the caller's own document.

Neither is produced by the capability. The seal does not exist when the outcome
that would name it is written, and the request was written by whoever invoked
the process. The other job documents may be declared: the process description
lists ``inputset.json`` and ``outcome.json`` among its outputs, and the seal
re-hashes those from disk.

Spelled here rather than imported from ``schema/job/layout.py``, which owns the
vocabulary: importing it would close a cycle through the job package, so a test
pins the two spellings together instead.
"""


def _refuse_unusable_host(host: str, *, owner: str) -> None:
    """Refuse a declared host a resolved name could never be compared against."""
    if not host.strip():
        raise ValueError(f"{owner}: declares a nameless host")
    if "://" in host:
        raise ValueError(f"{owner}: host {host!r} carries a scheme; declare the host alone")
    if "/" in host:
        raise ValueError(f"{owner}: host {host!r} carries a path; declare the host alone")
    if ":" in host:
        raise ValueError(f"{owner}: host {host!r} carries a port; declare the host alone")
    if "*" in host:
        # Refused rather than supported: no source in this tree needs a subdomain
        # family yet, and a pattern nothing matches against is a claim a caller
        # cannot check. The day one does, this becomes a deliberate change.
        raise ValueError(f"{owner}: host {host!r} is a wildcard, which is not supported")
    if not HOST_PATTERN.match(host):
        raise ValueError(f"{owner}: host {host!r} is not a lowercase DNS name")
    if len(host) > MAX_HOST_LENGTH:
        raise ValueError(
            f"{owner}: host {host!r} is {len(host)} characters, over the {MAX_HOST_LENGTH} a name has"
        )
    too_long = [label for label in host.split(".") if len(label) > MAX_HOST_LABEL]
    if too_long:
        raise ValueError(
            f"{owner}: host {host!r} has a label over {MAX_HOST_LABEL} characters, "
            "which no resolver answers"
        )


def _refuse_relative_path(path: str, *, owner: str) -> None:
    """Refuse an output path that could address anything outside the job."""
    if not path:
        raise ValueError(f"{owner}: output path is empty")
    if path.startswith("/") or path.startswith("\\"):
        raise ValueError(f"{owner}: output path {path!r} is absolute")
    if re.match(r"^[A-Za-z]:", path):
        raise ValueError(f"{owner}: output path {path!r} carries a drive letter")
    parts = path.replace("\\", "/").split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ValueError(f"{owner}: output path {path!r} is not a plain relative path")


@dataclass(frozen=True, slots=True)
class OutputDecl:
    """One artefact a capability promises, named by a stable relative path."""

    id: str
    title: str
    path: str
    media_type: str
    roles: tuple[str, ...]
    required: bool = True
    extra: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("output declaration has no id")
        if not self.title:
            raise ValueError(f"output {self.id!r} has no title")
        if not self.media_type:
            raise ValueError(f"output {self.id!r} has no media type")
        if not self.roles:
            raise ValueError(f"output {self.id!r} declares no role")
        _refuse_relative_path(self.path, owner=f"output {self.id!r}")
        if self.path in NAMES_THE_JOB_DOES_NOT_PRODUCE:
            raise ValueError(
                f"output {self.id!r} claims {self.path!r}, which the job does not produce"
            )
        object.__setattr__(self, "roles", tuple(self.roles))
        object.__setattr__(self, "extra", MappingProxyType(dict(self.extra)))


@dataclass(frozen=True, slots=True)
class CapabilityDecl:
    """One externally invocable capability, declared and not yet executed."""

    id: str
    version: str
    title: str
    description: str
    keywords: tuple[str, ...]
    request_model: type
    outputs: tuple[OutputDecl, ...]
    exceptions: tuple[type[BaseException], ...]
    env: tuple[str, ...] = ()
    writes_outside_jobdir: tuple[str, ...] = ()
    """Every location outside the job directory this capability writes into.

    Empty means the job directory is the only thing that needs to be writable,
    which is what an orchestrator mounting everything else read-only relies on.
    A capability that needs scratch space says so, by the name of the variable
    that points at it -- ``"$TMPDIR"`` -- and not by a boolean that would be
    false. A declaration nobody can check is the defect this whole phase exists
    to remove, so a test runs the capability with a controlled ``TMPDIR`` and
    asserts that nothing landed anywhere else.
    """

    reaches_network: tuple[str, ...] = ()
    """Every host this capability contacts. Empty means it contacts none.

    A list of hosts and not a boolean, for the same reason as
    ``writes_outside_jobdir``: the question an orchestrator has to answer is not
    "does it need egress" but "to where", because that is the shape a firewall
    rule and a proxy allowlist are written in. An empty tuple is the honest
    spelling of "nowhere", and it is what makes a capability runnable on a
    compute node with no egress at all.

    A host, not a URL: the path a capability requests is its own business and
    changes with the query, while the host is what somebody else has to allow.
    Each entry is a lowercase DNS name or an address literal, refused if it
    carries a scheme, a port, a path or a wildcard, or if it is longer than a
    resolver would ever answer -- a declaration that cannot be compared to what
    a socket actually resolved is the thing this member exists to avoid.
    """

    def __post_init__(self) -> None:
        if not CAPABILITY_ID_PATTERN.match(self.id):
            raise ValueError(f"capability id {self.id!r} is not lowercase kebab-case")
        if not CAPABILITY_VERSION_PATTERN.match(self.version):
            raise ValueError(f"capability {self.id!r} version {self.version!r} is not x.y.z")
        if not self.title:
            raise ValueError(f"capability {self.id!r} has no title")
        if not self.description:
            raise ValueError(f"capability {self.id!r} has no description")
        if not isinstance(self.request_model, type) or not hasattr(
            self.request_model, "model_validate"
        ):
            raise ValueError(f"capability {self.id!r} request model is not a Pydantic model")
        if not self.outputs:
            raise ValueError(f"capability {self.id!r} declares no output")
        self._refuse_duplicates()
        for exc in self.exceptions:
            if not (isinstance(exc, type) and issubclass(exc, BaseException)):
                raise ValueError(f"capability {self.id!r} declares {exc!r} as an exception")
        for location in self.writes_outside_jobdir:
            if not location.strip():
                raise ValueError(f"capability {self.id!r} declares a nameless write location")
        for host in self.reaches_network:
            _refuse_unusable_host(host, owner=f"capability {self.id!r}")
        repeated_hosts = sorted(
            {host for host in self.reaches_network if self.reaches_network.count(host) > 1}
        )
        if repeated_hosts:
            raise ValueError(f"capability {self.id!r} repeats host(s) {repeated_hosts}")
        object.__setattr__(self, "keywords", tuple(self.keywords))
        object.__setattr__(self, "outputs", tuple(self.outputs))
        object.__setattr__(self, "exceptions", tuple(self.exceptions))
        object.__setattr__(self, "env", tuple(self.env))
        object.__setattr__(self, "writes_outside_jobdir", tuple(self.writes_outside_jobdir))
        object.__setattr__(self, "reaches_network", tuple(self.reaches_network))

    def _refuse_duplicates(self) -> None:
        """Refuse two outputs sharing an id or a path.

        Two outputs on one path would make the seal list one file twice with
        two ids, and a caller asking for either would get the same bytes.
        """
        ids = [output.id for output in self.outputs]
        duplicate_ids = sorted({name for name in ids if ids.count(name) > 1})
        if duplicate_ids:
            raise ValueError(f"capability {self.id!r} repeats output id(s) {duplicate_ids}")
        paths = [output.path for output in self.outputs]
        duplicate_paths = sorted({path for path in paths if paths.count(path) > 1})
        if duplicate_paths:
            raise ValueError(f"capability {self.id!r} repeats output path(s) {duplicate_paths}")

    @property
    def major(self) -> int:
        """The version a caller pins. A bump of it breaks every shim."""
        return int(self.version.split(".")[0])

    @property
    def output_ids(self) -> tuple[str, ...]:
        return tuple(output.id for output in self.outputs)

    def output(self, output_id: str) -> OutputDecl:
        """Return the declared output named *output_id*."""
        for output in self.outputs:
            if output.id == output_id:
                return output
        raise KeyError(output_id)


__all__ = [
    "CAPABILITY_ID_PATTERN",
    "CAPABILITY_VERSION_PATTERN",
    "HOST_PATTERN",
    "MAX_HOST_LABEL",
    "MAX_HOST_LENGTH",
    "NAMES_THE_JOB_DOES_NOT_PRODUCE",
    "CapabilityDecl",
    "OutputDecl",
]
