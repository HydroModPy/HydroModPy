"""Write run, attempt and session directories on disk the way a run does, without any index.

The indexer and the reader are tested on what the tree holds: a sealed run is
a ``RunRecord`` written by itself, an attempt is an ``outcome.json`` with its
pulse, a session is a descriptor with its journal. Nothing here opens
``.hmp/index.duckdb``.
"""

from __future__ import annotations

import hashlib
import tempfile
import uuid
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from hydromodpy.core.state.layout import PROJECT_MARKER_FILENAME
from hydromodpy.core.state.result_dirs import parse_rel_dir, run_dir_rel
from hydromodpy.core.toml_io.writer import dumps
from hydromodpy.results.catalog.registration import split_stem_version
from hydromodpy.results.heartbeat import Heartbeat, write_heartbeat
from hydromodpy.results.identity import Identity
from hydromodpy.results.metric_rule import DateWindow, PeriodWindow
from hydromodpy.results.outcome import Outcome, OutcomeError, write_outcome
from hydromodpy.results.record.checks import CalibratedBy, Checks
from hydromodpy.results.record.manifest import (
    ManifestConfig,
    ManifestGeometry,
    ManifestPeriod,
    ManifestRun,
    ManifestSite,
    MetricRow,
    ParameterRow,
    RunSeal,
)
from hydromodpy.results.record.record import RunProvenance, RunRecord
from hydromodpy.results.session.descriptor import (
    BestCase,
    BestTrial,
    ParameterBound,
    SessionCase,
    SessionDescriptor,
    write_session,
)
from hydromodpy.results.session.journal import TrialCase, TrialLine, TrialParam, append_trial
from hydromodpy.results.session.phase import PhaseDescriptor, write_phase
from hydromodpy.results.storage.contract import (
    RUN_CONFIG_FILENAME,
    RUN_RESOLVED_CONFIG_FILENAME,
    RUN_SEARCH_TABLE,
)
from hydromodpy.schema.lineage import Lineage
from tests._helpers.metric_rows import headline_row, headline_score

NOW = datetime(2026, 10, 15, 8, 2, 11, tzinfo=UTC)
WINDOW = DateWindow(start=date(2016, 1, 1), end=date(2020, 12, 31))
VERSION = "2.0.0a5"
SITE = "J0014010"
FINGERPRINT = "abcd1234abcd1234"
CONFIG_HASH = "c0ffee" * 10 + "c0ff"


def make_project(root: Path) -> Path:
    """Create a project root with its marker and return it."""
    root.mkdir(parents=True, exist_ok=True)
    (root / PROJECT_MARKER_FILENAME).write_text("[workspace]\n", encoding="utf-8")
    return root


