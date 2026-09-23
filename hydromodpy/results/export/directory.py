"""FAIR views of a sealed run or job directory, read from the directory alone.

:func:`~hydromodpy.results.export.context.build_context` collects a
simulation from the catalog, and so needs a workspace, a DuckDB index and a
``sim_id``. A run or a job directory handed to somebody else carries none of
them. This module builds the same :class:`FairExportContext` from the seal and
the documents beside it, and writes the views into that directory.

Three rules, each one a way the catalog path goes wrong for a directory.

**A view renders the seal and nothing else.** It reads ``manifest.json``,
``provenance.json`` and, for a job, ``inputset.json`` and ``outcome.json``.
It never hashes an artefact again, never opens a workspace file and never
reads the clock: it is dated by ``sealed_at``. Rendering it twice gives the
same bytes, so a view can be deleted and written again at any time.

**Every href is relative to the directory.** The crate root ``./`` of the
RO-Crate is the directory that holds ``ro-crate-metadata.json``, and the STAC
assets resolve against ``stac-item.json``. A view written under ``share/``
names paths that resolve nowhere.

**Nothing is claimed that the directory does not say.** A run directory
records no licence, so its views say ``LicenseRef-undetermined`` rather than a
default. A bounding box is written in WGS84, as STAC and schema.org require,
and only when the directory names the CRS of the box it records.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any
from uuid import uuid4

from hydromodpy.core.exceptions import ExportError
from hydromodpy.core.io.atomic_replace import rename_over_open_file
from hydromodpy.results.export.context import AssetEntry, FairExportContext, InputEntry
from hydromodpy.results.storage.contract import RUN_MANIFEST_FILENAME, RUN_PROVENANCE_FILENAME
from hydromodpy.schema.generated_views import VIEW_FILENAMES
from hydromodpy.schema.job.digest import sha256_file
from hydromodpy.schema.job.inputset import UNDETERMINED
from hydromodpy.schema.job.layout import (
    INPUTSET_FILENAME,
    JOB_PROVENANCE_FILENAME,
    OUTCOME_FILENAME,
)
from hydromodpy.schema.job.seal import JOB_PROFILE
from hydromodpy.schema.media_types import (
    JSON_MEDIA_TYPE,
    OCTET_STREAM_MEDIA_TYPE,
    PARQUET_MEDIA_TYPE,
    TOML_MEDIA_TYPE,
    ZARR_MEDIA_TYPE,
)

_RUN_FORMAT_MEDIA_TYPES: dict[str, str] = {
    "json": JSON_MEDIA_TYPE,
    "toml": TOML_MEDIA_TYPE,
    "zarr": ZARR_MEDIA_TYPE,
    "parquet": PARQUET_MEDIA_TYPE,
}
"""The ``format`` labels of a run manifest that name a type the table holds.

Any other label, a figure's ``png`` included, is written as an octet stream:
the run manifest records a suffix, not a type, and a view does not guess one.
"""

_LICENCE_URLS: dict[str, str] = {
    "cc-by-4.0": "https://creativecommons.org/licenses/by/4.0/",
    "cc-by-sa-4.0": "https://creativecommons.org/licenses/by-sa/4.0/",
    "cc0-1.0": "https://creativecommons.org/publicdomain/zero/1.0/",
    "etalab-2.0": "https://spdx.org/licenses/etalab-2.0",
}
"""SPDX ids the exporters already know by URL. Any other id is kept as it is."""

_WGS84_EPSG = 4326
_EPSG_PREFIX = "EPSG:"


def context_from_directory(directory: Path | str) -> FairExportContext:
    """Build the export context of a sealed run or job directory.

    The profile is read off the seal: a job manifest says ``"profile":
    "job"``, a run manifest carries ``manifest_version``. An unsealed
    directory is refused, because a view renders the seal and there is none.
    """
    root = Path(directory)
    manifest_path = root / RUN_MANIFEST_FILENAME
    if not manifest_path.is_file():
        raise ExportError(
            f"{root} carries no {RUN_MANIFEST_FILENAME}: it is not sealed, "
            "and a generated view renders the seal"
        )
    manifest = _read_object(manifest_path)
    if manifest.get("profile") == JOB_PROFILE:
        return _job_context(root, manifest)
    if "manifest_version" in manifest:
        return _run_context(root, manifest)
    raise ExportError(
        f"{manifest_path} is neither a run manifest nor a job manifest; "
        "no view can be rendered from it"
    )


def write_view(path: Path, payload: Any) -> Path:
    """Write one view whole, through a temporary file and one rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp-{uuid4().hex}")
    tmp.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    rename_over_open_file(tmp, path)
    return path


