"""The ``identity`` block: what every file that leaves a run says about itself.

Why
---
A CSV of discharge, a GeoPackage of the catchment, a PNG of the heads, a
Parquet table or the Zarr store travel alone. Each one has to say which site
it is, which case and which run produced it, over what period, under which
version, and what the run may be called today. The block is computed once
and posed into every format by the applicators of this module; the same
module reads it back, so a guard can open each format and find it.

Format
------
:class:`Identity` is the block. In the seal (``manifest.json``) it carries no
label: the label is a function of reading. A derived file (figure, export,
published copy) receives a copy with the label and its date posed by
:meth:`Identity.labelled`.

Where it lives, per format:

- Zarr: root attributes ``hydromodpy_identity`` (the block), ``hydromodpy_site``,
  ``hydromodpy_label``, ``project`` (the site) and ``processing_level``;
- Parquet: the schema metadata key ``hmp.identity`` (the block as JSON);
- GeoPackage: one row of the standard ``gpkg_metadata`` table, referenced by
  ``gpkg_metadata_reference`` at the ``geopackage`` scope;
- PNG: the text chunk ``hydromodpy.identity`` (the block as JSON), and a
  visible footer rendered from :meth:`Identity.footer_text`;
- CSV and any other text file: a ``<file>.meta.json`` sidecar next to it
  (``discharge.csv`` gives ``discharge.csv.meta.json``).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Final

import zarr
from PIL import Image
from pydantic import Field

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.stored import read_stored
from hydromodpy.core.io.document_version import VersionWindow
from hydromodpy.results.metric_rule import DateWindow
from hydromodpy.results.storage.json_io import read_sealed_json, write_json_atomic
from hydromodpy.results.validity_rules import Label
from hydromodpy.schema.media_types import JSON_MEDIA_TYPE

IDENTITY_SCHEMA: Final[str] = "hydromodpy.identity.v1"
"""Schema id of the block and of its ``.meta.json`` sidecar."""

IDENTITY_VERSIONS: Final[VersionWindow] = VersionWindow(
    oldest="hydromodpy.identity.v1", current=IDENTITY_SCHEMA
)
"""Versions of the ``.meta.json`` sidecar this code reads."""

ZARR_IDENTITY_ATTR: Final[str] = "hydromodpy_identity"
"""Root attribute of a Zarr store holding the block."""

PARQUET_IDENTITY_KEY: Final[str] = "hmp.identity"
"""Schema metadata key of a Parquet file holding the block."""

PNG_IDENTITY_KEY: Final[str] = "hydromodpy.identity"
"""Text chunk of a PNG holding the block."""

GPKG_METADATA_URI: Final[str] = "https://hydromodpy.readthedocs.io/identity/v1"
"""``md_standard_uri`` of the GeoPackage metadata row holding the block."""

META_SIDECAR_SUFFIX: Final[str] = ".meta.json"
"""Suffix of the sidecar written next to a CSV."""

PROCESSING_LEVELS: Final[dict[str | None, str]] = {
    None: "Modeled L2",
    "exploratory": "Modeled L2 (exploratory)",
    "evaluated": "Modeled L2 (evaluated)",
    "calibrated": "Modeled L3 (calibrated)",
    "failed": "Modeled L1 (failed)",
}
"""ACDD ``processing_level`` derived from the label."""


class Identity(HydroModelBase):
    """Who a run is, posed into every file that leaves it."""

    site: str | None = Field(default=None, description="Site name")
    site_fingerprint: str | None = Field(default=None, description="Fingerprint of the site")
    case_id: str = Field(description="Case the run is: the run name, or site-recipe")
    sim_id: str = Field(description="Id of the run")
    attempt_id: str = Field(description="Id of the attempt that sealed the run")
    config_hash: str | None = Field(default=None, description="Identity hash of the configuration")
    mesh_hash: str | None = Field(default=None, description="Hash of the mesh")
    period: DateWindow | None = Field(
        default=None, description="Simulated period; none when steady"
    )
    score_window: DateWindow | None = Field(
        default=None, description="Window the run was scored on"
    )
    label: Label | None = Field(default=None, description="Label at the date below; never sealed")
    label_date: date | None = Field(default=None, description="Day the label was computed")
    rule_version: str | None = Field(default=None, description="Rules the label follows")
    hydromodpy_version: str = Field(description="Version that produced the run")
    code_reproducible: bool | None = Field(
        default=None, description="False for a dirty checkout or an editable install"
    )

    def labelled(self, label: Label, *, label_date: date, rule_version: str) -> Identity:
        """Return a copy carrying the label of the day, for a derived file."""
        return self.model_copy(
            update={"label": label, "label_date": label_date, "rule_version": rule_version}
        )

    def as_json(self) -> str:
        """Return the block as one JSON line."""
        return json.dumps(self.model_dump(mode="json"), sort_keys=True)

    @classmethod
    def from_json(cls, text: str) -> Identity:
        """Read a block :meth:`as_json` wrote."""
        return read_stored(cls, json.loads(text))

    def as_zarr_attrs(self) -> dict[str, Any]:
        """Return the root attributes of a Zarr store."""
        return {
            ZARR_IDENTITY_ATTR: self.model_dump(mode="json"),
            "hydromodpy_site": self.site or "",
            "hydromodpy_label": self.label or "",
            "project": self.site or "",
            "processing_level": PROCESSING_LEVELS[self.label],
        }

    def apply_to_zarr(self, group: zarr.Group) -> None:
        """Pose the block on the root of an open Zarr group."""
        group.attrs.update(self.as_zarr_attrs())

    def as_parquet_metadata(self) -> dict[bytes, bytes]:
        """Return the schema metadata of a Parquet file."""
        return {PARQUET_IDENTITY_KEY.encode("utf-8"): self.as_json().encode("utf-8")}

    def as_png_metadata(self) -> dict[str, str]:
        """Return the text chunks of a PNG, for ``savefig(metadata=...)``."""
        return {
            PNG_IDENTITY_KEY: self.as_json(),
            "Software": f"HydroModPy {self.hydromodpy_version}",
        }

    def footer_text(self) -> str:
        """Return the visible footer of a figure: site, period, version, label."""
        site = self.site or self.case_id
        if self.period is None:
            period = "steady state, no period"
        else:
            period = f"{self.period.start} to {self.period.end}"
        version = f"HydroModPy {self.hydromodpy_version}"
        if self.label is None:
            label = "unlabelled"
        else:
            label = f"{self.label} ({self.label_date})"
        return " · ".join((site, period, version, label))

    def write_gpkg_metadata(self, path: str | Path) -> None:
        """Pose the block in the ``gpkg_metadata`` table of an existing GeoPackage."""
        payload = self.as_json()
        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        with sqlite3.connect(path) as connection:
            connection.executescript(_GPKG_METADATA_DDL)
            connection.execute(
                "DELETE FROM gpkg_metadata_reference WHERE md_file_id IN "
                "(SELECT id FROM gpkg_metadata WHERE md_standard_uri = ?)",
                (GPKG_METADATA_URI,),
            )
            connection.execute(
                "DELETE FROM gpkg_metadata WHERE md_standard_uri = ?", (GPKG_METADATA_URI,)
            )
            cursor = connection.execute(
                "INSERT INTO gpkg_metadata (md_scope, md_standard_uri, mime_type, metadata) "
                "VALUES ('dataset', ?, ?, ?)",
                (GPKG_METADATA_URI, JSON_MEDIA_TYPE, payload),
            )
            connection.execute(
                "INSERT INTO gpkg_metadata_reference "
                "(reference_scope, table_name, column_name, row_id_value, timestamp, "
                "md_file_id, md_parent_id) VALUES ('geopackage', NULL, NULL, NULL, ?, ?, NULL)",
                (now, cursor.lastrowid),
            )
            for table in ("gpkg_metadata", "gpkg_metadata_reference"):
                _declare_metadata_extension(connection, table)

    def write_meta_json(self, data_path: str | Path) -> Path:
        """Write the ``.meta.json`` sidecar of a data file and return its path."""
        target = meta_sidecar_path(data_path)
        sidecar = MetaSidecar(file=Path(data_path).name, identity=self)
        return write_json_atomic(target, sidecar.model_dump(mode="json", by_alias=True))


class MetaSidecar(HydroModelBase):
    """The ``<file>.meta.json`` next to a CSV: the block and the file it describes."""

    schema_: str = Field(default=IDENTITY_SCHEMA, alias="schema")
    file: str = Field(description="Name of the file the sidecar describes")
    identity: Identity


_GPKG_METADATA_DDL = """
CREATE TABLE IF NOT EXISTS gpkg_metadata (
  id INTEGER CONSTRAINT m_pk PRIMARY KEY ASC NOT NULL,
  md_scope TEXT NOT NULL DEFAULT 'dataset',
  md_standard_uri TEXT NOT NULL,
  mime_type TEXT NOT NULL DEFAULT 'text/xml',
  metadata TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS gpkg_metadata_reference (
  reference_scope TEXT NOT NULL,
  table_name TEXT,
  column_name TEXT,
  row_id_value INTEGER,
  timestamp DATETIME NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  md_file_id INTEGER NOT NULL,
  md_parent_id INTEGER,
  CONSTRAINT crmr_mfi_fk FOREIGN KEY (md_file_id) REFERENCES gpkg_metadata(id),
  CONSTRAINT crmr_mpi_fk FOREIGN KEY (md_parent_id) REFERENCES gpkg_metadata(id)
);
CREATE TABLE IF NOT EXISTS gpkg_extensions (
  table_name TEXT,
  column_name TEXT,
  extension_name TEXT NOT NULL,
  definition TEXT NOT NULL,
  scope TEXT NOT NULL,
  CONSTRAINT ge_tce UNIQUE (table_name, column_name, extension_name)
);
"""


def _declare_metadata_extension(connection: sqlite3.Connection, table: str) -> None:
    """Register the metadata extension for *table* once; GDAL may have done it already."""
    present = connection.execute(
        "SELECT 1 FROM gpkg_extensions WHERE table_name = ? AND column_name IS NULL "
        "AND extension_name = 'gpkg_metadata'",
        (table,),
    ).fetchone()
    if present is None:
        connection.execute(
            "INSERT INTO gpkg_extensions (table_name, column_name, extension_name, definition, scope) "
            "VALUES (?, NULL, 'gpkg_metadata', "
            "'http://www.geopackage.org/spec120/#extension_metadata', 'read-write')",
            (table,),
        )


def meta_sidecar_path(data_path: str | Path) -> Path:
    """Return the sidecar path of a data file: ``discharge.csv`` gives ``discharge.csv.meta.json``.

    The whole file name is kept, so ``discharge.csv`` and ``discharge.parquet``
    never share a sidecar.
    """
    path = Path(data_path)
    return path.with_name(path.name + META_SIDECAR_SUFFIX)


def read_identity_from(path: str | Path) -> Identity | None:
    """Read the block back from any file an applicator wrote it into.

    ``None`` when the file carries no block. The format is told by the path:
    a ``.zarr`` directory, a ``.parquet``, a ``.gpkg``, a ``.png``, a
    ``.meta.json`` sidecar, or a data file whose sidecar is looked for.
    """
    target = Path(path)
    if target.name.endswith(META_SIDECAR_SUFFIX):
        return _read_sidecar(target)
    suffix = target.suffix.lower()
    if suffix == ".zarr":
        return _read_zarr(target)
    if suffix == ".parquet":
        return _read_parquet(target)
    if suffix == ".gpkg":
        return _read_gpkg(target)
    if suffix == ".png":
        return _read_png(target)
    sidecar = meta_sidecar_path(target)
    return _read_sidecar(sidecar) if sidecar.is_file() else None


def _read_sidecar(path: Path) -> Identity | None:
    if not path.is_file():
        return None
    return read_stored(MetaSidecar, read_sealed_json(path, IDENTITY_VERSIONS)).identity


def _read_zarr(path: Path) -> Identity | None:
    if not path.is_dir():
        return None
    root = zarr.open_group(str(path), mode="r", use_consolidated=False)
    block = root.attrs.get(ZARR_IDENTITY_ATTR)
    return None if block is None else read_stored(Identity, block)


def _read_parquet(path: Path) -> Identity | None:
    import pyarrow.parquet as pq

    metadata = pq.read_schema(path).metadata or {}
    raw = metadata.get(PARQUET_IDENTITY_KEY.encode("utf-8"))
    return None if raw is None else Identity.from_json(raw.decode("utf-8"))


def _read_gpkg(path: Path) -> Identity | None:
    with sqlite3.connect(path) as connection:
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'gpkg_metadata'"
        ).fetchone()
        if exists is None:
            return None
        row = connection.execute(
            "SELECT metadata FROM gpkg_metadata WHERE md_standard_uri = ?", (GPKG_METADATA_URI,)
        ).fetchone()
    return None if row is None else Identity.from_json(row[0])


def _read_png(path: Path) -> Identity | None:
    with Image.open(path) as image:
        text = dict(getattr(image, "text", {}))
    raw = text.get(PNG_IDENTITY_KEY)
    return None if raw is None else Identity.from_json(raw)


__all__ = [
    "GPKG_METADATA_URI",
    "IDENTITY_SCHEMA",
    "IDENTITY_VERSIONS",
    "META_SIDECAR_SUFFIX",
    "PARQUET_IDENTITY_KEY",
    "PNG_IDENTITY_KEY",
    "PROCESSING_LEVELS",
    "ZARR_IDENTITY_ATTR",
    "Identity",
    "MetaSidecar",
    "meta_sidecar_path",
    "read_identity_from",
]
