"""The run record: the seal of a run, built in memory and written without the index.

Why
---
The seal used to be a projection of SQL: the run registered a row, the index
accumulated what the steps wrote, and ``finalize`` copied the row back to
disk. A hundred cases writing one index is a hundred writers on one file, and
a run that cannot open the index cannot seal. Here the run carries everything
the seal needs in one object, :class:`RunRecord`, and writes it itself. The
index is rebuilt from these files by the indexer, never the other way round.

Files written, in this order
----------------------------
1. ``tables.parquet/simulation.parquet``: the one-row index payload
   (:data:`~hydromodpy.results.storage.parquet_schemas.SIMULATION_SCHEMA`),
   with the footer every table of the run carries: identity, licence, extent.
2. ``tables.parquet/parameters.parquet``: the parameters, when the run has
   some, with their origin.
3. ``provenance.json``: tool, git, python, platform, packages, solver,
   timing, environment. ``host`` and ``user`` stay here, in the tree; a
   publication removes them.
4. ``inputs.json``: every loaded input with its provider, request and digest.
5. ``manifest.json``, last and durable: a directory without it never
   finished, whatever else it holds.

A crash before step 5 leaves the first files and no manifest; the next
attempt rewrites them all. The label is never part of the record:
:attr:`Identity.label` must be empty, a seal carries no label.

Only a completed run has a record
---------------------------------
A manifest exists only for a completed run, and its presence is what
``completed`` means: :class:`RunRecord` refuses any other status. To seal
even in failure is to write ``outcome.json``, ``README.md`` and the tables
present, never ``manifest.json``.

The calibration cost
--------------------
A run promoted by a session says what the session scored it on in
``checks.calibrated_by``: the name of the cost, its value for the case of this
run and the periods that case read.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pyarrow as pa
from pydantic import ConfigDict, Field, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.stored import read_stored
from hydromodpy.core.io.document_version import VersionWindow
from hydromodpy.core.io.file_digest import sha256_of
from hydromodpy.core.licensing import UNDETERMINED_LICENSE
from hydromodpy.results.checks import Checks
from hydromodpy.results.identity import Identity
from hydromodpy.results.lineage import Lineage
from hydromodpy.results.manifest import (
    DERIVE_RULE_VERSION,
    PARAMETERS_TABLE_NAME,
    InputEntry,
    Manifest,
    ManifestArtifact,
    ManifestBudget,
    ManifestConfig,
    ManifestGeometry,
    ManifestPeriod,
    ManifestRun,
    ManifestSite,
    MetricRow,
    ParameterRow,
    TrackedInput,
    list_artifacts,
    read_seal,
)
from hydromodpy.results.metric_rule import MetricScore
from hydromodpy.results.storage.contract import (
    PARQUET_FILE_SUFFIX,
    RUN_INPUTS_FILENAME,
    RUN_MANIFEST_FILENAME,
    RUN_PROVENANCE_FILENAME,
    SIMULATION_TABLE_NAME,
    TABLES_DIRNAME,
    UNSEALED_RUN_ENTRIES,
)
from hydromodpy.results.storage.geo_metadata import run_parquet_footer
from hydromodpy.results.storage.json_io import (
    read_sealed_json,
    write_json_atomic,
    write_json_durable,
)
from hydromodpy.results.storage.parquet_io import write_table_atomic
from hydromodpy.results.storage.parquet_schemas import PARAMETERS_SCHEMA, SIMULATION_SCHEMA

INPUTS_SCHEMA: Final[str] = "hydromodpy.inputs.v1"
"""Schema id of ``inputs.json``."""

INPUTS_VERSIONS: Final[VersionWindow] = VersionWindow(
    oldest="hydromodpy.inputs.v1", current=INPUTS_SCHEMA
)
"""Versions of ``inputs.json`` this code reads."""

PROVENANCE_VERSION: Final[int] = 2
"""Version of ``provenance.json``. Its own number: a change of the seal does not move it."""

PROVENANCE_DOCUMENT_SCHEMA: Final[str] = f"hydromodpy.provenance.v{PROVENANCE_VERSION}"
"""Id of the published JSON Schema of ``provenance.json`` (``schema/results/provenance.v2.json``)."""

PROVENANCE_VERSIONS: Final[VersionWindow] = VersionWindow(oldest=2, current=PROVENANCE_VERSION)
"""Versions of ``provenance.json`` this code reads."""


class RunProvenance(HydroModelBase):
    """``provenance.json``: what produced the numbers, environment included."""

    provenance_version: int = Field(default=PROVENANCE_VERSION)
    sim_id: str
    tool: dict[str, Any] = Field(
        default_factory=dict, description="name, version, code_fingerprint by layer"
    )
    git: dict[str, Any] = Field(default_factory=dict, description="commit, dirty, project_commit")
    python: dict[str, Any] = Field(default_factory=dict, description="version")
    platform: dict[str, Any] = Field(
        default_factory=dict, description="platform, hostname, user, cpu, memory_gb"
    )
    packages: dict[str, str] = Field(default_factory=dict, description="key package versions")
    solver: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "name, engine, version, binary_path, binary_sha256, and options: what the adapter "
            "decided once it built the model (IMS complexity, XT3D)"
        ),
    )
    timing: dict[str, Any] = Field(
        default_factory=dict, description="started_at, ended_at, duration_s"
    )
    environment: dict[str, Any] = Field(
        default_factory=dict, description="dependency lock, solver binaries with their digests"
    )


class InputsDocument(HydroModelBase):
    """``inputs.json``: every input the run loaded."""

    model_config = ConfigDict(populate_by_name=True)

    schema_: str = Field(default=INPUTS_SCHEMA, alias="schema")
    sim_id: str
    inputs: list[InputEntry] = Field(default_factory=list)

    @model_validator(mode="after")
    def _schema(self) -> InputsDocument:
        if not INPUTS_VERSIONS.holds(self.schema_):
            raise ValueError(f"schema is {self.schema_!r}, this module reads {INPUTS_SCHEMA!r}")
        return self


def read_provenance(run_dir: str | Path) -> RunProvenance:
    """Read ``provenance.json`` of a sealed run."""
    return read_stored(
        RunProvenance,
        read_sealed_json(
            Path(run_dir) / RUN_PROVENANCE_FILENAME, PROVENANCE_VERSIONS, key="provenance_version"
        ),
    )


def read_inputs(run_dir: str | Path) -> InputsDocument:
    """Read ``inputs.json`` of a sealed run or of a published copy."""
    return read_stored(
        InputsDocument, read_sealed_json(Path(run_dir) / RUN_INPUTS_FILENAME, INPUTS_VERSIONS)
    )


class RunRecord(HydroModelBase):
    """Everything the seal of a completed run says, in memory.

    The blocks are those of :class:`~hydromodpy.results.manifest.Manifest`,
    plus the provenance and the loaded inputs that go to their own files.
    ``run.status`` is always ``completed``: :class:`ManifestRun` refuses any
    other status with the sentence of the module docstring.
    """

    derive_rule_version: str = Field(
        default=DERIVE_RULE_VERSION,
        description="Version of the rules the derived fields of this run are rebuilt by",
    )
    run: ManifestRun
    site: ManifestSite | None = None
    geometry: ManifestGeometry = Field(default_factory=ManifestGeometry)
    period: ManifestPeriod = Field(default_factory=ManifestPeriod)
    config: ManifestConfig = Field(default_factory=ManifestConfig)
    lineage: Lineage = Field(default_factory=Lineage)
    identity: Identity
    checks: Checks = Field(default_factory=Checks)
    tracked_inputs: list[TrackedInput] = Field(
        default_factory=list, description="Files the configuration declared"
    )
    inputs: list[InputEntry] = Field(default_factory=list, description="Inputs the run loaded")
    parameters: list[ParameterRow] = Field(default_factory=list)
    metrics: list[MetricRow] = Field(default_factory=list)
    score: MetricScore | None = Field(default=None, description="The NSE under the metric rule")
    budget: ManifestBudget | None = None
    provenance: RunProvenance

    @model_validator(mode="after")
    def _coherent(self) -> RunRecord:
        run, identity = self.run, self.identity
        if identity.sim_id != run.sim_id:
            raise ValueError(f"identity names sim {identity.sim_id}, the run is {run.sim_id}")
        if identity.case_id != run.case_id:
            raise ValueError(f"identity names case {identity.case_id}, the run is {run.case_id}")
        if identity.attempt_id != run.attempt_id:
            raise ValueError("identity and run name different attempts")
        if identity.label is not None or identity.label_date is not None:
            raise ValueError("a seal carries no label: the label is a function of reading")
        if self.site is not None and identity.site != self.site.name:
            raise ValueError(f"identity names site {identity.site}, the run is on {self.site.name}")
        if self.site is not None and identity.site_fingerprint != self.site.fingerprint:
            raise ValueError("identity and site carry different fingerprints")
        if identity.config_hash != self.config.hash:
            raise ValueError("identity and config carry different hashes")
        if identity.mesh_hash != self.geometry.mesh_hash:
            raise ValueError("identity and geometry carry different mesh hashes")
        if self.provenance.sim_id != run.sim_id:
            raise ValueError("provenance names another run")
        if self.score is not None and self.score.metric != "nse":
            raise ValueError(f"the headline score is the NSE, not {self.score.metric}")
        for name, value in (
            ("created_at", run.created_at),
            ("started_at", run.started_at),
            ("ended_at", run.ended_at),
            ("period.start", self.period.start),
            ("period.end", self.period.end),
        ):
            if value is not None and value.tzinfo is None:
                raise ValueError(f"{name} is a naive instant; a seal states UTC")
        return self

    def simulation_row(self) -> dict[str, Any]:
        """Return the one row of ``simulation.parquet``, keyed by its columns."""
        run, geometry, period = self.run, self.geometry, self.period
        bbox = geometry.bbox or (None, None, None, None)
        score = self.score
        row: dict[str, Any] = {
            "sim_id": run.sim_id,
            "name": run.name,
            "name_stem": run.name_stem,
            "version_int": run.version,
            "project": run.project,
            "site": None if self.site is None else self.site.name,
            "site_fingerprint": None if self.site is None else self.site.fingerprint,
            "recipe": run.recipe,
            "case_id": run.case_id,
            "rel_dir": run.rel_dir,
            "attempt": run.attempt,
            "attempt_id": run.attempt_id,
            "solver": run.solver,
            "solver_category": run.solver_category,
            "status": run.status,
            "flow_regime": run.flow_regime,
            "mesh_topology": geometry.mesh_topology,
            "mesh_hash": geometry.mesh_hash,
            "n_cells": geometry.n_cells,
            "n_layers": geometry.n_layers,
            "n_timesteps": period.n_timesteps,
            "crs_wkt": geometry.crs_wkt,
            "crs_epsg": geometry.crs_epsg,
            "bbox_xmin": bbox[0],
            "bbox_ymin": bbox[1],
            "bbox_xmax": bbox[2],
            "bbox_ymax": bbox[3],
            "period_start": period.start,
            "period_end": period.end,
            "time_unit": period.time_unit,
            "config_hash": self.config.hash,
            "config_source": self.config.source,
            "parent_sim_id": self.lineage.parent_sim_id,
            "lineage_kind": self.lineage.kind,
            "session_id": self.lineage.session_id,
            "hydromodpy_version": self.identity.hydromodpy_version,
            "created_at": run.created_at,
            "started_at": run.started_at,
            "ended_at": run.ended_at,
            "duration_s": run.duration_s,
            "description": run.description,
            "scientific_objective": run.scientific_objective,
            "contact_email": run.contact_email,
            "doi": run.doi,
            **self.checks.flatten(),
            "nse": None if score is None else score.value,
            "score_station": None if score is None else score.station,
            "score_variable": None if score is None else score.variable,
            "metric_rule_version": None if score is None else score.metric_rule_version,
        }
        return row

    def simulation_table(self) -> pa.Table:
        """Return ``simulation.parquet`` as a table, identity in its metadata."""
        table = pa.Table.from_pylist([self.simulation_row()], schema=SIMULATION_SCHEMA)
        return table.replace_schema_metadata(self._footed(SIMULATION_SCHEMA))

    def parameters_table(self) -> pa.Table | None:
        """Return ``parameters.parquet`` as a table, or ``None`` without parameters."""
        if not self.parameters:
            return None
        rows = [
            {
                "sim_id": self.run.sim_id,
                "param_name": row.name,
                "zone_id": row.zone,
                "value": row.value,
                "unit": row.unit,
                "parameterization": row.parameterization,
                "valid_from": self.run.created_at,
                "origin": row.origin,
                "calibrated": row.calibrated,
            }
            for row in self.parameters
        ]
        table = pa.Table.from_pylist(rows, schema=PARAMETERS_SCHEMA)
        return table.replace_schema_metadata(self._footed(PARAMETERS_SCHEMA))

    def parquet_footer(self) -> dict[str, str]:
        """Return the footer of the tables of the record, the one every run table carries."""
        run, geometry, period = self.run, self.geometry, self.period
        return run_parquet_footer(
            sim_id=run.sim_id,
            project=run.project,
            name=run.name,
            solver=run.solver,
            config_hash=self.config.hash,
            licence=run.license or UNDETERMINED_LICENSE,
            scientific_objective=run.scientific_objective,
            doi=run.doi,
            identity=self.identity,
            created_at=run.created_at,
            crs_epsg=geometry.crs_epsg,
            crs_wkt=geometry.crs_wkt,
            bbox=geometry.bbox,
            period_start=period.start,
            period_end=period.end,
        )

    def _footed(self, schema: pa.Schema) -> dict[bytes, bytes]:
        """Return the metadata of *schema* with the footer of the run on top."""
        metadata = dict(schema.metadata or {})
        for key, value in self.parquet_footer().items():
            metadata[key.encode("utf-8")] = value.encode("utf-8")
        return metadata

    def inputs_document(self) -> InputsDocument:
        """Return ``inputs.json`` as a document."""
        return InputsDocument(sim_id=self.run.sim_id, inputs=list(self.inputs))

    def to_manifest(self, *, sealed_at: datetime, artifacts: list[ManifestArtifact]) -> Manifest:
        """Return the seal, given the inventory of the directory."""
        return Manifest(
            derive_rule_version=self.derive_rule_version,
            sealed_at=sealed_at,
            run=self.run,
            site=self.site,
            geometry=self.geometry,
            period=self.period,
            config=self.config,
            lineage=self.lineage,
            identity=self.identity,
            checks=self.checks,
            inputs=list(self.tracked_inputs),
            artifacts=artifacts,
            parameters=list(self.parameters),
            metrics=list(self.metrics),
            score=self.score,
            budget=self.budget,
        )

    def write(self, run_dir: str | Path) -> Path:
        """Write the seal files in order and return the path of the manifest."""
        directory = Path(run_dir)
        tables = directory / TABLES_DIRNAME
        write_table_atomic(
            self.simulation_table(), tables / f"{SIMULATION_TABLE_NAME}{PARQUET_FILE_SUFFIX}"
        )
        parameters = self.parameters_table()
        if parameters is not None:
            write_table_atomic(parameters, tables / f"{PARAMETERS_TABLE_NAME}{PARQUET_FILE_SUFFIX}")
        write_json_atomic(
            directory / RUN_PROVENANCE_FILENAME, self.provenance.model_dump(mode="json")
        )
        write_json_atomic(
            directory / RUN_INPUTS_FILENAME,
            self.inputs_document().model_dump(mode="json", by_alias=True),
        )
        manifest = self.to_manifest(
            sealed_at=datetime.now(UTC), artifacts=sealed_artifacts(directory)
        )
        return write_json_durable(
            directory / RUN_MANIFEST_FILENAME, manifest.model_dump(mode="json", by_alias=True)
        )

    @classmethod
    def read(cls, run_dir: str | Path) -> RunRecord:
        """Read a record back from a sealed directory."""
        directory = Path(run_dir)
        manifest = read_seal(directory)
        provenance = read_provenance(directory)
        inputs = read_inputs(directory)
        return cls(
            run=manifest.run,
            site=manifest.site,
            geometry=manifest.geometry,
            period=manifest.period,
            config=manifest.config,
            lineage=manifest.lineage,
            identity=manifest.identity,
            checks=manifest.checks,
            tracked_inputs=manifest.inputs,
            inputs=inputs.inputs,
            parameters=manifest.parameters,
            metrics=manifest.metrics,
            score=manifest.score,
            budget=manifest.budget,
            provenance=provenance,
        )


def sealed_artifacts(run_dir: str | Path) -> list[ManifestArtifact]:
    """Inventory the sealed entries of a run directory.

    What :data:`~hydromodpy.results.storage.contract.UNSEALED_RUN_ENTRIES`
    names is left out: derived, mutable, diagnostic or history. A file carries
    its ``sha256``. A directory store and the manifest itself do not: the first
    is too large to hash at every seal, the second is not written yet.
    """
    root = Path(run_dir)
    artifacts = []
    for entry in list_artifacts(root):
        if Path(entry["path"]).parts[0] in UNSEALED_RUN_ENTRIES:
            continue
        path = root / entry["path"]
        if entry["role"] != "manifest" and path.is_file():
            entry = {**entry, "sha256": sha256_of(path)}
        artifacts.append(ManifestArtifact(**entry))
    return artifacts


__all__ = [
    "INPUTS_SCHEMA",
    "INPUTS_VERSIONS",
    "PROVENANCE_VERSIONS",
    "InputsDocument",
    "RunProvenance",
    "RunRecord",
    "read_inputs",
    "read_provenance",
    "sealed_artifacts",
]