def write_views(
    directory: Path | str,
    formats: Iterable[str] = tuple(VIEW_FILENAMES),
) -> tuple[Path, ...]:
    """Write the requested views of a sealed directory inside it.

    *formats* takes the names ``hmp data export --format`` uses: ``rocrate``,
    ``stac`` and ``prov``. The context is built once and shared by all three,
    so they describe the same seal.
    """
    from hydromodpy.results.export.prov import write_prov_view
    from hydromodpy.results.export.rocrate import write_ro_crate_view
    from hydromodpy.results.export.stac import write_stac_item_view

    writers = {
        "rocrate": write_ro_crate_view,
        "stac": write_stac_item_view,
        "prov": write_prov_view,
    }
    requested = tuple(dict.fromkeys(formats))
    unknown = [name for name in requested if name not in writers]
    if unknown:
        raise ValueError(
            f"unknown view format(s) {', '.join(unknown)}; expected one of {', '.join(writers)}"
        )
    root = Path(directory)
    context = context_from_directory(root)
    return tuple(writers[name](root, context=context) for name in requested)


# ---------------------------------------------------------------------------
# run profile
# ---------------------------------------------------------------------------


def _run_context(root: Path, manifest: Mapping[str, Any]) -> FairExportContext:
    """Read a run directory: its seal, and the provenance the seal hashes."""
    run = _mapping(manifest.get("run"))
    geometry = _mapping(manifest.get("geometry"))
    period = _mapping(manifest.get("period"))
    provenance = _optional_object(root / RUN_PROVENANCE_FILENAME)
    solver = _mapping(provenance.get("solver"))
    git = _mapping(provenance.get("git"))
    environment = _mapping(provenance.get("environment"))

    epsg = _int_or_none(geometry.get("crs_epsg"))
    crs_wkt = geometry.get("crs_wkt")
    sim_row: dict[str, Any] = {
        "name": run.get("name"),
        "description": run.get("description"),
        "project": run.get("project"),
        "n_cells": geometry.get("n_cells"),
        "n_layers": geometry.get("n_layers"),
        "n_timesteps": period.get("n_timesteps"),
        "crs_epsg": epsg,
        # 72 of 78 real manifests hold an EPSG code in this field, not WKT.
        "crs_wkt": crs_wkt if _is_wkt(crs_wkt) else None,
        "doi": run.get("doi"),
        "contact_email": run.get("contact_email"),
        "started_at": run.get("started_at"),
        "ended_at": run.get("ended_at"),
        "period_start": period.get("start"),
        "period_end": period.get("end"),
        **_bbox_columns(_wgs84_bbox(geometry.get("bbox"), epsg)),
    }
    sim_id = str(run.get("sim_id") or root.name)
    return FairExportContext(
        sim_id=sim_id,
        sim_row=sim_row,
        runs_env={
            "git_commit": git.get("commit"),
            "rng_seed": environment.get("rng_seed"),
        },
        workspace_meta={},
        workspace_path=root,
        license_url=UNDETERMINED.spdx,
        creator_name=None,
        creator_email=_text_or_none(run.get("contact_email")),
        assets=(_seal_asset(root), *_run_assets(manifest.get("artifacts"))),
        inputs=tuple(_run_inputs(manifest.get("inputs"))),
        lockfile_path=None,
        solver_binary_sha256=_text_or_none(solver.get("binary_sha256")),
        solver_name=_text_or_none(solver.get("name")),
        solver_version=_text_or_none(solver.get("version")),
        hydromodpy_version=str(_mapping(provenance.get("tool")).get("version") or "unknown"),
        generated_at=str(manifest.get("sealed_at") or ""),
    )


def _run_assets(entries: Any) -> list[AssetEntry]:
    """Turn the artefact list of a run seal into assets, the seal itself aside."""
    assets: list[AssetEntry] = []
    for entry in _records(entries):
        path = str(entry.get("path") or "")
        if not path or path == RUN_MANIFEST_FILENAME:
            continue
        role = str(entry.get("role") or "other")
        assets.append(
            AssetEntry(
                key=path,
                relative_path=path,
                media_type=_RUN_FORMAT_MEDIA_TYPES.get(
                    str(entry.get("format") or ""), OCTET_STREAM_MEDIA_TYPE
                ),
                roles=(_stac_role(role), role),
                sha256=_text_or_none(entry.get("sha256")),
                size_bytes=_int_or_none(entry.get("bytes")),
            )
        )
    return assets


