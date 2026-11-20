"""What a calibration returns, and the words about it.

:class:`CalibrationReport` is what ``hmp.calibrate`` and ``Project.calibrate``
always return, with or without phases. Its names read the stored documents, and
its ``best`` and ``trials`` read the session on disk. The session page is written
by :mod:`hydromodpy.project.report`, from the rows of
:mod:`hydromodpy.results.session.summary`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

from hydromodpy.core.logging import get_logger
from hydromodpy.results.errors import SeveralCasesError
from hydromodpy.results.metric_rule import CALIBRATION_ROLE, PeriodWindow
from hydromodpy.results.session.descriptor import (
    BestCase,
    ScoredSamples,
    read_session,
    scored_samples_text,
    session_descriptor_path,
)
from hydromodpy.results.session.view import TRIAL_COLUMNS, Session

if TYPE_CHECKING:
    import pandas as pd

    from hydromodpy.calibration.optim.parameters import CalibParameter
    from hydromodpy.results.run.view import Run

logger = get_logger(__name__)


NO_OTHER_TRIAL = "no other trial within the cost margin"
"""What a recap says in place of an interval that only holds the best trial."""


# ---------------------------------------------------------------------------
# CalibrationReport dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FrozenParameter:
    """One parameter a phase calibrated and held fixed for the phases after it.

    The declaration is the one the parent configuration carries, so the dotted
    path and the mode (``replace`` / ``scale``) are honored exactly as during
    the phase that calibrated the value.
    """

    parameter: CalibParameter
    value: float
    phase: str

    @property
    def name(self) -> str:
        """Calibration name of the frozen parameter."""
        return self.parameter.name

    @property
    def path(self) -> str | None:
        """Dotted path in the configuration the value is written to."""
        return self.parameter.effective_path

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly view of the frozen value."""
        return {
            "name": self.name,
            "path": self.path,
            "value": float(self.value),
            "mode": self.parameter.mode,
            "phase": self.phase,
        }