def seal_run(
    project_root: Path,
    name: str,
    *,
    rel_dir: str | None = None,
    project: str = "demo",
    site: str | None = SITE,
    recipe: str | None = None,
    sim_id: str | None = None,
    attempt: int = 1,
    attempt_id: str | None = None,
    solver: str = "modflow6",
    mesh_engine: str | None = "regular",
    nse: float | None = 0.71,
    window: DateWindow | None = WINDOW,
    parameters: dict[str, float] | None = None,
    calibrated_by: CalibratedBy | None = None,
    converged: bool | None = True,
    hydromodpy_version: str = VERSION,
    created_at: datetime = NOW,
    config_text: str = "[flow]\nK = 1e-5\n",
    tags: tuple[str, ...] = (),
    with_outcome: bool = True,
) -> str:
    """Seal one run directory and return its ``sim_id``.

    ``rel_dir`` defaults to ``runs/<name>``; pass ``sessions/<x>/trials/0004``
    for a kept trial. The record is complete enough to be indexed and read
    back, and small enough to write in a test.
    """
    sid = sim_id or str(uuid.uuid4())
    aid = attempt_id or uuid.uuid4().hex
    rel = rel_dir or run_dir_rel(name)
    parse_rel_dir(rel)
    directory = project_root / rel
    directory.mkdir(parents=True, exist_ok=True)
    (directory / RUN_CONFIG_FILENAME).write_text(config_text, encoding="utf-8")
    config_hash = hashlib.sha256(config_text.encode("utf-8")).hexdigest()
    stem, version = split_stem_version(name)
    case_id = f"{site}-{recipe}" if site and recipe else name
    score = None
    metrics: list[MetricRow] = []
    if nse is not None and window is not None:
        station = site or "outlet"
        score = headline_score(
            nse, station=station, window=window, n_samples=1827, metric_rule_version="1"
        )
        metrics = [
            headline_row(
                "nse", nse, station=station, window=window, n_samples=1827, metric_rule_version="1"
            )
        ]
    manifest_site = None
    if site is not None:
        manifest_site = ManifestSite(
            name=site,
            label="Nancon",
            gauge=site,
            uri=f"hubeau:{site}",
            fingerprint=FINGERPRINT,
            x_outlet=350000.0,
            y_outlet=6800000.0,
            crs="EPSG:2154",
            area_km2=65.2,
        )
    record = RunRecord(
        run=ManifestRun(
            sim_id=sid,
            name=name,
            name_stem=stem,
            version=version or 1,
            status="completed",
            project=project,
            case_id=case_id,
            recipe=recipe,
            rel_dir=rel,
            attempt=attempt,
            attempt_id=aid,
            solver=solver,
            solver_category="distributed",
            flow_regime="transient",
            created_at=created_at,
            started_at=created_at,
            ended_at=created_at + timedelta(minutes=5),
            duration_s=300.0,
        ),
        site=manifest_site,
        geometry=ManifestGeometry(
            n_cells=64,
            n_layers=2,
            mesh_engine=mesh_engine,
            crs_wkt="EPSG:2154",
            crs_epsg=2154,
            bbox=(0.0, 0.0, 100.0, 100.0),
            catchment={"catch_area": 29.7, "x_outlet": 301.5, "y_outlet": 402.5},
        ),
        period=ManifestPeriod(
            start=datetime(2016, 1, 1, tzinfo=UTC),
            end=datetime(2020, 12, 31, tzinfo=UTC),
            n_timesteps=3,
            time_unit="day",
        ),
        config=ManifestConfig(file=RUN_CONFIG_FILENAME, source="project.toml"),
        lineage=Lineage(
            session_id=None if calibrated_by is None else calibrated_by.session_id,
            phase=None if calibrated_by is None else calibrated_by.phase,
            trial=None if calibrated_by is None else calibrated_by.trial,
            kind=None if calibrated_by is None else "promoted",
        ),
        identity=Identity(
            site=site,
            site_fingerprint=None if site is None else FINGERPRINT,
            case_id=case_id,
            sim_id=sid,
            attempt_id=aid,
            solution_key=config_hash,
            request_id=config_hash,
            period=WINDOW,
            score_window=window,
            hydromodpy_version=hydromodpy_version,
            code_reproducible=False,
        ),
        checks=Checks(
            budget_pct=0.8,
            budget_threshold_pct=2.0,
            converged=converged,
            score_window=window,
            n_samples=None if window is None else 1827,
            calibrated_by=calibrated_by,
            code_reproducible=False,
        ),
        parameters=[
            ParameterRow(name=key, value=value, unit="m/s", origin="declared", calibrated=False)
            for key, value in (parameters or {"K": 1e-5}).items()
        ],
        metrics=metrics,
        score=score,
        provenance=RunProvenance(
            sim_id=sid,
            tool={"name": "hydromodpy", "version": hydromodpy_version},
            python={"version": "3.13"},
            platform={"platform": "Linux", "hostname": "node12", "user": "bb"},
            solver={"name": solver, "engine": "executable"},
        ),
    )
    record.write(directory)
    if with_outcome:
        write_attempt(
            project_root,
            rel,
            status="completed",
            attempt=attempt,
            attempt_id=aid,
            case_id=case_id,
            site=site,
            project=project,
            sim_id=sid,
            started_at=created_at,
        )
    if tags:
        from hydromodpy.results.annotations import Annotations, write_annotations

        write_annotations(directory, Annotations(sim_id=sid, tags=tuple(tags)))
    return sid


def manifest_document(
    *, sim_id: str | None = None, name: str = "demo", config_hash: str = "0" * 64, **blocks: Any
) -> dict[str, Any]:
    """Return the JSON of a manifest its model reads, for a test that writes no run around it.

    A key of ``blocks`` replaces the key of the document, and ``run`` updates its block.
    """
    sid = sim_id or str(uuid.uuid4())
    stem, version = split_stem_version(name)
    document = RunSeal(
        sealed_at=NOW,
        run=ManifestRun(
            sim_id=sid,
            name=name,
            name_stem=stem,
            version=version or 1,
            status="completed",
            project="demo",
            case_id=name,
            rel_dir=run_dir_rel(name),
            attempt=1,
            attempt_id="a" * 32,
            solver="modflow6",
            created_at=NOW,
        ),
        geometry=ManifestGeometry(),
        period=ManifestPeriod(),
        config=ManifestConfig(file=RUN_CONFIG_FILENAME),
        lineage=Lineage(),
        identity=Identity(
            case_id=name,
            sim_id=sid,
            attempt_id="a" * 32,
            solution_key=config_hash,
            request_id=config_hash,
            hydromodpy_version=VERSION,
        ),
        checks=Checks(),
    ).model_dump(mode="json")
    document["run"].update(blocks.pop("run", {}))
    document.update(blocks)
    return document


