"""Data-overview launcher - "watershed identity card" workflow.

Orchestrates four phases:

1. **WorkspaceLayout** - prepare output directories.
2. **Geographic** - delineate watershed from outlet coordinates.
3. **Data loading** - download / load all requested data families.
4. **Report** - generate overview PNGs (one per panel).

An overview is a run like any other: the caller claims ``runs/<name>/``
through the attempt protocol and hands the claim over; the launcher writes
its panels and pages there, then seals the directory with a record that
holds no solver table (:meth:`DataOverviewLauncher.seal`). The seal also
writes what the page counts, ``tables.parquet/data_inventory.parquet``
(:func:`inventory_rows`), and lists the inputs it loaded in ``inputs.json``.
The page itself is written after the seal, from the sealed directory.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import UTC, datetime
from pathlib import Path
from statistics import fmean
from typing import Any

from hydromodpy.config import HydroModPyConfig
from hydromodpy.core.console import progress
from hydromodpy.core.contracts.overview import DataOverviewState
from hydromodpy.core.exceptions import ConfigError, ConfigMissingError
from hydromodpy.core.licensing import UNDETERMINED_LICENSE
from hydromodpy.core.logging import get_logger
from hydromodpy.core.runtime.bounds import Bounds
from hydromodpy.core.state.layout import PROJECT_MARKER_FILENAME
from hydromodpy.core.state.portable import encode_workspace_path
from hydromodpy.core.state.run_state import LoadedDataContext, SetupContext, WorkflowContext
from hydromodpy.data.contracts.spatial_field import INPUT_FILES_KEY
from hydromodpy.results.record.manifest import InputEntry
from hydromodpy.results.storage.attempt import RunClaim, is_run_product
from hydromodpy.results.storage.digests import path_size_bytes
from hydromodpy.schema.sources import input_licence
from hydromodpy.workflow.steps.data_description import (
    iter_loaded_records,
    record_source_path,
    sha256_file_or_none,
)
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
        self, claim: RunClaim | None = None, *, solution_key: str | None = None
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

        # Phase 4: panels, drawn from the state in memory
        with progress.phase("Drawing the report"):
            inventory = inventory_rows(state)
            report_paths = self._generate_report(state, inventory)

        web_report = None
        if claim is not None:
            self.seal(state, claim, solution_key=solution_key, inventory=inventory)
            if report_paths:
                web_report = self._write_page(Path(claim.run_dir))
        return OverviewResult(
            name=claim.name if claim is not None else getattr(self.cfg.overview, "name", None),
            run_dir=None if claim is None else Path(claim.run_dir),
            catchment_area_km2=(
                state.domain_geographic.catchment_area_km2 if state.domain_geographic else None
            ),
            report_paths=tuple(Path(path) for path in report_paths),
            web_report=web_report,
        )

    def seal(
        self,
        state: DataOverviewState,
        claim: RunClaim,
        *,
        solution_key: str | None,
        inventory: list[dict[str, Any]] | None = None,
    ) -> Any:
        """Seal the run directory of the overview and return its record.

        The record carries the identity of the overview (site, solution key,
        period, catchment) and no solver table: no field store, no budget, no
        series. It holds the inventory of the loaded data and lists the loaded
        inputs. ``config.toml`` is frozen first, ``manifest.json`` is written
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
            solution_key=solution_key,
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
        rows = inventory_rows(state) if inventory is None else inventory
        store.write_view(claim.sim_id, "data_inventory", rows)
        for entry in loaded_inputs(state, project_root):
            store.record_input(claim.sim_id, entry)
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
    def _generate_report(state: DataOverviewState, inventory: list[dict[str, Any]]) -> list[Path]:
        from hydromodpy.display.overview import generate_overview_report

        return generate_overview_report(state, inventory)

    @staticmethod
    def _write_page(run_dir: Path) -> Path | None:
        """Write the page of the sealed overview and return its ``index.html``."""
        from datetime import date

        from hydromodpy.display.report.engine import write_pages
        from hydromodpy.display.report.pages import overview_blocks
        from hydromodpy.results.run import open_run_dir
        from hydromodpy.results.storage.contract import RUN_REPORT_DIRNAME

        run = open_run_dir(run_dir)
        index = write_pages(
            run_dir / RUN_REPORT_DIRNAME,
            title=run.name or "Catchment data view",
            subtitle="Catchment data view",
            blocks=overview_blocks(run),
            rendered=date.today(),
        )
        return Path(index) if Path(index).is_file() else None