@dataclass(frozen=True, slots=True)
class PhaseRun:
    """One phase of a staged calibration: its report, its freeze, its status."""

    name: str
    index: int
    session_id: str
    report: CalibrationReport
    frozen: tuple[FrozenParameter, ...]
    reopened: tuple[FrozenParameter, ...] = ()
    """The passed values this phase moved again, each with the phase that found it."""
    status: str = "completed"
    """What the phase descriptor says of the search: completed, partial or failed."""
    stop_note: str | None = None
    """``FROZE_BUDGET_ONLY`` for the best of a budget-only search, or a root out of bounds."""

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly view of the phase, report included."""
        summary: dict[str, Any] = {
            "phase": self.name,
            "index": self.index,
            "session_id": self.session_id,
            "status": self.status,
            "frozen": [item.to_dict() for item in self.frozen],
        }
        if self.stop_note:
            summary["stop_note"] = self.stop_note
        if self.reopened:
            summary["reopened"] = [item.to_dict() for item in self.reopened]
        summary["report"] = self.report.to_dict()
        return summary


@dataclass(frozen=True)
class CalibrationReport:
    """What one calibration found, with or without phases.

    ``hmp.calibrate`` and ``Project.calibrate`` return this class, and with
    ``dry_run`` a plan that runs nothing. A calibration in phases fills
    ``phases``, each with its own report, and
    ``frozen``, and its best values are those of the calibrated run. ``to_dict``
    gives the same summary as a JSON-friendly mapping.

    The shape of this report and the ``[calibration]`` section are experimental
    until the rework of the calibration is published.
    """

    session_id: str
    """Id of the session the search belongs to."""

    method: str
    """Optimizer method name (e.g. ``"optuna"``)."""

    n_trials: int
    """Number of trials actually run (could be < ``max_trials`` if the optimizer converged)."""

    best_cost: float | None
    """Lowest cost reached, ``None`` when no trial completed."""

    duration_s: float
    """Wall-clock duration of the search in seconds."""

    save_runs: str
    """The ``save_runs`` mode used (``"none"``, ``"best_n"`` or ``"all"``)."""

    promoted: int
    """Count of trials promoted to runs after the search."""

    status: str = "completed"
    """How the session closed: completed, partial, aborted or failed."""

    cost_name: str | None = None
    """Name of the cost the search minimized."""

    cost_label: str | None = None
    """What the cost reads as, such as ``1 - nse_log``."""

    best_trial: int | None = None
    """Number of the best trial in ``trials.jsonl``, unique in the session."""

    best_parameters: dict[str, float] | None = None
    """Physical values of the best candidate, keyed by calibrated parameter name.

    The whole set of the calibrated run: in a calibration in phases, the values
    an earlier phase froze come with those of the last phase. ``None`` when no
    candidate was evaluated."""

    best_cases: dict[str, BestCase] = field(default_factory=dict)
    """What the best trial gave in each case: its run and its cost, by case id."""

    windows: dict[str, PeriodWindow] = field(default_factory=dict)
    """The periods the best trial was scored on, by name."""

    parameter_uncertainty: tuple[Any, ...] = ()
    """Width beside each calibrated value, when the file asked for one.

    Empty unless ``[calibration.uncertainty]`` declared a method that produces it.
    The values themselves are in ``best_parameters`` and are never touched by it."""

    cost_block_fractions: dict[str, Any] | None = None
    """Fraction of the cost each block actually took.

    ``"mean"`` averages the fraction over the finished trials (each a mapping of
    block name to its fraction, 0 to 1, of the cost), ``"mean_n_trials"`` is how
    many of them entered that average, and ``"best"`` reads the fraction at the
    reported candidate. ``None`` when the phase scores through a single
    metric with no declared ``[[calibration.objective_blocks]]``, or, for a
    phase reused from a previous run (see ``extra["cost_block_fractions_absent_note"]``
    when that is why), when its journaled trials carry nothing to recompute it
    from. See :func:`hydromodpy.calibration.optim.objective.cost_block_fractions`
    for how a fraction is defined."""

    workspace: Path | None = None
    """Project root the session was written to."""

    session_dir: Path | None = None
    """Folder the session journalled its trials in, ``sessions/<case>``."""

    phases: tuple[PhaseRun, ...] = ()
    """The phases of a staged calibration in the order they ran; empty without phases.

    The report of a phase has no phases of its own."""

    frozen: tuple[FrozenParameter, ...] = ()
    """Every value a settled phase declared frozen, in order, with the path it is written to.

    A parameter two phases froze appears twice; the later value is the one the
    phases after both of them hold."""

    reused_from_disk: tuple[str, ...] = ()
    """Names of the phases read back from the reopened session instead of solved.

    Only non-empty under ``hmp calibrate --resume``: a phase is reused when it
    completed in the session and its recorded fingerprint matches this run's
    own model, mesh and input files."""

    restart_spreads: tuple[Any, ...] = ()
    """Where the restarts of each phase landed, when the file asked for restarts.

    The calibrated value is untouched: it is the best of them. This says how far
    apart the others finished, which is the one thing a single search cannot
    report about itself."""

    steady_window: dict[str, Any] | None = None
    """The span a ``regime = "steady"`` phase actually averaged its recharge
    over: ``start``, ``end``, ``days``, and ``mean_recharge_m_s`` when the
    steady phase's calibrated conductivity is known. ``None`` when no phase
    declares a steady regime. Read back from the same translation the run
    itself used (:func:`hydromodpy.calibration.runners.phase_regime.regime_overrides`),
    never recomputed by a second reading of the file that could drift from it."""

    protocol: dict[str, Any] | None = None
    """The published method that wrote these stages, when one did."""

    methods_paragraph: str | None = None
    """The prose this run writes about itself, conditioned on the stages that
    completed. It is the only object by which someone who did not produce the
    number can know what it rests on without reading Python."""

    methods_path: Path | None = None
    """The ``methods.md`` file the paragraph was written to, in the session folder.
    ``None`` when there is no paragraph or no session folder."""

    extra: dict[str, Any] = field(default_factory=dict)
    """Free-form metadata (callers may attach anything extra here)."""

    @property
    def session(self) -> Session | None:
        """The session on disk, ``None`` when the report names no session folder."""
        return None if self.session_dir is None else Session(self.session_dir)

    @property
    def best_by_case(self) -> dict[str, Run | None]:
        """The run of the best trial in each case (:attr:`Session.best_by_case`)."""
        session = self.session
        return {} if session is None else session.best_by_case

    @property
    def best(self) -> Run | None:
        """The run of the one case (:attr:`Session.best`), ``None`` without a run."""
        session = self.session
        return None if session is None else session.best

    @property
    def trials(self) -> pd.DataFrame:
        """Every trial of the session, one row per trial and case (:attr:`Session.trials`)."""
        import pandas as pd

        session = self.session
        return pd.DataFrame(columns=list(TRIAL_COLUMNS)) if session is None else session.trials

    def _only_case(self) -> BestCase | None:
        """Return the one case the best trial names; refuse a report of several cases."""
        if len(self.best_cases) > 1:
            raise SeveralCasesError(
                f"session {self.session_id} holds one run per case "
                f"({', '.join(self.best_cases)}): read best_cases."
            )
        return next(iter(self.best_cases.values()), None)

    @property
    def best_sim_id(self) -> str | None:
        """Id of the run of the one case, ``None`` when none was written."""
        case = self._only_case()
        return None if case is None else case.sim_id

    @property
    def best_rel_dir(self) -> str | None:
        """Directory of the run of the one case, relative to the project root."""
        case = self._only_case()
        return None if case is None else case.rel_dir

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly summary."""
        payload: dict[str, Any] = {
            "session_id": self.session_id,
            "method": self.method,
            "status": self.status,
            "n_trials": int(self.n_trials),
            "best_cost": self.best_cost,
            "duration_s": round(float(self.duration_s), 3),
            "save_runs": self.save_runs,
            "promoted": int(self.promoted),
            "best_cases": {
                case_id: case.model_dump(mode="json") for case_id, case in self.best_cases.items()
            },
        }
        if len(self.best_cases) <= 1:
            payload["best_sim_id"] = self.best_sim_id
            payload["best_rel_dir"] = self.best_rel_dir
        if self.cost_name is not None:
            payload["cost_name"] = self.cost_name
        if self.cost_label is not None:
            payload["cost_label"] = self.cost_label
        if self.best_trial is not None:
            payload["best_trial"] = int(self.best_trial)
        if self.best_parameters is not None:
            payload["best_parameters"] = dict(self.best_parameters)
        if self.windows:
            payload["windows"] = {
                name: window.model_dump(mode="json") for name, window in self.windows.items()
            }
        if self.parameter_uncertainty:
            payload["parameter_uncertainty"] = [
                item.to_dict() for item in self.parameter_uncertainty
            ]
        if self.cost_block_fractions:
            payload["cost_block_fractions"] = {
                key: (dict(value) if isinstance(value, Mapping) else value)
                for key, value in self.cost_block_fractions.items()
            }
        if self.workspace is not None:
            payload["workspace"] = str(self.workspace)
        if self.session_dir is not None:
            payload["session_dir"] = str(self.session_dir)
        if self.phases:
            payload["phases"] = [phase.to_dict() for phase in self.phases]
        if self.frozen:
            payload["frozen"] = [item.to_dict() for item in self.frozen]
        if self.reused_from_disk:
            payload["reused_from_disk"] = list(self.reused_from_disk)
        if self.restart_spreads:
            payload["restart_spreads"] = [item.to_dict() for item in self.restart_spreads]
        if self.steady_window is not None:
            payload["steady_window"] = dict(self.steady_window)
        if self.protocol is not None:
            payload["protocol"] = self.protocol
        if self.methods_paragraph is not None:
            payload["methods_paragraph"] = self.methods_paragraph
        if self.methods_path is not None:
            payload["methods_path"] = str(self.methods_path)
        if self.extra:
            payload["extra"] = dict(self.extra)
        return payload


