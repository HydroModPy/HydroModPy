"""The facts a run accumulates about itself before its seal.

Why
---
A run writes its arrays and tables as it goes, but what the seal says about
the run (its parameters, its metrics, its environment, the inputs it read,
its grid) is known step by step. The seal is built from these facts at the
end, without an index. The facts live in one document under the attempt
state of the run, ``<run>/.hmp/checkpoints/facts.json``, rewritten each time
the store closes, so a second attempt resumes with what the first recorded
and nothing a run needs lives only in memory.

Format
------
:class:`RunFacts`, a Pydantic model dumped as JSON. Its blocks are the ones
of the seal (:mod:`hydromodpy.results.record.manifest`), typed by the same models.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Final

from pydantic import ConfigDict, Field

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.stored import dump_stored, read_stored
from hydromodpy.core.state.layout import INTERNAL_DIRNAME, RUN_INTERNAL_CHECKPOINTS_DIRNAME
from hydromodpy.core.version import __version__ as HMP_VERSION
from hydromodpy.results.identity import Identity
from hydromodpy.results.metric_rule import DateWindow, MetricScore
from hydromodpy.results.record.checks import CalibratedBy, Validity
from hydromodpy.results.record.manifest import (
    FlowRegime,
    InputEntry,
    ManifestSite,
    MeshTopology,
    MetricRow,
    ParameterRow,
    RunSeal,
    TrackedInput,
)
from hydromodpy.results.storage.json_io import read_transient_json, write_json_atomic
from hydromodpy.schema.lineage import Lineage

FACTS_FILENAME: Final[str] = "facts.json"
"""Name of the facts document under ``<run>/.hmp/checkpoints/``."""

FACTS_SCHEMA: Final[str] = "hydromodpy.run_facts.v1"
"""Schema id of the document."""


class CalibratedParameter(HydroModelBase):
    """One parameter a calibration set, as the rows of the run name it."""

    name: str = Field(description="Parameter name, as in the parameter rows of the run")
    zone: str | None = Field(default=None, description="Zone it set; None for every zone")

    def matches(self, row: ParameterRow) -> bool:
        """Whether *row* holds a value this calibration set."""
        return row.name == self.name and (self.zone is None or row.zone == self.zone)


class PromotionFacts(HydroModelBase):
    """What the session that promotes a run says about it.

    Built by the promotion from the session descriptor and the journal line
    of the trial, applied to the facts of the run by
    :meth:`RunFacts.apply_promotion` when the run opens.
    """

    converged: bool = Field(description="Whether the solve of the trial converged")
    bounds_hit: list[str] = Field(
        default_factory=list, description="Calibrated parameters that ended on a bound"
    )
    calibrated: list[CalibratedParameter] = Field(
        default_factory=list, description="Parameters the session set"
    )


class RunFacts(HydroModelBase):
    """What a run knows about itself before the seal."""

    schema_: str = Field(default=FACTS_SCHEMA, alias="schema", description="Schema id")
    sim_id: str = Field(description="Id of the run")
    name: str = Field(description="Run directory name, with its .vN")
    case_id: str = Field(description="The run name, or site-recipe under [sites]")
    recipe: str | None = Field(default=None, description="Recipe of a planned case")
    project: str = Field(description="Project the run belongs to")
    attempt: int = Field(ge=1, description="Attempt that writes these facts")
    attempt_id: str = Field(description="Id of that attempt")
    created_at: datetime = Field(description="Start of the first attempt, UTC")
    started_at: datetime = Field(description="Start of this attempt, UTC")
    solver: str | None = None
    solver_category: str | None = None
    flow_regime: FlowRegime | None = None
    solution_key: str | None = Field(
        default=None,
        description=(
            "Solution key of the run: its request id plus its code, solver binaries, key "
            "package versions and mesh engine"
        ),
    )
    request_id: str | None = Field(
        default=None, description="Request id of the run, the key a base regroups by"
    )
    field_digests: dict[str, dict[str, str]] = Field(
        default_factory=dict,
        description=(
            "Digest of each step of each array rounded at write time, by array path: the "
            "float64 values the writer received, before the rounding"
        ),
    )
    solver_output_dirs: dict[str, str] = Field(
        default_factory=dict,
        description="Folder each run of the plan solved in, by run id, for a resume to read",
    )
    config_source: str | None = Field(default=None, description="File the run was launched from")
    config_file: str | None = Field(default=None, description="config.toml once frozen")
    description: str | None = None
    scientific_objective: str | None = None
    contact_email: str | None = None
    doi: str | None = None
    n_cells: int | None = None
    n_layers: int | None = None
    n_timesteps: int | None = None
    mesh_hash: str | None = None
    mesh_topology: MeshTopology | None = None
    crs_wkt: str | None = None
    crs_epsg: int | None = None
    bbox: tuple[float, float, float, float] | None = None
    period_start: datetime | None = None
    period_end: datetime | None = None
    time_unit: str | None = None
    site: ManifestSite | None = None
    lineage: Lineage = Field(default_factory=Lineage)
    calibrated_by: CalibratedBy | None = None
    geographic_metadata: dict[str, Any] = Field(default_factory=dict)
    parameters: list[ParameterRow] = Field(default_factory=list)
    metrics: list[MetricRow] = Field(default_factory=list)
    tracked_inputs: list[TrackedInput] = Field(default_factory=list)
    inputs: list[InputEntry] = Field(default_factory=list)
    environment: dict[str, Any] = Field(
        default_factory=dict, description="Host snapshot, solver engine and dispatch, seed"
    )
    licence: str | None = Field(
        default=None, description="Licence the seal stated; None before the seal"
    )
    converged: bool | None = None
    budget_pct: float | None = None
    budget_threshold_pct: float | None = None
    validities: list[Validity] = Field(default_factory=list)
    bounds_hit: list[str] = Field(default_factory=list)
    score: MetricScore | None = None
    calibrated: list[CalibratedParameter] = Field(
        default_factory=list, description="Parameters a calibration set; their rows say so"
    )

    model_config = ConfigDict(populate_by_name=True)

    @classmethod
    def from_manifest(cls, seal: RunSeal) -> RunFacts:
        """Return the facts a sealed run states, read back from its seal.

        A sealed run keeps no attempt state: its facts are its seal. The
        host snapshot lives in ``provenance.json``, so it is not carried
        here; the licence is the one the seal stated.
        """
        run, geometry, period = seal.run, seal.geometry, seal.period
        checks = seal.checks
        return cls(
            sim_id=run.sim_id,
            name=run.name,
            case_id=run.case_id,
            recipe=run.recipe,
            project=run.project,
            attempt=run.attempt,
            attempt_id=run.attempt_id,
            created_at=run.created_at,
            started_at=run.started_at or run.created_at,
            solver=run.solver,
            solver_category=run.solver_category,
            flow_regime=run.flow_regime,
            solution_key=seal.identity.solution_key,
            request_id=seal.identity.request_id,
            config_source=seal.config.source,
            config_file=seal.config.file,
            description=run.description,
            scientific_objective=run.scientific_objective,
            contact_email=run.contact_email,
            doi=run.doi,
            licence=run.license,
            n_cells=geometry.n_cells,
            n_layers=geometry.n_layers,
            n_timesteps=period.n_timesteps,
            mesh_hash=geometry.mesh_hash,
            mesh_topology=geometry.mesh_topology,
            crs_wkt=geometry.crs_wkt,
            crs_epsg=geometry.crs_epsg,
            bbox=geometry.bbox,
            period_start=period.start,
            period_end=period.end,
            time_unit=period.time_unit,
            site=seal.site,
            lineage=seal.lineage,
            calibrated_by=checks.calibrated_by,
            geographic_metadata=dict(geometry.catchment),
            parameters=list(seal.parameters),
            metrics=list(seal.metrics),
            tracked_inputs=list(seal.inputs),
            converged=checks.converged,
            budget_pct=checks.budget_pct,
            budget_threshold_pct=checks.budget_threshold_pct,
            validities=list(checks.validities),
            bounds_hit=list(checks.bounds_hit),
            score=seal.score,
            calibrated=[
                CalibratedParameter(name=row.name, zone=row.zone)
                for row in seal.parameters
                if row.calibrated
            ],
        )

    def apply_promotion(self, promotion: PromotionFacts) -> None:
        """Write what the promoting session says about the run into its facts.

        The convergence of the trial solve, the parameters that ended on a
        bound, and the parameters the session set: their rows, written now or
        later, say ``origin = "calibrated"``.
        """
        self.converged = promotion.converged
        self.bounds_hit = list(promotion.bounds_hit)
        self.calibrated = list(promotion.calibrated)
        self.parameters = [self._marked(row) for row in self.parameters]

    def put_parameter(self, row: ParameterRow) -> None:
        """Keep one value per parameter and zone; the last write wins."""
        self.parameters = [
            p for p in self.parameters if (p.name, p.zone) != (row.name, row.zone)
        ] + [self._marked(row)]

    def _marked(self, row: ParameterRow) -> ParameterRow:
        """Return *row* marked calibrated when a calibration set its value."""
        if row.calibrated or not any(item.matches(row) for item in self.calibrated):
            return row
        return row.model_copy(update={"origin": "calibrated", "calibrated": True})

    def note_validity(
        self,
        name: str,
        passed: bool,
        value: float | None,
        message: str,
        *,
        fatal: bool = False,
    ) -> None:
        """Keep one verdict per check name, a non-fatal one by default; the last write wins."""
        self.validities = [v for v in self.validities if v.name != name] + [
            Validity(name, passed, value, message, fatal)
        ]

    def put_metric(self, row: MetricRow) -> None:
        """Keep one value per station, variable, metric and period; the last write wins."""
        key = (row.station, row.variable, row.metric, row.window_name)
        self.metrics = [
            m for m in self.metrics if (m.station, m.variable, m.metric, m.window_name) != key
        ] + [row]

    def put_tracked_input(self, row: TrackedInput) -> None:
        """Keep one entry per role and path; the last write wins."""
        key = (row.role, row.path)
        self.tracked_inputs = [t for t in self.tracked_inputs if (t.role, t.path) != key] + [row]

    def put_input(self, entry: InputEntry) -> None:
        """Keep one loaded input per variable, path and station; the last write wins."""
        key = _input_key(entry)
        self.inputs = [i for i in self.inputs if _input_key(i) != key] + [entry]


def _input_key(entry: InputEntry) -> tuple[str, str, str | None]:
    station = entry.request.get("station")
    return (entry.variable, entry.path, None if station is None else str(station))


def identity_of(facts: RunFacts) -> Identity:
    """Return the identity block the facts of a run state, label free.

    The block of a run before its seal: what a figure or an export written
    during the run carries. The seal writes the same block in its manifest.
    """
    score = facts.score
    score_window = (
        None
        if score is None or score.window_start is None or score.window_end is None
        else DateWindow(start=score.window_start, end=score.window_end)
    )
    period = (
        None
        if facts.period_start is None or facts.period_end is None
        else DateWindow(start=facts.period_start.date(), end=facts.period_end.date())
    )
    dirty = facts.environment.get("git_dirty")
    return Identity(
        site=None if facts.site is None else facts.site.name,
        site_fingerprint=None if facts.site is None else facts.site.fingerprint,
        case_id=facts.case_id,
        sim_id=facts.sim_id,
        attempt_id=facts.attempt_id,
        solution_key=facts.solution_key,
        request_id=facts.request_id,
        solver=facts.solver,
        mesh_hash=facts.mesh_hash,
        period=period,
        score_window=score_window,
        hydromodpy_version=HMP_VERSION,
        code_reproducible=None if dirty is None else not bool(dirty),
    )


def facts_path(run_dir: str | Path) -> Path:
    """Return ``<run>/.hmp/checkpoints/facts.json``."""
    return Path(run_dir) / INTERNAL_DIRNAME / RUN_INTERNAL_CHECKPOINTS_DIRNAME / FACTS_FILENAME


def write_facts(run_dir: str | Path, facts: RunFacts) -> Path:
    """Write the facts atomically and return their path."""
    return write_json_atomic(facts_path(run_dir), dump_stored(facts))


def read_facts(run_dir: str | Path) -> RunFacts | None:
    """Return the facts of an attempt, or ``None`` when none were written yet."""
    try:
        payload = read_transient_json(facts_path(run_dir), FACTS_SCHEMA)
    except FileNotFoundError:
        return None
    return read_stored(RunFacts, payload)


__all__ = [
    "FACTS_FILENAME",
    "FACTS_SCHEMA",
    "CalibratedParameter",
    "PromotionFacts",
    "RunFacts",
    "facts_path",
    "identity_of",
    "read_facts",
    "write_facts",
]