def _run_inputs(entries: Any) -> list[InputEntry]:
    """Turn the input list of a run seal into input entries.

    Only the file name of a recorded path reaches a view: the seal stores the
    absolute path the run read, which names the account that ran it.
    """
    return [
        InputEntry(
            role=str(entry.get("role") or "input"),
            category=str(entry.get("category") or ""),
            original_path=Path(str(entry.get("path") or "")).name,
            sha256=str(entry.get("sha256") or ""),
            size_bytes=_int_or_none(entry.get("bytes")) or 0,
        )
        for entry in _records(entries)
    ]


def _stac_role(role: str) -> str:
    """Map a run artefact role onto the STAC asset role vocabulary."""
    if role in ("fields", "data") or role.startswith("table:"):
        return "data"
    if role == "figure":
        return "visual"
    return "metadata"


# ---------------------------------------------------------------------------
# job profile
# ---------------------------------------------------------------------------


def _job_context(root: Path, manifest: Mapping[str, Any]) -> FairExportContext:
    """Read a job directory: its seal and the three documents the seal hashes."""
    inputset = _optional_object(root / INPUTSET_FILENAME)
    provenance = _optional_object(root / JOB_PROVENANCE_FILENAME)
    outcome = _optional_object(root / OUTCOME_FILENAME)
    process = _mapping(outcome.get("process")) or _mapping(provenance.get("process"))
    backend = _mapping(provenance.get("backend"))
    resources = _records(inputset.get("resources"))

    geometry = _mapping(manifest.get("geometry"))
    bbox = _extent_wgs84_bbox(geometry) or _union_bbox(
        _extent_wgs84_bbox(_mapping(resource.get("spatial"))) for resource in resources
    )
    job_id = str(manifest.get("job_id") or outcome.get("job_id") or root.name)
    process_label = " ".join(
        str(part) for part in (process.get("id"), process.get("version")) if part
    )
    sim_row: dict[str, Any] = {
        "name": process_label or job_id,
        "description": f"HydroModPy job {job_id}",
        "crs_epsg": _epsg(geometry.get("crs")) or _shared_epsg(resources),
        "crs_wkt": geometry.get("crs_wkt2"),
        "started_at": outcome.get("started_at"),
        "ended_at": outcome.get("finished_at"),
        **_bbox_columns(bbox),
    }
    rollup = _mapping(inputset.get("licence_rollup"))
    return FairExportContext(
        sim_id=job_id,
        sim_row=sim_row,
        runs_env={"git_commit": _mapping(provenance.get("git")).get("commit")},
        workspace_meta={},
        workspace_path=root,
        license_url=_licence_reference(str(rollup.get("expression") or UNDETERMINED.spdx)),
        creator_name=None,
        creator_email=None,
        assets=(_seal_asset(root), *_job_assets(manifest.get("artifacts"))),
        inputs=tuple(_job_input(resource) for resource in resources),
        lockfile_path=None,
        solver_binary_sha256=_text_or_none(backend.get("sha256")),
        solver_name=_text_or_none(backend.get("name") or backend.get("id")),
        solver_version=_text_or_none(backend.get("version")),
        hydromodpy_version=str(_mapping(provenance.get("tool")).get("version") or "unknown"),
        generated_at=str(manifest.get("sealed_at") or ""),
    )


def _job_assets(entries: Any) -> list[AssetEntry]:
    """Turn the artefact list of a job seal into assets, digests included."""
    assets: list[AssetEntry] = []
    for entry in _records(entries):
        path = str(entry.get("path") or "")
        if not path:
            continue
        is_output = "/" in path
        assets.append(
            AssetEntry(
                key=path,
                relative_path=path,
                media_type=str(entry.get("mediaType") or OCTET_STREAM_MEDIA_TYPE),
                roles=("data",) if is_output else ("metadata",),
                sha256=_text_or_none(entry.get("sha256")),
                size_bytes=_int_or_none(entry.get("bytes")),
            )
        )
    return assets


def _job_input(resource: Mapping[str, Any]) -> InputEntry:
    """Turn one resource of ``inputset.json`` into an input entry."""
    source = _mapping(resource.get("source"))
    licence = _mapping(resource.get("licence"))
    href = str(resource.get("href") or "")
    return InputEntry(
        role=str(resource.get("role") or resource.get("name") or "input"),
        category="input",
        original_path=Path(href).name or str(resource.get("name") or ""),
        sha256=str(resource.get("sha256") or ""),
        size_bytes=_int_or_none(resource.get("bytes")) or 0,
        source_type=_text_or_none(source.get("slug")),
        source_ref=_text_or_none(source.get("endpoint")),
        license=_text_or_none(licence.get("spdx")),
        data_provider=_text_or_none(source.get("publisher")),
        fetched_at=_text_or_none(source.get("fetched_at")),
    )