def write_attempt(
    project_root: Path,
    rel_dir: str,
    *,
    status: str = "running",
    attempt: int = 1,
    attempt_id: str | None = None,
    case_id: str | None = None,
    site: str | None = SITE,
    project: str = "demo",
    sim_id: str | None = None,
    started_at: datetime = NOW,
    heartbeat_age_s: float | None = None,
    step: str | None = "run_solver",
    error: tuple[str, str] | None = None,
    host: str = "node12",
    pid: int = 4421,
) -> Path:
    """Write the ``outcome.json`` of one attempt, and its pulse when asked.

    ``heartbeat_age_s`` writes ``logs/heartbeat.json`` dated that many seconds
    before now. A ``failed`` attempt carries ``error`` as ``(type, message)``.
    Returns the directory.
    """
    directory = project_root / parse_rel_dir(rel_dir).as_posix()
    directory.mkdir(parents=True, exist_ok=True)
    aid = attempt_id or uuid.uuid4().hex
    payload: dict[str, Any] = {
        "case_id": case_id or parse_rel_dir(rel_dir).name,
        "site": site,
        "project": project,
        "attempt": attempt,
        "attempt_id": aid,
        "sim_id": sim_id,
        "status": status,
        "written_by": "worker",
        "started_at": started_at,
        "host": host,
        "pid": pid,
        "step": step,
    }
    if status != "running":
        payload["ended_at"] = started_at + timedelta(minutes=3)
        payload["exit_code"] = 0 if status == "completed" else 15
    if status == "failed":
        kind, message = error or ("SolverError", "mf6 did not converge at stress period 51")
        payload["error"] = OutcomeError(type=kind, message=message)
        payload["log_tail"] = ["stress period 51 failed"]
    write_outcome(directory, Outcome(**payload))
    if heartbeat_age_s is not None:
        write_heartbeat(
            directory,
            Heartbeat(
                at=datetime.now(UTC) - timedelta(seconds=heartbeat_age_s),
                pid=pid,
                host=host,
                attempt_id=aid,
                step=step,
            ),
        )
    return directory


def write_session_dir(
    project_root: Path,
    name: str,
    *,
    session_id: str | None = None,
    case_id: str | None = None,
    site: str | None = SITE,
    status: str = "completed",
    started_at: datetime = NOW,
    trials: int = 2,
    best_trial: int | None = None,
    best_sim_id: str | None = None,
    best_rel_dir: str | None = None,
    phases: tuple[str, ...] = ("steady_k",),
    objective: str = "nse_log",
    root_search: dict[str, Any] | None = None,
) -> str:
    """Write ``sessions/<name>/`` with its descriptor, journal and phases; return the session id."""
    sid = session_id or uuid.uuid4().hex
    directory = project_root / "sessions" / name
    directory.mkdir(parents=True, exist_ok=True)
    ended = None if status == "running" else started_at + timedelta(hours=1)
    case = case_id or name
    best = None
    if best_trial is not None:
        best = BestTrial(
            trial=best_trial,
            cost=-0.84,
            parameters={"K": 1e-5 * best_trial},
            cases={case: BestCase(sim_id=best_sim_id, rel_dir=best_rel_dir, cost=-0.84)},
        )
    write_session(
        directory,
        SessionDescriptor(
            session_id=sid,
            case_id=case,
            config_hash=CONFIG_HASH,
            sites=[site] if site else [],
            cases={
                case: SessionCase(
                    site=site,
                    config_hash=CONFIG_HASH,
                    config_file="config.toml",
                    cost_name=objective,
                )
            },
            hydromodpy_version=VERSION,
            method="tpe",
            bounds={"K": ParameterBound(lower=1e-7, upper=1e-4, search_space="log")},
            cost_name=objective,
            windows={
                "calibration": PeriodWindow(role="calibration", start=WINDOW.start, end=WINDOW.end)
            },
            best=best,
            status=status,
            started_at=started_at,
            ended_at=ended,
            root_search=root_search,
        ),
    )
    for index, phase in enumerate(phases):
        write_phase(
            directory,
            PhaseDescriptor(
                phase_id=f"{sid[:8]}-{index}",
                name=phase,
                index=index,
                status=status,
                frozen={},
                restarts=0,
            ),
        )
    for number in range(1, trials + 1):
        append_trial(
            directory,
            TrialLine(
                trial=number,
                phase=phases[0],
                params={"K": TrialParam(value=1e-5 * number)},
                cost=-0.5 - 0.1 * number,
                cases={
                    case: TrialCase(
                        cost=-0.5 - 0.1 * number,
                        status="completed",
                        params_hash=f"h{number}",
                        sim_id=best_sim_id if number == best_trial else None,
                        rel_dir=best_rel_dir if number == best_trial else None,
                    )
                },
                status="completed",
                started_at=started_at + timedelta(minutes=number),
                ended_at=started_at + timedelta(minutes=number + 1),
            ),
        )
    return sid


def sealed_search(calibration: Mapping[str, Any]) -> Path:
    """Return a folder whose ``config.resolved.toml`` holds the search a promoted run came from.

    A stand-in run takes it as its ``dir``, where ``search_of`` reads it.
    """
    folder = Path(tempfile.mkdtemp(prefix="sealed-search-"))
    document = dumps({RUN_SEARCH_TABLE: dict(calibration)})
    (folder / RUN_RESOLVED_CONFIG_FILENAME).write_text(document, encoding="utf-8")
    return folder


__all__ = [
    "sealed_search",
    "FINGERPRINT",
    "NOW",
    "SITE",
    "VERSION",
    "WINDOW",
    "make_project",
    "seal_run",
    "write_attempt",
    "write_session_dir",
]