def _instant(value: Any) -> datetime | None:
    """Return a date of the overview window as a UTC instant, or None."""
    if value is None:
        return None
    import pandas as pd

    stamp = pd.Timestamp(value)
    moment: datetime = stamp.to_pydatetime()
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)


# ----------------------------------------------------------------------
# What the overview counts: the rows of data_inventory and inputs.json
# ----------------------------------------------------------------------

_POINT_FAMILIES = ("hydrometry", "piezometry", "intermittency", "water_quality")
"""Families whose points are stations: one ``station`` row per station."""

_PER_DAY_UNITS = frozenset({"mm/day", "mm d-1", "mm/d"})


def inventory_rows(state: DataOverviewState) -> list[dict[str, Any]]:
    """Return the rows of ``data_inventory`` for the loaded data of *state*.

    One ``family`` row per family requested or loaded (``records`` is 0 for a
    family that was requested and not loaded), one ``station`` row per station
    of a point family and one ``well`` row per well of ``[flow.sinks_sources]``.
    A station seen in several records (water quality emits one per parameter)
    is one row whose period is the union of its records.
    """
    data_cfg = getattr(state.cfg, "data", None)
    requested = {str(item).strip().lower() for item in getattr(data_cfg, "types", ()) or ()}
    rows: list[dict[str, Any]] = []
    for family in _family_order(data_cfg):
        loaded = getattr(state.loaded_data, family, None)
        if family not in requested and not loaded:
            continue
        section = getattr(data_cfg, family, None)
        first, last = _section_window(section) if section is not None else (None, None)
        if first is None and last is None:
            first, last = _records_window(loaded)
        mean_value, unit = _family_mean(family, loaded)
        rows.append(
            _row(
                "family",
                family,
                source=", ".join(_source_names(section)),
                first=first,
                last=last,
                records=_object_count(loaded),
                mean_value=mean_value,
                unit=unit,
            )
        )
        if family in _POINT_FAMILIES:
            rows.extend(_station_rows(family, loaded))
    rows.extend(_well_rows(state))
    return rows


def _row(row_kind: str, family: str, **values: Any) -> dict[str, Any]:
    """Return a full row: every column of the schema except ``sim_id``."""
    row: dict[str, Any] = {
        "row_kind": row_kind,
        "family": family,
        "source": "",
        "item_id": "",
        "name": None,
        "x": None,
        "y": None,
        "crs_epsg": None,
        "first": None,
        "last": None,
        "records": 0,
        "mean_value": None,
        "unit": None,
    }
    row.update(values)
    return row


def _family_order(data_cfg: Any) -> tuple[str, ...]:
    """Return the families in the order of ``[data].types``, then the others."""
    ordered: list[str] = []
    for family in getattr(data_cfg, "types", ()) or ():
        name = str(family).strip().lower()
        if name and name not in ordered:
            ordered.append(name)
    ordered.extend(f.name for f in fields(LoadedDataContext) if f.name not in ordered)
    return tuple(ordered)


def _source_names(section: Any) -> list[str]:
    names = (getattr(source, "source", "") for source in getattr(section, "sources", ()) or ())
    return [str(name) for name in names if name]


def _section_window(section: Any) -> tuple[datetime | None, datetime | None]:
    return _instant(getattr(section, "date_start", None) or None), _instant(
        getattr(section, "date_end", None) or None
    )