def _extent_wgs84_bbox(extent: Mapping[str, Any]) -> tuple[float, float, float, float] | None:
    """Return the WGS84 box of a job extent, in either of its two spellings.

    Boundary-spec §4 writes ``bbox_wgs84``. The fetch worker writes the box
    it measured, ``bbox``, in the CRS it names under ``crs``. That box is
    reprojected, as the run profile does.
    """
    return _bbox_or_none(extent.get("bbox_wgs84")) or _wgs84_bbox(
        extent.get("bbox"), _epsg(extent.get("crs"))
    )


def _shared_epsg(resources: Sequence[Mapping[str, Any]]) -> int | None:
    """Return the EPSG code every spatial input agrees on, or ``None``."""
    codes = {
        _epsg(_mapping(resource.get("spatial")).get("crs"))
        for resource in resources
        if resource.get("spatial")
    }
    codes.discard(None)
    return codes.pop() if len(codes) == 1 else None


def _licence_reference(expression: str) -> str:
    """Return the URL the exporters use for a known SPDX id, else the id."""
    return _LICENCE_URLS.get(expression.strip().lower(), expression)


# ---------------------------------------------------------------------------
# shared readers
# ---------------------------------------------------------------------------


def _seal_asset(root: Path) -> AssetEntry:
    """Name the seal as an asset, hashed from its bytes.

    A seal cannot record its own digest. The view records it, which ties the
    view to the one seal it was rendered from.
    """
    digest, size = sha256_file(root / RUN_MANIFEST_FILENAME)
    return AssetEntry(
        key=RUN_MANIFEST_FILENAME,
        relative_path=RUN_MANIFEST_FILENAME,
        media_type=JSON_MEDIA_TYPE,
        roles=("metadata", "manifest"),
        sha256=digest,
        size_bytes=size,
        description="Seal of this directory, written last.",
    )


def _wgs84_bbox(bbox: Any, epsg: int | None) -> tuple[float, float, float, float] | None:
    """Reproject a native bounding box to WGS84 longitude and latitude.

    A box whose CRS is not named is dropped rather than written as if it were
    in degrees: a synthetic model in metres would land in the Gulf of Guinea.
    """
    native = _bbox_or_none(bbox)
    if native is None or epsg is None:
        return None
    if epsg == _WGS84_EPSG:
        return native
    from pyproj import Transformer
    from pyproj.exceptions import CRSError

    try:
        transformer = Transformer.from_crs(epsg, _WGS84_EPSG, always_xy=True)
    except CRSError:
        return None
    xmin, ymin, xmax, ymax = transformer.transform_bounds(*native)
    return (float(xmin), float(ymin), float(xmax), float(ymax))


def _bbox_columns(bbox: tuple[float, float, float, float] | None) -> dict[str, float]:
    """Spell a box the way :attr:`FairExportContext.bbox` reads it."""
    if bbox is None:
        return {}
    keys = ("bbox_xmin", "bbox_ymin", "bbox_xmax", "bbox_ymax")
    return dict(zip(keys, bbox, strict=True))


def _bbox_or_none(value: Any) -> tuple[float, float, float, float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        xmin, ymin, xmax, ymax = (float(v) for v in value)
    except (TypeError, ValueError):
        return None
    return (xmin, ymin, xmax, ymax)


def _union_bbox(
    boxes: Iterable[tuple[float, float, float, float] | None],
) -> tuple[float, float, float, float] | None:
    present = [box for box in boxes if box is not None]
    if not present:
        return None
    xmins, ymins, xmaxs, ymaxs = zip(*present, strict=True)
    return (min(xmins), min(ymins), max(xmaxs), max(ymaxs))


def _epsg(value: Any) -> int | None:
    """Read ``EPSG:2154`` or ``2154`` as an EPSG code."""
    if value is None:
        return None
    text = str(value).strip()
    if text.upper().startswith(_EPSG_PREFIX):
        text = text[len(_EPSG_PREFIX) :]
    return _int_or_none(text)


def _is_wkt(value: Any) -> bool:
    return isinstance(value, str) and "[" in value


def _int_or_none(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _text_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _records(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [entry for entry in value if isinstance(entry, Mapping)]


def _read_object(path: Path) -> Mapping[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExportError(f"{path} cannot be read as JSON: {exc}") from exc
    if not isinstance(document, Mapping):
        raise ExportError(f"{path} is not a JSON object")
    return document


def _optional_object(path: Path) -> Mapping[str, Any]:
    """Read a document the seal hashes, empty when the directory lacks it."""
    if not path.is_file():
        return {}
    return _read_object(path)


__all__ = [
    "context_from_directory",
    "write_view",
    "write_views",
]
