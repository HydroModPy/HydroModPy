"""What a job consumed, as one object: resolved, hashed, licence-annotated.

Before this, three per-file records hashed the same bytes independently and
never referenced each other, so there was nothing to attach a licence to,
nothing to cite, and nothing to hand an orchestrator. ``inputset.json`` is
that object, and its own digest covers the **complete** resource array: a
licence, a CRS or a fetch query rewritten after the fact changes the id, which
is the only claim a digest of three chosen fields could never support.

Four rules this module enforces, each answering a measured defect:

- an unknown licence is ``LicenseRef-undetermined``, never a default;
- the licence is per resource, because one job legitimately mixes a
  share-alike database with an attribution-only one;
- the rollup carries the **lowest** confidence of any member;
- a rollup never refuses to seal. It records the fact and the job goes on.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from hydromodpy.core.licensing import UNDETERMINED_LICENSE
from hydromodpy.schema.job.digest import sha256_file, sha256_value

INPUTSET_SCHEMA = "hmp-inputset/v1"

Confidence = Literal["declared", "assumed", "undetermined"]

_CONFIDENCE_ORDER: tuple[Confidence, ...] = ("undetermined", "assumed", "declared")


@dataclass(frozen=True, slots=True)
class Licence:
    """The licence of one resource, and how sure this repository is of it."""

    spdx: str = UNDETERMINED_LICENSE
    url: str | None = None
    attribution: str | None = None
    share_alike: bool = False
    confidence: Confidence = "undetermined"

    def to_document(self) -> dict[str, Any]:
        document: dict[str, Any] = {
            "spdx": self.spdx,
            "share_alike": self.share_alike,
            "confidence": self.confidence,
        }
        if self.url is not None:
            document["url"] = self.url
        if self.attribution is not None:
            document["attribution"] = self.attribution
        return document


UNDETERMINED = Licence()
"""The licence of every resource nobody declared one for."""


@dataclass(frozen=True, slots=True)
class InputResource:
    """One thing the job read, named by the role it was read for."""

    name: str
    role: str
    href: str
    media_type: str | None = None
    bytes: int | None = None
    sha256: str | None = None
    copied_to: str | None = None
    spatial: Mapping[str, Any] | None = None
    temporal: Mapping[str, Any] | None = None
    source: Mapping[str, Any] | None = None
    licence: Licence = UNDETERMINED

    def to_document(self) -> dict[str, Any]:
        """Render the resource as the object its digest is computed over."""
        return {
            "name": self.name,
            "role": self.role,
            "href": self.href,
            "copied_to": self.copied_to,
            "mediaType": self.media_type,
            "bytes": self.bytes,
            "sha256": self.sha256,
            "spatial": dict(self.spatial) if self.spatial is not None else None,
            "temporal": dict(self.temporal) if self.temporal is not None else None,
            "source": dict(self.source) if self.source is not None else None,
            "licence": self.licence.to_document(),
        }


@dataclass(frozen=True, slots=True)
class LicenceRollup:
    """What the whole input set allows, computed from its members."""

    expression: str
    redistributable: bool
    share_alike: bool
    confidence: Confidence
    attribution: tuple[str, ...] = ()

    def to_document(self) -> dict[str, Any]:
        return {
            "expression": self.expression,
            "redistributable": self.redistributable,
            "share_alike": self.share_alike,
            "confidence": self.confidence,
            "attribution": list(self.attribution),
        }


@dataclass(frozen=True, slots=True)
class InputSet:
    """The resolved input set of one job, with its own content address."""

    resources: tuple[InputResource, ...]
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    @property
    def rollup(self) -> LicenceRollup:
        return roll_up_licences(resource.licence for resource in self.resources)

    @property
    def id(self) -> str:
        """The digest of the complete resource array, every key included."""
        payload = [resource.to_document() for resource in self.resources]
        return f"sha256:{sha256_value(payload)}"

    def to_document(self) -> dict[str, Any]:
        return {
            "schema": INPUTSET_SCHEMA,
            "id": self.id,
            "created_at": self.created_at,
            "resources": [resource.to_document() for resource in self.resources],
            "licence_rollup": self.rollup.to_document(),
        }


def roll_up_licences(licences: Iterable[Licence]) -> LicenceRollup:
    """Combine per-resource licences into what the job as a whole allows.

    Never a refusal: an input set whose licences are unknown is recorded as
    unknown and sealed, because refusing to seal on a licence heuristic loses
    the results of a run that already happened.
    """
    members = tuple(licences)
    if not members:
        return LicenceRollup(
            expression=UNDETERMINED_LICENSE,
            redistributable=False,
            share_alike=False,
            confidence="undetermined",
        )
    tokens = sorted({licence.spdx for licence in members})
    expression = tokens[0] if len(tokens) == 1 else " AND ".join(tokens)
    confidence = _CONFIDENCE_ORDER[
        min(_CONFIDENCE_ORDER.index(licence.confidence) for licence in members)
    ]
    attribution = tuple(sorted({licence.attribution for licence in members if licence.attribution}))
    return LicenceRollup(
        expression=expression,
        redistributable=all(licence.spdx != UNDETERMINED_LICENSE for licence in members),
        share_alike=any(licence.share_alike for licence in members),
        confidence=confidence,
        attribution=attribution,
    )


def file_resource(
    name: str,
    *,
    role: str,
    path: str | Path,
    href: str | None = None,
    media_type: str | None = None,
    licence: Licence = UNDETERMINED,
    spatial: Mapping[str, Any] | None = None,
    temporal: Mapping[str, Any] | None = None,
    source: Mapping[str, Any] | None = None,
) -> InputResource:
    """Describe a file the job read, hashing the bytes it actually read."""
    digest, size = sha256_file(path)
    return InputResource(
        name=name,
        role=role,
        href=href if href is not None else str(path),
        media_type=media_type,
        bytes=size,
        sha256=digest,
        spatial=spatial,
        temporal=temporal,
        source=source,
        licence=licence,
    )


def inline_resource(
    name: str,
    *,
    role: str,
    value: Any,
    pointer: str,
    licence: Licence = UNDETERMINED,
) -> InputResource:
    """Describe an input the request carried inline, by JSON Pointer.

    Its ``href`` names the member of ``request.json`` that holds it, so the
    input set stays re-readable from the job directory alone: the value is in
    the directory already and is not copied a second time.
    """
    return InputResource(
        name=name,
        role=role,
        href=f"request.json#{pointer}",
        media_type="application/json",
        sha256=sha256_value(value),
        licence=licence,
    )


def build_inputset(resources: Sequence[InputResource]) -> InputSet:
    """Assemble the input set, refusing two resources under one name."""
    names = [resource.name for resource in resources]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise ValueError(f"input set repeats the resource name(s) {duplicates}")
    return InputSet(resources=tuple(resources))


__all__ = [
    "INPUTSET_SCHEMA",
    "UNDETERMINED",
    "Confidence",
    "InputResource",
    "InputSet",
    "Licence",
    "LicenceRollup",
    "build_inputset",
    "file_resource",
    "inline_resource",
    "roll_up_licences",
]
