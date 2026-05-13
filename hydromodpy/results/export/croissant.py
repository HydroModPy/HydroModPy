"""Croissant MLCommons 1.0 manifest generator (https://docs.mlcommons.org/croissant/).

The exporter targets the ``ml_datasets``, ``ml_splits`` and ``ml_scalers``
tables defined by the v2 schema (cf.
``reports_db/15_export_formats.md §4.4`` and the migrations DDL
``0001_initial_v2_schema.sql §4.10``). Each Croissant manifest covers
exactly one dataset row and links to its parquet artefacts when they were
materialised by ``hmp ml export``.

Croissant 1.0 expects a JSON-LD document keyed by ``@context``,
``conformsTo`` and a list of ``RecordSet`` definitions. When the ML
tables are empty - the v2.0 ML stack is documented as a stub - this
module still emits a syntactically valid skeleton manifest tagged
``hydromodpy:stub`` so downstream tools see something instead of a
``FileNotFoundError``.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hydromodpy.results.export.context import _is_missing

CROISSANT_CONFORMS = "http://mlcommons.org/croissant/1.0"
CROISSANT_CONTEXT = {
    "@language": "en",
    "@vocab": "https://schema.org/",
    "citeAs": "cr:citeAs",
    "column": "cr:column",
    "conformsTo": "dct:conformsTo",
    "cr": "http://mlcommons.org/croissant/",
    "rai": "http://mlcommons.org/croissant/RAI/",
    "data": {"@id": "cr:data", "@type": "@json"},
    "dataType": {"@id": "cr:dataType", "@type": "@vocab"},
    "dct": "http://purl.org/dc/terms/",
    "examples": {"@id": "cr:examples", "@type": "@json"},
    "extract": "cr:extract",
    "field": "cr:field",
    "fileProperty": "cr:fileProperty",
    "fileObject": "cr:fileObject",
    "fileSet": "cr:fileSet",
    "format": "cr:format",
    "includes": "cr:includes",
    "isLiveDataset": "cr:isLiveDataset",
    "jsonPath": "cr:jsonPath",
    "key": "cr:key",
    "md5": "cr:md5",
    "parentField": "cr:parentField",
    "path": "cr:path",
    "recordSet": "cr:recordSet",
    "references": "cr:references",
    "regex": "cr:regex",
    "repeated": "cr:repeated",
    "replace": "cr:replace",
    "sc": "https://schema.org/",
    "separator": "cr:separator",
    "source": "cr:source",
    "subField": "cr:subField",
    "transform": "cr:transform",
    "wd": "https://www.wikidata.org/wiki/",
}


def _slug(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in value).strip("_")


def _safe_list(raw: Any) -> list[str]:
    if raw is None:
        return []
    # numpy / pyarrow / pandas array-like: convert to plain list first
    try:
        import numpy as _np

        if isinstance(raw, _np.ndarray):
            raw = raw.tolist()
    except ImportError:
        pass
    if isinstance(raw, (list, tuple)):
        return [str(v) for v in raw if v is not None and not _is_missing(v)]
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return []
        if text.startswith("["):
            try:
                parsed = json.loads(text)
                if isinstance(parsed, list):
                    return [str(v) for v in parsed if v is not None]
            except json.JSONDecodeError:
                pass
        return [text]
    return [str(raw)]


def _hash_file(path: Path) -> tuple[str, int] | None:
    if not path.is_file():
        return None
    digest = hashlib.md5()  # noqa: S324 - Croissant 1.0 expects MD5 in `md5`
    size = 0
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _empty_stub(reason: str) -> dict[str, Any]:
    return {
        "@context": CROISSANT_CONTEXT,
        "@type": "sc:Dataset",
        "conformsTo": CROISSANT_CONFORMS,
        "name": "hydromodpy-ml-empty",
        "description": "Croissant stub: no ML dataset row available.",
        "license": "https://creativecommons.org/licenses/by/4.0/",
        "url": "https://hydromodpy-docs.readthedocs.io/",
        "dateCreated": datetime.now(UTC).isoformat(timespec="seconds"),
        "version": "0.0.0",
        "hydromodpy:stub": True,
        "hydromodpy:stubReason": reason,
        "distribution": [],
        "recordSet": [],
    }


def _fetch_one(catalog: Any, sql: str, params: list[Any]) -> dict[str, Any] | None:
    backend = getattr(catalog, "backend", None)
    if backend is None:
        cur = catalog.connection.execute(sql, params)
        row = cur.fetchone()
        if row is None:
            return None
        names = [d[0] for d in cur.description]
        return dict(zip(names, row, strict=False))
    df = backend.query(sql, params)
    if df.empty:
        return None
    return {str(k): df.iloc[0][k] for k in df.columns}


def _fetch_all(catalog: Any, sql: str, params: list[Any]) -> list[dict[str, Any]]:
    backend = getattr(catalog, "backend", None)
    if backend is None:
        cur = catalog.connection.execute(sql, params)
        rows = cur.fetchall()
        names = [d[0] for d in cur.description]
        return [dict(zip(names, row, strict=False)) for row in rows]
    df = backend.query(sql, params)
    if df.empty:
        return []
    return df.to_dict("records")


def _table_exists(catalog: Any, name: str) -> bool:
    rows = _fetch_all(
        catalog,
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema='main' AND lower(table_name) = ?",
        [name.lower()],
    )
    return bool(rows)


def _build_field_node(record_set_id: str, name: str, dtype: str) -> dict[str, Any]:
    return {
        "@type": "cr:Field",
        "@id": f"{record_set_id}/{_slug(name)}",
        "name": name,
        "description": f"Column '{name}'",
        "dataType": dtype,
    }


def build_croissant_manifest(
    catalog: Any,
    dataset_id: str | None = None,
    *,
    parquet_root: Path | None = None,
) -> dict[str, Any]:
    """Build a Croissant 1.0 manifest for *dataset_id*.

    When *dataset_id* is ``None`` the function falls back to the most
    recently created ``ml_datasets`` row. When the table is empty (or
    missing), a labelled stub manifest is returned.
    """
    if not _table_exists(catalog, "ml_datasets"):
        return _empty_stub("ml_datasets table missing from catalog")

    if dataset_id is None:
        row = _fetch_one(
            catalog,
            "SELECT * FROM ml_datasets ORDER BY created_at DESC LIMIT 1",
            [],
        )
    else:
        row = _fetch_one(
            catalog,
            "SELECT * FROM ml_datasets WHERE CAST(dataset_id AS VARCHAR) = ?",
            [str(dataset_id)],
        )
    if row is None:
        return _empty_stub("no ml_datasets row")

    raw_name = row.get("name")
    name = (None if _is_missing(raw_name) else raw_name) or f"hydromodpy-ml-{row['dataset_id']}"
    features = _safe_list(row.get("features"))
    targets = _safe_list(row.get("targets"))
    split_id = row.get("split_id")
    scaler_id = row.get("scaler_id")
    if _is_missing(split_id):
        split_id = None
    if _is_missing(scaler_id):
        scaler_id = None

    distribution: list[dict[str, Any]] = []
    if parquet_root is None:
        parquet_root = (
            Path(getattr(catalog, "workspace_path", Path(".")))
            / "ml"
            / "datasets"
            / str(row["dataset_id"])
        )
    parquet_root = Path(parquet_root)
    file_objects: list[dict[str, Any]] = []
    for filename, role in (
        ("features.parquet", "features"),
        ("labels.parquet", "labels"),
        ("metadata.parquet", "metadata"),
    ):
        path = parquet_root / filename
        info = _hash_file(path)
        if info is None:
            continue
        md5, size = info
        file_objects.append(
            {
                "@type": "cr:FileObject",
                "@id": f"file/{role}",
                "name": filename,
                "description": f"Parquet file with {role}.",
                "encodingFormat": "application/vnd.apache.parquet",
                "contentSize": size,
                "md5": md5,
                "contentUrl": filename,
                "sha256": _sha256(path),
            }
        )
    distribution.extend(file_objects)

    record_sets: list[dict[str, Any]] = []
    if file_objects:
        for fobj in file_objects:
            base_id = fobj["@id"]
            rs_id = f"records/{base_id.split('/')[-1]}"
            columns = (
                features if "features" in base_id else (targets if "labels" in base_id else [])
            )
            fields = [_build_field_node(rs_id, col, "sc:Float") for col in columns if col]
            record_sets.append(
                {
                    "@type": "cr:RecordSet",
                    "@id": rs_id,
                    "name": base_id.split("/")[-1],
                    "description": f"Record set materialised from {fobj['name']}.",
                    "field": fields,
                    "source": {"@id": fobj["@id"]},
                }
            )

    payload: dict[str, Any] = {
        "@context": CROISSANT_CONTEXT,
        "@type": "sc:Dataset",
        "conformsTo": CROISSANT_CONFORMS,
        "name": str(name),
        "description": (
            f"HydroModPy ML dataset {row['dataset_id']} "
            f"with {len(features)} features and {len(targets)} targets."
        ),
        "license": "https://creativecommons.org/licenses/by/4.0/",
        "url": "https://hydromodpy-docs.readthedocs.io/",
        "version": "1.0.0",
        "dateCreated": str(row.get("created_at") or datetime.now(UTC).isoformat()),
        "hydromodpy:datasetId": str(row["dataset_id"]),
        "hydromodpy:catalogHash": row.get("catalog_hash"),
        "hydromodpy:features": features,
        "hydromodpy:targets": targets,
        "distribution": distribution,
        "recordSet": record_sets,
    }
    if split_id:
        payload["hydromodpy:splitId"] = str(split_id)
    if scaler_id:
        payload["hydromodpy:scalerId"] = str(scaler_id)

    if split_id and _table_exists(catalog, "ml_splits"):
        split_row = _fetch_one(
            catalog,
            "SELECT strategy, seed FROM ml_splits WHERE CAST(split_id AS VARCHAR) = ?",
            [str(split_id)],
        )
        if split_row is not None:
            payload["hydromodpy:splitStrategy"] = split_row.get("strategy")
            if split_row.get("seed") is not None:
                payload["hydromodpy:splitSeed"] = int(split_row["seed"])
    if scaler_id and _table_exists(catalog, "ml_scalers"):
        scaler_row = _fetch_one(
            catalog,
            "SELECT strategy, fingerprint FROM ml_scalers WHERE CAST(scaler_id AS VARCHAR) = ?",
            [str(scaler_id)],
        )
        if scaler_row is not None:
            payload["hydromodpy:scalerStrategy"] = scaler_row.get("strategy")
            payload["hydromodpy:scalerFingerprint"] = scaler_row.get("fingerprint")
    return payload


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_croissant(
    catalog: Any,
    dataset_id: str | None,
    output_path: Path | str,
    *,
    parquet_root: Path | None = None,
) -> Path:
    """Render a Croissant manifest and write it as JSON-LD."""
    payload = build_croissant_manifest(catalog, dataset_id, parquet_root=parquet_root)
    out = Path(output_path)
    if out.is_dir() or out.suffix == "":
        out = out / "croissant.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return out


def validate_manifest(payload: dict[str, Any]) -> tuple[bool, list[str]]:
    """Validate a manifest dict with mlcroissant when installed.

    Returns ``(True, [])`` when the payload parses correctly, otherwise a
    list of error strings. Never raises.
    """
    try:
        from mlcroissant import Dataset  # type: ignore[import-not-found]
    except ImportError:
        return False, ["mlcroissant not installed"]
    try:
        Dataset(jsonld=payload)
    except Exception as exc:  # noqa: BLE001 - mlcroissant raises broadly
        return False, [str(exc)]
    return True, []


__all__ = [
    "CROISSANT_CONFORMS",
    "CROISSANT_CONTEXT",
    "build_croissant_manifest",
    "validate_manifest",
    "write_croissant",
]
