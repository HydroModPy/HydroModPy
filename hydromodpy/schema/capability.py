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
        object.__setattr__(self, "keywords", tuple(self.keywords))
        object.__setattr__(self, "outputs", tuple(self.outputs))
        object.__setattr__(self, "exceptions", tuple(self.exceptions))
        object.__setattr__(self, "env", tuple(self.env))

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
    "CapabilityDecl",
    "OutputDecl",
]