CALIBRATE_SCHEMA = "hydromodpy.calibrate.v1"
"""The JSON Schema of what ``hmp calibrate --format json`` holds in ``data``."""


class CalibrationResult(BaseModel):
    """What ``hmp calibrate --format json`` writes: :meth:`CalibrationReport.to_dict`, as a contract.

    Experimental with the report it reads: its shape may change until the rework
    of the calibration is published. A key that does not apply is null.
    """

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(description="Id of the session the search belongs to.")
    method: str = Field(description="Optimizer method name.")
    status: str = Field(description="How the session closed: completed, partial, aborted, failed.")
    n_trials: int = Field(description="Number of trials actually run.")
    best_cost: float | None = Field(description="Lowest cost reached. Null if no trial completed.")
    duration_s: float = Field(description="Wall-clock duration of the search, in seconds.")
    save_runs: str = Field(description="The save_runs mode used: none, best_n or all.")
    promoted: int = Field(description="Count of trials promoted to runs after the search.")
    best_cases: dict[str, Any] = Field(
        description="The run and the cost of the best trial, by case."
    )
    best_sim_id: str | None = Field(default=None, description="Run of the one case.")
    best_rel_dir: str | None = Field(default=None, description="Its folder under the project.")
    cost_name: str | None = Field(default=None, description="Name of the cost minimized.")
    cost_label: str | None = Field(default=None, description="What it reads as: 1 - nse_log.")
    best_trial: int | None = Field(default=None, description="Number of the best trial.")
    best_parameters: dict[str, float] | None = Field(
        default=None, description="Physical values of the best candidate, by parameter name."
    )
    windows: dict[str, Any] | None = Field(
        default=None, description="The periods the best trial was scored on, by name."
    )
    parameter_uncertainty: list[dict[str, Any]] | None = Field(
        default=None, description="Width beside each calibrated value, when the file asked for one."
    )
    cost_block_fractions: dict[str, Any] | None = Field(
        default=None, description="Fraction of the cost each block took, 0 to 1."
    )
    workspace: str | None = Field(default=None, description="Project root of the session.")
    session_dir: str | None = Field(default=None, description="Folder of the session.")
    phases: list[dict[str, Any]] | None = Field(
        default=None, description="The phases in the order they ran, each with its own report."
    )
    frozen: list[dict[str, Any]] | None = Field(
        default=None, description="Every value a settled phase declared frozen."
    )
    reused_from_disk: list[str] | None = Field(
        default=None, description="The phases read back from the session instead of solved."
    )
    restart_spreads: list[dict[str, Any]] | None = Field(
        default=None, description="Where the restarts of each phase landed."
    )
    steady_window: dict[str, Any] | None = Field(
        default=None, description="The span a steady phase averaged its recharge over."
    )
    protocol: dict[str, Any] | None = Field(
        default=None, description="The published method that wrote these stages."
    )
    methods_paragraph: str | None = Field(
        default=None, description="The prose this run writes about itself."
    )
    methods_path: str | None = Field(default=None, description="The file that paragraph is in.")
    extra: dict[str, Any] | None = Field(default=None, description="Free-form metadata.")