def _records_window(load_result: Any) -> tuple[datetime | None, datetime | None]:
    """Return the union of the periods of the records of a load result."""
    starts, ends = [], []
    for record in getattr(load_result, "all_records", ()) or ():
        start, end = getattr(record, "date_start", None), getattr(record, "date_end", None)
        if start is not None:
            starts.append(_instant(start))
        if end is not None:
            ends.append(_instant(end))
    return (min(starts) if starts else None, max(ends) if ends else None)


def _object_count(load_result: Any) -> int:
    """Count the points and the fields a family loaded."""
    if not load_result:
        return 0
    count = len(getattr(load_result, "points", ()) or ()) + len(
        getattr(load_result, "fields", ()) or ()
    )
    return count or 1


def _family_mean(family: str, load_result: Any) -> tuple[float | None, str | None]:
    """Return the mean of the recharge in mm/year, else the mean in its own unit."""
    if family != "recharge" or not load_result:
        return None, None
    values: list[float] = []
    units: list[str] = []
    for record in getattr(load_result, "points", ()) or ():
        data = getattr(record, "data", None)
        if data is None or "value" not in data:
            continue
        series = data["value"].dropna()
        if not series.empty:
            values.append(float(series.mean()))
            units.append(str(getattr(record, "unit", "") or ""))
    for record in getattr(load_result, "fields", ()) or ():
        mean_value = _field_mean(record)
        if mean_value is not None:
            values.append(mean_value)
            units.append(str(getattr(record, "unit", "") or ""))
    if not values:
        return None, None
    unit = units[0]
    mean_value = fmean(values)
    if unit.lower() in _PER_DAY_UNITS:
        return mean_value * 365.25, "mm/year"
    return mean_value, unit or None


def _field_mean(record: Any) -> float | None:
    """Return the mean of a field over space and time, or None when it cannot be read."""
    import numpy as np

    try:
        dataset = record.dataset
        if hasattr(dataset, "data_vars"):
            arrays = [np.asarray(dataset[name].values, dtype=float) for name in dataset.data_vars]
        else:
            arrays = [np.asarray(dataset, dtype=float)]
    except Exception:
        # A field that cannot be opened has no mean; the row keeps its count.
        return None
    means = [float(np.nanmean(array)) for array in arrays if array.size]
    finite = [value for value in means if np.isfinite(value)]
    return fmean(finite) if finite else None


def _station_rows(family: str, load_result: Any) -> list[dict[str, Any]]:
    """Return one row per station of a point family, deduplicated by station id."""
    stations: dict[str, dict[str, Any]] = {}
    for record in getattr(load_result, "points", ()) or ():
        station = str(getattr(record, "station_id", ""))
        location = getattr(record, "location", None)
        start, end = getattr(record, "date_start", None), getattr(record, "date_end", None)
        start, end = (_instant(start), _instant(end))
        row = stations.get(station)
        if row is None:
            metadata = getattr(location, "metadata", None)
            name = metadata.get("station_name") or metadata.get("name") if metadata else None
            stations[station] = _row(
                "station",
                family,
                source=str(getattr(record, "source", "") or ""),
                item_id=station,
                name=None if not name else str(name),
                x=_float_or_none(getattr(location, "x", None)),
                y=_float_or_none(getattr(location, "y", None)),
                crs_epsg=_epsg(getattr(location, "crs", None)),
                first=start,
                last=end,
                records=1,
            )
            continue
        row["records"] += 1
        if start is not None and (row["first"] is None or start < row["first"]):
            row["first"] = start
        if end is not None and (row["last"] is None or end > row["last"]):
            row["last"] = end
    return list(stations.values())


