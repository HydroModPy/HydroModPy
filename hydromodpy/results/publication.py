"""What a published copy records, and what the source remembers of it.

Why
---
``hmp publish`` copies a run or a summary out of the tree. The copy must say
where it came from and what it contains, so a reader can verify it and a
source can be matched to it; the source must remember where it went, so a
delete warns. And nothing that leaves the tree may name the machine it was
computed on: the one function :func:`redact` removes the host, the user and
every absolute path from any document on its way out.

Format
------
:class:`PublicationConfig` is the ``[publication]`` section of a project file:
the licence, the creators and the attribution every copy carries.
``PUBLICATION.json`` in the copy is :class:`Publication`: what it copies
(a run, the summary or a whole project), the source by project, directory
and id, the digest of the manifest and of each copied file, the label of the
day, the version, the instant, the format and what was taken along. The copy
of a project lists its members, each by name and by the digest of its own
``PUBLICATION.json``. ``published.jsonl`` in the source is one
:class:`PublishedLine` per copy, appended.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from datetime import date, datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Annotated, Any, Final

from pydantic import ConfigDict, Field, field_validator, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.config_kit.stored import Vocabulary, read_stored
from hydromodpy.core.io.document_version import VersionWindow
from hydromodpy.core.state.layout import SUMMARY_DIRNAME
from hydromodpy.results.rel_dir import checked_rel_dir
from hydromodpy.results.storage.contract import PUBLICATION_FILENAME, RUN_PUBLISHED_FILENAME
from hydromodpy.results.storage.json_io import check_sealed, read_sealed_json, write_json_atomic
from hydromodpy.results.validity_rules import Label


class PublicationConfig(HydroModelBase):
    """The licence and the authorship written into every publication."""

    license: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description=(
            "Licence of the published results, as an SPDX identifier or a licence "
            "name (CC-BY-4.0, etalab-2.0). Required by hmp publish --public."
        ),
        examples=["etalab-2.0"],
    )
    creators: Annotated[list[str], Profile.USER] = Field(
        default_factory=list,
        description="People or bodies credited as creators of the published results.",
        examples=[["A. Author"]],
    )
    attribution: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Attribution text the publication carries, for the data it was built on.",
        examples=["Contains data from Hub'Eau."],
    )


PUBLICATION_SCHEMA: Final[str] = "hydromodpy.publication.v1"
"""Schema id of ``PUBLICATION.json``."""

PUBLICATION_VERSIONS: Final[VersionWindow] = VersionWindow(
    oldest="hydromodpy.publication.v1", current=PUBLICATION_SCHEMA
)
"""Versions of ``PUBLICATION.json`` this code reads."""

PUBLISHED_SCHEMA: Final[str] = "hydromodpy.published.v1"
"""Schema id of one line of ``published.jsonl``."""

PUBLISHED_VERSIONS: Final[VersionWindow] = VersionWindow(
    oldest="hydromodpy.published.v1", current=PUBLISHED_SCHEMA
)
"""Versions of one line of ``published.jsonl`` this code reads."""

REDACTED_PATH: Final[str] = "<absolute path>"
"""What an absolute path outside the project becomes."""

REDACTED_KEYS: Final[frozenset[str]] = frozenset(
    {"host", "hostname", "user", "username", "user_name"}
)
"""Keys removed from any published document, at any depth."""

PROJECT_REL_DIR: Final[str] = "."
"""``rel_dir`` of the source of a project copy: the project root itself."""

PublicationFormat = Annotated[str, Vocabulary("dir", "tar")]
PublicationExtra = Annotated[str, Vocabulary("results", "inputs")]
PublicationKind = Annotated[str, Vocabulary("run", "summary", "project")]


class PublicationSource(HydroModelBase):
    """The run or summary a copy was made from."""

    project: str = Field(description="Project of the source")
    rel_dir: str = Field(
        description=(
            "Directory of the source, relative to the project root; summary for a summary, "
            ". for a whole project"
        )
    )
    sim_id: str | None = Field(
        default=None, description="Id of the run; none for a summary or a project"
    )

    @field_validator("rel_dir")
    @classmethod
    def _rel_dir(cls, value: str) -> str:
        if value in (SUMMARY_DIRNAME, PROJECT_REL_DIR):
            return value
        return checked_rel_dir(value)


class PublicationMember(HydroModelBase):
    """One copy a project copy holds: a run or the summary, a folder or a tar."""

    name: str = Field(description="Folder or .tar of the member, directly under the copy")
    rel_dir: str = Field(
        description="Directory of the member's source, relative to the project root"
    )
    manifest_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
        description="Digest of the sealed manifest of the run; none for the summary",
    )
    publication_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$", description="Digest of the member's own PUBLICATION.json"
    )

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        if not value or value in (".", "..") or "/" in value or "\\" in value:
            raise ValueError(f"{value!r} is not an entry name directly under the copy")
        return value

    @field_validator("rel_dir")
    @classmethod
    def _rel_dir(cls, value: str) -> str:
        if value == SUMMARY_DIRNAME:
            return value
        return checked_rel_dir(value)


class Publication(HydroModelBase):
    """``PUBLICATION.json``: what a published copy is."""

    model_config = ConfigDict(populate_by_name=True)

    schema_: str = Field(default=PUBLICATION_SCHEMA, alias="schema", description="Schema id")
    kind: PublicationKind = Field(
        default="run", description="What the copy is: one run, the summary or a whole project"
    )
    source: PublicationSource
    manifest_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$", description="Digest of the sealed manifest"
    )
    files: dict[str, str] = Field(
        default_factory=dict, description="Relative path of each copied file to its sha256"
    )
    label: Label | None = Field(default=None, description="Label of the source on the day")
    label_date: date | None = Field(default=None, description="Day the label was computed")
    hydromodpy_version: str = Field(description="Version that published")
    published_at: datetime = Field(description="Instant of the copy, UTC")
    format: PublicationFormat = Field(description="dir or tar")
    with_: list[PublicationExtra] = Field(
        default_factory=list, alias="with", description="What was taken along"
    )
    members: list[PublicationMember] = Field(
        default_factory=list,
        description="The copies a project copy holds, one per run and one for the summary",
    )

    @model_validator(mode="after")
    def _schema(self) -> Publication:
        if not PUBLICATION_VERSIONS.holds(self.schema_):
            raise ValueError(
                f"schema is {self.schema_!r}, this module reads {PUBLICATION_SCHEMA!r}"
            )
        return self

    @model_validator(mode="after")
    def _kind(self) -> Publication:
        rel_dir = self.source.rel_dir
        expected = {"summary": SUMMARY_DIRNAME, "project": PROJECT_REL_DIR}.get(self.kind)
        if expected is not None and rel_dir != expected:
            raise ValueError(f"a {self.kind} copy has source.rel_dir {expected!r}, not {rel_dir!r}")
        if self.kind == "run" and rel_dir in (SUMMARY_DIRNAME, PROJECT_REL_DIR):
            raise ValueError(
                f"a run copy names its run directory in source.rel_dir, not {rel_dir!r}"
            )
        if self.kind != "project" and self.members:
            raise ValueError(f"only a project copy lists members, not a {self.kind} copy")
        names = [member.name for member in self.members]
        if len(set(names)) != len(names):
            raise ValueError("a project copy lists each member once")
        return self


class PublishedLine(HydroModelBase):
    """One line of ``published.jsonl``: where a copy went."""

    model_config = ConfigDict(populate_by_name=True)

    schema_: str = Field(default=PUBLISHED_SCHEMA, alias="schema", description="Schema id")
    to: str = Field(description="Destination of the copy, as given")
    format: PublicationFormat
    published_at: datetime = Field(description="Instant of the copy, UTC")
    publication_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$", description="Digest of the PUBLICATION.json written there"
    )


def publication_path(directory: str | Path) -> Path:
    """Return ``<copy>/PUBLICATION.json``."""
    return Path(directory) / PUBLICATION_FILENAME


def write_publication(directory: str | Path, publication: Publication) -> Path:
    """Write ``PUBLICATION.json`` in a copy and return its path."""
    return write_json_atomic(
        publication_path(directory), publication.model_dump(mode="json", by_alias=True)
    )


def read_publication(directory: str | Path) -> Publication:
    """Read ``PUBLICATION.json`` of a copy."""
    return read_stored(
        Publication, read_sealed_json(publication_path(directory), PUBLICATION_VERSIONS)
    )


def published_path(source_dir: str | Path) -> Path:
    """Return ``<source>/published.jsonl``."""
    return Path(source_dir) / RUN_PUBLISHED_FILENAME


def append_published(source_dir: str | Path, line: PublishedLine) -> Path:
    """Append one line to ``published.jsonl`` of a source and return its path."""
    target = published_path(source_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(line.model_dump(mode="json", by_alias=True), ensure_ascii=False) + "\n"
    fd = os.open(target, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, text.encode("utf-8"))
    finally:
        os.close(fd)
    return target


def read_published(source_dir: str | Path) -> list[PublishedLine]:
    """Return every line of ``published.jsonl``, empty when nothing was published."""
    target = published_path(source_dir)
    if not target.is_file():
        return []
    complete = target.read_text(encoding="utf-8").split("\n")[:-1]
    return [
        read_stored(
            PublishedLine,
            check_sealed(json.loads(text), PUBLISHED_VERSIONS, path=target, line=number),
        )
        for number, text in enumerate(complete, start=1)
        if text.strip()
    ]


_POSIX_ABSOLUTE = re.compile(r"(?<![\w:/])/(?:[^\s\"'<>|/]+)(?:/[^\s\"'<>|/]*)*")
_WINDOWS_ABSOLUTE = re.compile(r"(?<!\w)[A-Za-z]:[\\/][^\s\"'<>|]*")


def redact(payload: Mapping[str, Any], *, project_root: Path | None) -> dict[str, Any]:
    """Return *payload* without host, user or absolute path, at any depth.

    A key of :data:`REDACTED_KEYS` is dropped. A string that is, or holds,
    an absolute path has it replaced: by its path relative to *project_root*
    when it lies under it, by :data:`REDACTED_PATH` otherwise. Lists and
    nested mappings are walked; anything else is kept as it is.
    """
    root = None if project_root is None else Path(project_root).resolve()
    return {
        key: _redact_value(value, root)
        for key, value in payload.items()
        if key not in REDACTED_KEYS
    }


def _redact_value(value: Any, root: Path | None) -> Any:
    if isinstance(value, Mapping):
        return {k: _redact_value(v, root) for k, v in value.items() if k not in REDACTED_KEYS}
    if isinstance(value, list):
        return [_redact_value(item, root) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_value(item, root) for item in value)
    if isinstance(value, str):
        return _redact_text(value, root)
    return value


def _redact_text(text: str, root: Path | None) -> str:
    def posix(match: re.Match[str]) -> str:
        return _relative_or_redacted(PurePosixPath(match.group(0)), root)

    def windows(match: re.Match[str]) -> str:
        return _relative_or_redacted(PureWindowsPath(match.group(0)), root)

    text = _WINDOWS_ABSOLUTE.sub(windows, text)
    return _POSIX_ABSOLUTE.sub(posix, text)


def _relative_or_redacted(path: PurePosixPath | PureWindowsPath, root: Path | None) -> str:
    if root is not None:
        try:
            return Path(path).resolve().relative_to(root).as_posix()
        except ValueError:
            pass
    return REDACTED_PATH


__all__ = [
    "PUBLICATION_SCHEMA",
    "PUBLICATION_VERSIONS",
    "PROJECT_REL_DIR",
    "PUBLISHED_SCHEMA",
    "PUBLISHED_VERSIONS",
    "REDACTED_KEYS",
    "REDACTED_PATH",
    "Publication",
    "PublicationConfig",
    "PublicationExtra",
    "PublicationFormat",
    "PublicationKind",
    "PublicationMember",
    "PublicationSource",
    "PublishedLine",
    "append_published",
    "publication_path",
    "published_path",
    "read_publication",
    "read_published",
    "redact",
    "write_publication",
]