def samples_text(samples: Mapping[str, Mapping[str, Any]]) -> str:
    """Return the pairs of ``extra["cost_samples"]`` in words, one clause per output."""
    return scored_samples_text(
        scored_entry(name, info, case_id="") for name, info in samples.items()
    )


def scored_entry(
    output: str, info: Mapping[str, Any], *, case_id: str, window: str = CALIBRATION_ROLE
) -> ScoredSamples:
    """Return one ``{n_paired, n_sim_nan, start, end}`` entry of a report as a :class:`ScoredSamples`."""
    return ScoredSamples(
        window=window,
        case_id=case_id,
        output=output,
        n=info["n_paired"],
        n_sim_nan=info.get("n_sim_nan"),
        first=info.get("start"),
        last=info.get("end"),
    )


def interval_is_degenerate(interval: Mapping[str, Any]) -> bool:
    """Whether an interval holds the best trial alone, so it has no width.

    ``interval`` is a :meth:`ParameterInterval.to_dict` record. Printed as
    ``[x, x]``, such an interval reads as a value known exactly, when it only
    says that no other trial scored within the cost margin.
    """
    n_within = interval.get("n_within")
    if n_within is not None and int(n_within) <= 1:
        return True
    return float(interval["lower"]) == float(interval["upper"])


def interval_best_is_on_a_bound(interval: Mapping[str, Any]) -> bool:
    """Whether the value itself sits on a search bound, not only the range around it."""
    best = float(interval["best"])
    return bool(
        (interval["reaches_lower_bound"] and best <= float(interval["lower"]))
        or (interval["reaches_upper_bound"] and best >= float(interval["upper"]))
    )


def promotion_failures(result: Any) -> list[str]:
    """Return the promotions a finished calibration could not write, one line each.

    Reads a calibration report or its ``to_dict`` summary. A line of a staged
    run starts with its phase name. The search results stay valid: only the
    replayed runs are missing.
    """
    summary = result.to_dict() if hasattr(result, "to_dict") else result
    if not isinstance(summary, Mapping):
        return []
    lines: list[str] = []
    for phase in summary.get("phases") or ():
        extra = phase["report"].get("extra") or {}
        for failure in extra.get("promotion_failures") or ():
            lines.append(f"phase {phase['phase']}: {failure}")
    extra = summary.get("extra")
    if isinstance(extra, Mapping):
        lines.extend(str(failure) for failure in extra.get("promotion_failures") or ())
    return lines


def unfinished_session(result: Any) -> str | None:
    """Return one line saying how the session of a calibration closed, unless completed.

    Reads ``session.json`` of the session a calibration report, or its
    ``to_dict`` summary, names. ``None`` when that session closed
    ``completed``, or when the result names no folder holding a descriptor.
    """
    summary = result.to_dict() if hasattr(result, "to_dict") else result
    if not isinstance(summary, Mapping) or not summary.get("session_dir"):
        return None
    session_dir = Path(summary["session_dir"])
    if not session_descriptor_path(session_dir).is_file():
        return None
    descriptor = read_session(session_dir)
    if descriptor.status == "completed":
        return None
    reason = f": {descriptor.error_message}" if descriptor.error_message else ""
    return f"Session {session_dir.name} closed {descriptor.status}{reason}"


__all__ = (
    "CALIBRATE_SCHEMA",
    "NO_OTHER_TRIAL",
    "CalibrationReport",
    "CalibrationResult",
    "FrozenParameter",
    "PhaseRun",
    "interval_best_is_on_a_bound",
    "interval_is_degenerate",
    "promotion_failures",
    "samples_text",
    "scored_entry",
    "unfinished_session",
)