def _well_rows(state: DataOverviewState) -> list[dict[str, Any]]:
    """Return the ``pumping`` family row and one row per well of the configuration."""
    sinks = getattr(getattr(state.cfg, "flow", None), "sinks_sources", None)
    wells = getattr(sinks, "wells", None) or {}
    if not wells:
        return []
    rows: list[dict[str, Any]] = []
    total = 0.0
    units = "m3/s"
    for well_id, well in wells.items():
        flux = _mean_flux(getattr(well, "flux", None))
        units = str(getattr(well, "units", units) or units)
        if flux is not None and flux < 0:
            total += -flux
        location = getattr(well, "location", None)
        rows.append(
            _row(
                "well",
                "pumping",
                item_id=str(well_id),
                x=_float_or_none(getattr(location, "x", None)),
                y=_float_or_none(getattr(location, "y", None)),
                records=1,
                mean_value=flux,
                unit=units,
            )
        )
    family = _row("family", "pumping", records=len(rows), mean_value=total, unit=units)
    return [family, *rows]


def _mean_flux(flux: Any) -> float | None:
    if isinstance(flux, bool) or flux is None:
        return None
    if isinstance(flux, (int, float)):
        return float(flux)
    if isinstance(flux, (list, tuple)) and flux:
        return fmean(float(item) for item in flux)
    return None


def _float_or_none(value: Any) -> float | None:
    return None if value is None else float(value)


def _epsg(crs: Any) -> int | None:
    """Return the EPSG code of a CRS given as a code, a string or an object, else None."""
    if crs in (None, ""):
        return None
    from pyproj import CRS
    from pyproj.exceptions import CRSError

    try:
        return CRS.from_user_input(crs).to_epsg()
    except CRSError:
        return None


def loaded_inputs(state: DataOverviewState, project_root: Path) -> list[InputEntry]:
    """Return the ``inputs.json`` entries of the records the overview loaded.

    Same rule as a simulation: one entry per file a record was read from, with
    its provider, request, digest and licence. A product of the run itself is
    no input.
    """
    anchor = Path(getattr(state.workspace, "root", None) or project_root)
    entries: list[InputEntry] = []
    for item in iter_loaded_records(state.loaded_data):
        record = item.record
        source_path = record_source_path(record)
        for path, provider in _input_files(record, source_path):
            if is_run_product(path, project_root):
                continue
            entries.append(
                _input_entry(item.scope, item.variable, record, path, provider, anchor=anchor)
            )
    return entries


def _input_files(record: Any, source_path: Path | None) -> list[tuple[Path, str | None]]:
    """Return the files a record was read from, each with its provider when it names one."""
    metadata = getattr(record, "metadata", None)
    listed = metadata.get(INPUT_FILES_KEY) if isinstance(metadata, dict) else None
    if listed:
        return [(Path(str(entry["path"])), str(entry["provider"])) for entry in listed]
    return [] if source_path is None else [(source_path, None)]


def _input_entry(
    scope: str,
    variable: str,
    record: Any,
    path: Path,
    provider: str | None,
    *,
    anchor: Path,
) -> InputEntry:
    request: dict[str, Any] = {}
    station = getattr(record, "station_id", None)
    if station not in (None, ""):
        request["station"] = str(station)
    start, end = getattr(record, "date_start", None), getattr(record, "date_end", None)
    if start is not None or end is not None:
        request["period"] = [_iso(start), _iso(end)]
    bbox = getattr(record, "bbox", None)
    if bbox is not None:
        request["bbox"] = [float(value) for value in bbox]
    exists = path.exists()
    try:
        located = encode_workspace_path(anchor, path)
    except ValueError:
        located = str(path)
    return InputEntry(
        variable=f"{scope}:{variable}",
        provider=provider or str(getattr(record, "source", "") or "") or "unknown",
        request=request,
        fetched_at=datetime.fromtimestamp(path.stat().st_mtime, tz=UTC) if exists else None,
        path=located,
        sha256=sha256_file_or_none(path),
        bytes=path_size_bytes(path) if exists else None,
        license=input_licence(path).spdx if exists else UNDETERMINED_LICENSE,
    )


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    isoformat = getattr(value, "isoformat", None)
    return isoformat() if callable(isoformat) else str(value)
