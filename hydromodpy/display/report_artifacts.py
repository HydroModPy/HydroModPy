"""Generic artifact contract for optional HTML reports."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

REPORT_ARTIFACT_MANIFEST_SCHEMA = "hydromodpy.report_artifact_manifest.v1"

ArtifactKind = Literal["figure", "json", "table", "html", "toml", "directory", "file"]
ArtifactStatus = Literal["present", "missing"]


@dataclass(frozen=True)
class HtmlReportIntent:
    """Resolved intent for an optional HTML report."""

    enabled: bool = False
    build_at_end: bool = False
    profile: str | None = None
    strict: bool = False

    @classmethod
    def from_mapping(
        cls,
        payload: Any,
        *,
        default_profile: str | None = None,
    ) -> HtmlReportIntent:
        """Resolve ``[report.html]`` semantics from a TOML-like mapping.

        ``build_at_end = true`` implies ``enabled = true``. ``strict`` defaults
        to ``False`` so ordinary reports degrade around optional missing
        artifacts instead of failing the simulation.
        """

        if payload is None:
            return cls(profile=default_profile)
        if not isinstance(payload, Mapping):
            raise ValueError("[report.html] must be a table when provided.")

        build_at_end = _optional_bool_with_default(payload, "build_at_end", False)
        enabled_value = _optional_bool(payload, "enabled")
        enabled = build_at_end or bool(enabled_value)
        profile = _optional_string(payload, "profile") or default_profile
        strict = _optional_bool_with_default(payload, "strict", False)
        return cls(
            enabled=enabled,
            build_at_end=build_at_end,
            profile=profile,
            strict=strict,
        )


@dataclass(frozen=True)
class ReportArtifactRequirement:
    """One artifact expected by a report profile."""

    artifact_id: str
    kind: ArtifactKind = "file"
    required: bool = True
    title: str = ""
    producer: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "artifact_id": self.artifact_id,
            "kind": self.kind,
            "required": self.required,
        }
        if self.title:
            payload["title"] = self.title
        if self.producer:
            payload["producer"] = self.producer
        if self.metadata:
            payload["metadata"] = dict(self.metadata)
        return payload


@dataclass(frozen=True)
class ReportArtifact:
    """One resolved artifact instance for a report build."""

    artifact_id: str
    kind: ArtifactKind = "file"
    status: ArtifactStatus = "missing"
    path: Path | None = None
    required: bool = True
    producer: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_requirement(
        cls,
        requirement: ReportArtifactRequirement,
        *,
        path: Path | None,
    ) -> ReportArtifact:
        return cls(
            artifact_id=requirement.artifact_id,
            kind=requirement.kind,
            status="present" if path is not None and path.exists() else "missing",
            path=path,
            required=requirement.required,
            producer=requirement.producer,
            metadata=requirement.metadata,
        )

    def to_dict(self, *, base_dir: Path | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "artifact_id": self.artifact_id,
            "kind": self.kind,
            "status": self.status,
            "required": self.required,
        }
        if self.path is not None:
            payload["path"] = _format_path(self.path, base_dir=base_dir)
        if self.producer:
            payload["producer"] = self.producer
        if self.metadata:
            payload["metadata"] = dict(self.metadata)
        return payload


@dataclass(frozen=True)
class ReportArtifactManifest:
    """Resolved artifact contract for one report build."""

    profile: str
    requirements: tuple[ReportArtifactRequirement, ...]
    artifacts: tuple[ReportArtifact, ...]
    source_manifest: Path | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = REPORT_ARTIFACT_MANIFEST_SCHEMA

    @property
    def missing_required(self) -> tuple[str, ...]:
        return tuple(
            artifact.artifact_id
            for artifact in self.artifacts
            if artifact.required and artifact.status != "present"
        )

    @property
    def missing_optional(self) -> tuple[str, ...]:
        return tuple(
            artifact.artifact_id
            for artifact in self.artifacts
            if not artifact.required and artifact.status != "present"
        )

    def to_dict(self, *, base_dir: Path | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "profile": self.profile,
            "summary": {
                "requirement_count": len(self.requirements),
                "artifact_count": len(self.artifacts),
                "present_count": sum(1 for item in self.artifacts if item.status == "present"),
                "missing_required_count": len(self.missing_required),
                "missing_optional_count": len(self.missing_optional),
            },
            "requirements": [item.to_dict() for item in self.requirements],
            "artifacts": [item.to_dict(base_dir=base_dir) for item in self.artifacts],
        }
        if self.source_manifest is not None:
            payload["source_manifest"] = _format_path(self.source_manifest, base_dir=base_dir)
        if self.metadata:
            payload["metadata"] = dict(self.metadata)
        return payload

    def write_json(self, path: Path, *, base_dir: Path | None = None) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(base_dir=base_dir), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return path


@dataclass(frozen=True)
class ReportArtifactIndex:
    """Path lookup built from a report artifact manifest."""

    manifest_path: Path
    payload: Mapping[str, Any]
    paths_by_key: Mapping[str, Path]
    entries_by_key: Mapping[str, ReportArtifactIndexEntry]

    @classmethod
    def from_manifest(
        cls,
        path: Path,
        *,
        base_dir: Path | None = None,
    ) -> ReportArtifactIndex:
        manifest_path = Path(path).expanduser().resolve()
        payload = load_report_artifact_manifest(manifest_path)
        entries_by_key = _artifact_entries_by_key(
            payload,
            manifest_path=manifest_path,
            base_dir=base_dir,
        )
        return cls(
            manifest_path=manifest_path,
            payload=payload,
            paths_by_key={key: entry.path for key, entry in entries_by_key.items()},
            entries_by_key=entries_by_key,
        )

    @classmethod
    def from_manifests(
        cls,
        paths: Iterable[Path],
        *,
        base_dir: Path | None = None,
    ) -> ReportArtifactIndex:
        indexes = tuple(cls.from_manifest(path, base_dir=base_dir) for path in paths)
        if not indexes:
            raise ValueError("At least one report artifact manifest is required.")
        entries_by_key: dict[str, ReportArtifactIndexEntry] = {}
        for index in indexes:
            for key, entry in index.entries_by_key.items():
                entries_by_key.setdefault(key, entry)
        return cls(
            manifest_path=indexes[0].manifest_path,
            payload={"manifests": [index.payload for index in indexes]},
            paths_by_key={key: entry.path for key, entry in entries_by_key.items()},
            entries_by_key=entries_by_key,
        )

    def get(self, key: str) -> Path | None:
        return self.paths_by_key.get(key)

    def find(self, keys: Iterable[str]) -> ReportArtifactIndexEntry | None:
        for key in keys:
            entry = self.entries_by_key.get(key)
            if entry is not None:
                return entry
        return None


@dataclass(frozen=True)
class ReportArtifactIndexEntry:
    """Resolved artifact path plus manifest provenance."""

    key: str
    path: Path
    manifest_path: Path
    artifact_id: str


def _format_path(path: Path, *, base_dir: Path | None) -> str:
    resolved = path.resolve()
    if base_dir is not None:
        try:
            return resolved.relative_to(base_dir.resolve()).as_posix()
        except ValueError:
            pass
    return str(resolved)


def load_report_artifact_manifest(path: Path) -> dict[str, Any]:
    """Load a report artifact manifest JSON payload."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Report artifact manifest must be a JSON object: {path}")
    return payload


