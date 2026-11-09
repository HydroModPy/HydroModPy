"""Data-overview launcher - "watershed identity card" workflow.

Orchestrates four phases:

1. **WorkspaceLayout** - prepare output directories.
2. **Geographic** - delineate watershed from outlet coordinates.
3. **Data loading** - download / load all requested data families.
4. **Report** - generate overview PNGs (one per panel).

An overview is a run like any other: the caller claims ``runs/<name>/``
through the attempt protocol and hands the claim over; the launcher writes
its panels and pages there, then seals the directory with a record that
holds no solver table (:meth:`DataOverviewLauncher.seal`).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hydromodpy.config import HydroModPyConfig
from hydromodpy.core.console import progress
from hydromodpy.core.contracts.overview import DataOverviewState
from hydromodpy.core.exceptions import ConfigError, ConfigMissingError
from hydromodpy.core.logging import get_logger
from hydromodpy.core.runtime.bounds import Bounds
from hydromodpy.core.state.layout import PROJECT_MARKER_FILENAME
from hydromodpy.core.state.run_state import SetupContext, WorkflowContext
from hydromodpy.results.storage.attempt import RunClaim
from hydromodpy.workflow.steps.setup import resolve_geographic_inputs

logger = get_logger(__name__)

OVERVIEW_SOLVER = "overview"
"""What the seal of an overview names as its solver: it solves nothing."""


@dataclass(frozen=True, slots=True)
class OverviewResult:
    """What an overview drew, and where it sealed it."""

    name: str | None
    run_dir: Path | None
    catchment_area_km2: float | None
    report_paths: tuple[Path, ...]
    web_report: Path | None

    def to_dict(self) -> dict[str, Any]:
        """Return the result as text and numbers, for a program."""
        return {
            "mode": "data_overview",
            "name": self.name,
            "run_dir": None if self.run_dir is None else str(self.run_dir),
            "catchment_area_km2": self.catchment_area_km2,
            "report_paths": [str(path) for path in self.report_paths],
            "web_report": None if self.web_report is None else str(self.web_report),
        }


class DataOverviewLauncher:
    """Generate a "watershed identity card" from a loaded configuration.

    *base* is the folder the relative paths of the configuration were read from.
    *source* is the file the configuration came from, when it came from one: it
    is recorded in the seal. A configuration with no file anchors its relative
    paths on the project root, where ``project.toml`` would be.
    """

    def __init__(
        self,
        cfg: HydroModPyConfig,
        *,
        base: str | Path,
        source: str | Path | None = None,
        bounds: Bounds | None = None,
    ) -> None:
        self.cfg = cfg
        self.base = Path(base).resolve()
        self.source = None if source is None else Path(source).resolve()
        self.config_path = (
            self.source
            if self.source is not None
            else Path(cfg.workspace.project_root) / PROJECT_MARKER_FILENAME
        )
        # The bounds of the call that asked for the overview, or the
        # default of the machine: every context this launcher builds
        # carries them.
        self.bounds = bounds if bounds is not None else Bounds()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self, claim: RunClaim | None = None, *, config_hash: str | None = None
    ) -> OverviewResult:
        """Execute the full overview pipeline and return what it drew.

        With the *claim* of its run directory, the overview seals that
        directory once its report is drawn.
        """
        state = DataOverviewState(cfg=self.cfg, config_path=self.config_path)

        # Phase 1: WorkspaceLayout
        self._setup_workspace(state)

        # Phase 1b: the DEM, the crossings and the network map, as files on disk
        with progress.phase("Resolving the DEM and the crossings"):
            network_map_path, dem_path = self._resolve_geographic_inputs(state)

        # Phase 2: Geographic (watershed delineation)
        with progress.phase("Delineating the catchment"):
            self._setup_geographic(state, network_map_path, dem_path)

        # Phase 3: Data loading
        with progress.phase("Loading data"):
            self._load_data(state)

        # Phase 4: Report generation
        with progress.phase("Drawing the report"):
            report_paths = self._generate_report(state)

        from hydromodpy.display.overview import overview_web_report_path

        web_report = overview_web_report_path(state) if report_paths else None
        if claim is not None:
            self.seal(state, claim, config_hash=config_hash)
        return OverviewResult(
            name=claim.name if claim is not None else getattr(self.cfg.overview, "name", None),
            run_dir=None if claim is None else Path(claim.run_dir),
            catchment_area_km2=(
                state.domain_geographic.catchment_area_km2 if state.domain_geographic else None
            ),
            report_paths=tuple(Path(path) for path in report_paths),
            web_report=Path(web_report) if web_report and Path(web_report).is_file() else None,
        )

    def seal(self, state: DataOverviewState, claim: RunClaim, *, config_hash: str | None) -> Any:
        """Seal the run directory of the overview and return its record.

        The record carries the identity of the overview (site, configuration,
        period, catchment) and no solver table: no field store, no budget, no
        series. ``config.toml`` is frozen first, ``manifest.json`` is written
        last, then ``README.md``; the attempt protocol flips the outcome.
        """
        from hydromodpy.core.io.atomic_replace import staged_path
        from hydromodpy.results.catalog.registration import portable_config_source
        from hydromodpy.results.outcome import read_outcome
        from hydromodpy.results.storage.contract import RUN_CONFIG_FILENAME
        from hydromodpy.results.storage.run_facts import RunFacts
        from hydromodpy.results.storage.run_store import RunStore
        from hydromodpy.results.storage.sealing import seal_completed
        from hydromodpy.workflow.steps.prepare_solver.dispatch import planned_recipe
        from hydromodpy.workflow.steps.prepare_solver.facts import site_block
        from hydromodpy.workflow.steps.prepare_solver.freeze import portable_config_document

        run_dir = claim.run_dir
        project_root = Path(self.cfg.workspace.project_root)
        with staged_path(run_dir / RUN_CONFIG_FILENAME) as staged:
            staged.write_text(
                portable_config_document(self.cfg, run_dir, project_root), encoding="utf-8"
            )
        outcome = read_outcome(run_dir)
        overview = self.cfg.overview
        area = state.domain_geographic.catchment_area_km2 if state.domain_geographic else None
        case_id = outcome.case_id if outcome is not None else claim.name
        facts = RunFacts(
            sim_id=claim.sim_id,
            name=claim.name,
            case_id=case_id,
            recipe=planned_recipe(project_root, case_id),
            project=(outcome.project if outcome is not None else None) or project_root.name,
            attempt=claim.attempt,
            attempt_id=claim.attempt_id,
            created_at=claim.started_at,
            started_at=claim.started_at,
            solver=OVERVIEW_SOLVER,
            config_hash=config_hash,
            config_source=(
                None
                if self.source is None
                else portable_config_source(project_root, str(self.source))
            ),
            config_file=RUN_CONFIG_FILENAME,
            description=getattr(overview, "name", None) if overview is not None else None,
            period_start=_instant(getattr(overview, "date_start", None)),
            period_end=_instant(getattr(overview, "date_end", None)),
            site=site_block(state),
            geographic_metadata={} if area is None else {"catchment_area_km2": float(area)},
        )
        store = RunStore.open(run_dir, facts=facts, workspace=project_root)
        return seal_completed(store)

    # ------------------------------------------------------------------
    # Phase 1 - WorkspaceLayout
    # ------------------------------------------------------------------

    @staticmethod
    def _setup_workspace(state: DataOverviewState) -> None:
        from hydromodpy.core.workspace.workspace import WorkspaceLayout

        state.workspace = WorkspaceLayout(config=state.cfg.workspace)
        logger.debug("[overview] WorkspaceLayout: %s", state.workspace.project_root)

    # ------------------------------------------------------------------
    # Phase 1b - DEM, crossings and network map as files on disk
    # ------------------------------------------------------------------

    def _context(self, state: DataOverviewState, cfg: Any = None) -> WorkflowContext:
        """Return the workflow context the shared resolvers and the loader read."""
        return WorkflowContext(
            cfg=state.cfg if cfg is None else cfg,
            config_path=self.config_path,
            raw_toml={},
            setup=SetupContext(workspace=state.workspace, geographic=state.geographic),
            loaded_data=state.loaded_data,
            bounds=self.bounds,
        )

    def _resolve_geographic_inputs(self, state: DataOverviewState) -> tuple[Path | None, Path]:
        """Resolve the crossings and the DEM like a simulation run.

        Delegates to :func:`resolve_geographic_inputs`, so the overview and the
        simulation pipeline apply one rule. One difference is kept: an overview
        with no DEM at all raises :class:`ConfigMissingError` and says how to
        declare one, where a simulation lets the geographic step fail later.
        Returns the network map of alpha and the DEM raster.
        """
        context = self._context(state)
        network_map_path = resolve_geographic_inputs(state.cfg, context)
        dem_record = getattr(context.setup, "dem_record", None)
        if dem_record is None:
            raise ConfigMissingError(
                "No [data.dem] source configured. Add:\n"
                '  [data]\n  types = [..., "dem"]\n'
                '  [[data.dem.sources]]\n  source = "ign_geoplateforme_dem"\n'
                '  dataset = "bd-alti"\n  resolution_m = 25.0\n'
                "or:\n"
                '  [[data.dem.sources]]\n  source = "file"\n  path = "inputs/dem.tif"'
            )
        return network_map_path, Path(dem_record.path)

    # ------------------------------------------------------------------
    # Phase 2 - Geographic
    # ------------------------------------------------------------------

    @staticmethod
    def _setup_geographic(
        state: DataOverviewState, network_map_path: Path | None, dem_path: Path | None = None
    ) -> None:
        from hydromodpy.catchment.algorithms.derived_features import (
            coerce_geographic_derived_features,
        )
        from hydromodpy.catchment.preprocess.catchment_delineation import CatchmentDelineation

        geographic = CatchmentDelineation(
            state.cfg.geographic,
            state.workspace,
            dem_path=dem_path,
            network_map_path=network_map_path,
        )
        state.geographic = geographic

        geographic_features = coerce_geographic_derived_features(
            geographic=geographic,
        )
        if geographic_features is None:
            raise ConfigError(
                "Could not resolve geographic derived features from the overview geographic runtime."
            )
        state.geographic_features = geographic_features
        domain_geo = geographic_features.to_domain_geographic_context()
        state.domain_geographic = domain_geo
        logger.info(
            "[overview] Catchment area: %.2f km2",
            domain_geo.catchment_area_km2,
        )

    # ------------------------------------------------------------------
    # Phase 3 - Data loading
    # ------------------------------------------------------------------

    def _load_data(self, state: DataOverviewState) -> None:
        """Load every data family declared in ``[data].types`` into ``state.loaded_data``.

        Uses :class:`DataLoader` on a ``WorkflowContext`` built
        from the overview state. Overview dates from ``[overview]`` are
        injected into data sections that have no explicit dates of their own.
        """
        from hydromodpy.catchment.algorithms.derived_features import (
            attach_reference_hydrographic_network,
        )
        from hydromodpy.data import DataLoader, DataLoadPlan

        data_plan = DataLoadPlan(
            explicit_types=tuple(state.cfg.data.types),
            inferred_types=(),
        )
        logger.info("[overview] Loading data for: %s", list(data_plan.types))

        self._inject_overview_dates(state)

        # Overview mode has no [simulation]: the loader takes its window from [overview].
        context = self._context(state, state.cfg.model_copy(update={"simulation": None}))
        context.data_plan = data_plan

        loader = DataLoader(
            config_path=self.config_path,
            data_plan=data_plan,
            bounds=self.bounds,
        )
        loader.load_all(context)
        if state.geographic_features is not None:
            state.geographic_features = attach_reference_hydrographic_network(
                state.geographic_features,
                state.loaded_data.hydrography,
            )

    @staticmethod
    def _inject_overview_dates(state: DataOverviewState) -> None:
        """Copy ``[overview].date_start/date_end`` into data sections missing them.

        Overview mode has no ``[simulation.time]``, so ``[overview]`` plays the
        role of the single date declaration. Same rule as the runtime loader:
        a section that declares a window keeps it, a section that declares
        none inherits the whole pair.
        """
        overview = state.cfg.overview
        if overview is None or not overview.date_start or not overview.date_end:
            return

        for type_name in state.cfg.data.types:
            section = getattr(state.cfg.data, type_name, None)
            if section is None or not hasattr(section, "date_start"):
                continue
            if getattr(section, "date_start", None) or getattr(section, "date_end", None):
                continue
            # Assigning the pair in one setattr makes the parent revalidate the
            # section, so an invalid [overview] window is rejected. Setting the
            # two attributes one by one would not: pydantic writes each value
            # into __dict__ before the model validator raises, so a reversed
            # window would ship silently.
            setattr(
                state.cfg.data,
                type_name,
                section.model_copy(
                    update={
                        "date_start": overview.date_start,
                        "date_end": overview.date_end,
                    }
                ),
            )

    # ------------------------------------------------------------------
    # Phase 4 - Report generation
    # ------------------------------------------------------------------

    @staticmethod
    def _generate_report(state: DataOverviewState) -> list[Path]:
        from hydromodpy.display.overview import generate_overview_report

        return generate_overview_report(state)


def _instant(value: Any) -> Any:
    """Return a date of the overview window as a UTC instant, or None."""
    if value is None:
        return None
    from datetime import UTC, datetime

    import pandas as pd

    stamp = pd.Timestamp(value)
    moment: datetime = stamp.to_pydatetime()
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)