def missing_required_artifact_ids(payload: Mapping[str, Any]) -> tuple[str, ...]:
    """Return required artifact IDs whose status is not ``present``."""

    missing: list[str] = []
    for artifact in payload.get("artifacts", []) or []:
        if not isinstance(artifact, Mapping):
            continue
        if artifact.get("required") and artifact.get("status") != "present":
            artifact_id = artifact.get("artifact_id")
            if artifact_id:
                missing.append(str(artifact_id))
    return tuple(missing)


def _artifact_entries_by_key(
    payload: Mapping[str, Any],
    *,
    manifest_path: Path,
    base_dir: Path | None,
) -> Mapping[str, ReportArtifactIndexEntry]:
    entries: dict[str, ReportArtifactIndexEntry] = {}
    for artifact in payload.get("artifacts", []) or []:
        if not isinstance(artifact, Mapping):
            continue
        if artifact.get("status") != "present":
            continue
        raw_path = artifact.get("path")
        if raw_path in (None, ""):
            continue
        path = _resolve_manifest_artifact_path(
            str(raw_path),
            manifest_path=manifest_path,
            base_dir=base_dir,
        )
        artifact_id = str(artifact.get("artifact_id") or "")
        for key in _artifact_lookup_keys(artifact, raw_path=str(raw_path)):
            entries.setdefault(
                key,
                ReportArtifactIndexEntry(
                    key=key,
                    path=path,
                    manifest_path=manifest_path,
                    artifact_id=artifact_id,
                ),
            )
    return entries


def _artifact_lookup_keys(
    artifact: Mapping[str, Any],
    *,
    raw_path: str,
) -> tuple[str, ...]:
    keys: list[str] = []
    artifact_id = artifact.get("artifact_id")
    if artifact_id:
        keys.append(str(artifact_id))
    metadata = artifact.get("metadata")
    if isinstance(metadata, Mapping):
        value = metadata.get("display_figure")
        if value:
            keys.append(str(value))
    path_stem = Path(raw_path).stem
    if path_stem:
        keys.append(path_stem)
    return tuple(dict.fromkeys(keys))


def _resolve_manifest_artifact_path(
    raw_path: str,
    *,
    manifest_path: Path,
    base_dir: Path | None,
) -> Path:
    path = Path(raw_path).expanduser()
    if path.is_absolute():
        return path

    candidates: list[Path] = []
    if base_dir is not None:
        candidates.append(base_dir / path)
    workspace = _infer_workspace_from_display_manifest(manifest_path)
    if workspace is not None:
        candidates.append(workspace / path)
    candidates.append(manifest_path.parent / path)
    candidates.append(Path.cwd() / path)

    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return candidates[0].resolve()


def _infer_workspace_from_display_manifest(manifest_path: Path) -> Path | None:
    figures_root = manifest_path.parent.parent
    if figures_root.name == "figures":
        return figures_root.parent
    return None


def _optional_bool(payload: Mapping[str, Any], key: str) -> bool | None:
    value = payload.get(key)
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    raise ValueError(f"[report.html] key {key!r} must be a boolean.")


def _optional_bool_with_default(
    payload: Mapping[str, Any],
    key: str,
    default: bool,
) -> bool:
    value = _optional_bool(payload, key)
    return default if value is None else value


def _optional_string(payload: Mapping[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    return str(value)


__all__ = [
    "ArtifactKind",
    "ArtifactStatus",
    "HtmlReportIntent",
    "REPORT_ARTIFACT_MANIFEST_SCHEMA",
    "ReportArtifact",
    "ReportArtifactIndex",
    "ReportArtifactIndexEntry",
    "ReportArtifactManifest",
    "ReportArtifactRequirement",
    "load_report_artifact_manifest",
    "missing_required_artifact_ids",
]
