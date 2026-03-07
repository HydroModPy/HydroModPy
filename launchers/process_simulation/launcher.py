"""HydroModPy launcher driven by an explicit simulation plan.

This module is the user-facing entry point that turns a declarative TOML file
into a concrete modeling run.

The launcher deliberately stays thin:

1. it loads and validates the configuration,
2. it prepares shared runtime context used by process solvers,
3. it asks the simulation layer to resolve the declared process list,
4. it delegates the actual solver execution to ``SimulationRunner``.

That separation matters because three concerns stay isolated:

- ``HydroModPyLauncher`` handles I/O-oriented bootstrap work
  (paths, raw TOML, shared objects),
- ``SimulationPlanner`` handles dependency logic
  (for example: a transport run may require a specific flow solver first),
- ``SimulationRunner`` handles side effects
  (writing models, launching binaries, storing produced models).

In practice, the launcher consumes a TOML structure like::

    [simulation]
    name = "Example 12 launcher baseline"
    description = "Transient flow, particle tracking, and nitrate transport."

    [[simulation.process]]
    id = "flow_main"
    type = "flow"
    solvers = ["modflownwt"]

    [[simulation.process]]
    id = "transport_no3"
    type = "transport"
    solvers = ["mt3dms"]

The launcher itself does not hard-code "run flow then transport". It only:

- prepares the shared state,
- builds a plan from the TOML,
- runs optional launcher-managed postprocess actions after process families,
- executes the resolved plan.
"""

from __future__ import annotations

import os
import tomllib
import warnings
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import hydromodpy as hmp
import pandas as pd
from hydromodpy.config.hydromodpy_config import HydroModPyConfig
from hydromodpy.data_managers import (
    DataLoadPlan,
    DataManagersPlanner,
    DataManagersRuntimeLoader,
)
from hydromodpy.domain import Domain
from hydromodpy.domain.structure_binders import (
    apply_catchment_zones_to_domain,
    apply_geology_to_domain,
)
from hydromodpy.postprocess.runner import PostprocessRunner
from hydromodpy.process.flow.structure_binders import (
    apply_climatic_to_flow_recharge,
    apply_oceanic_to_flow,
)
from hydromodpy.simulation import ProcessContextFactory, SimulationPlanner
from hydromodpy.simulation.runtime.runner import ProcessCallbacks, SimulationRunner
from hydromodpy.simulation.state.run_state import LauncherRunState
from hydromodpy.simulation.settings import Settings


def _as_mapping(value: object, *, name: str) -> dict[str, Any]:
    """Return a shallow dict copy from a mapping-like payload."""
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    raise ValueError(f"{name} must be a mapping")


def _resolve_config_path(
    config_path: Path,
    path_value: object,
    *,
    name: str,
) -> Path:
    """Resolve a path relative to the launcher TOML location."""
    if not isinstance(path_value, str) or not path_value.strip():
        raise ValueError(f"{name} must be a non-empty string path")
    path = Path(path_value).expanduser()
    if not path.is_absolute():
        path = (config_path.parent / path).resolve()
    return path


def _to_m_per_day(series: pd.Series, *, units: object, label: str) -> pd.Series:
    """Normalize recharge/runoff units to m/day."""
    unit = str(units).strip().lower()
    if unit in {"m/day", "m/d"}:
        return series.astype(float)
    if unit in {"mm/day", "mm/d"}:
        return series.astype(float) / 1000.0
    raise ValueError(f"{label} units must be 'mm/day' or 'm/day'. Got: {units!r}")


def _normalize_recharge_mode(raw_toml: Mapping[str, Any]) -> str | None:
    """Return recharge chronicle mode, or None when section is absent."""
    cfg = _as_mapping(raw_toml.get("recharge_chronicle"), name="recharge_chronicle")
    if not cfg:
        return None
    mode = str(cfg.get("mode", "synthetic_generated")).strip().lower()
    allowed = {"observed_csv", "synthetic_generated", "synthetic_csv"}
    if mode not in allowed:
        raise ValueError(
            "recharge_chronicle.mode must be one of "
            "'observed_csv', 'synthetic_generated', 'synthetic_csv'."
        )
    return mode


def _build_synthetic_generated_series(
    raw_toml: Mapping[str, Any],
    *,
    default_values: object | None = None,
) -> tuple[pd.Series, pd.Series]:
    """Build recharge/runoff series from inline synthetic payload."""
    cfg_root = _as_mapping(raw_toml.get("recharge_chronicle"), name="recharge_chronicle")
    cfg = _as_mapping(
        cfg_root.get("synthetic_generated"),
        name="recharge_chronicle.synthetic_generated",
    )

    raw_values = cfg.get("values_mm_day", default_values)
    if isinstance(raw_values, (list, tuple)):
        values = [float(v) for v in raw_values]
        periods = int(cfg.get("periods", len(values)))
        if len(values) != periods:
            raise ValueError(
                "recharge_chronicle.synthetic_generated.values_mm_day length must match periods."
            )
    elif isinstance(raw_values, (int, float)) and not isinstance(raw_values, bool):
        periods = int(cfg.get("periods", 12))
        values = [float(raw_values)] * periods
    else:
        raise ValueError(
            "recharge_chronicle.synthetic_generated.values_mm_day must be "
            "a scalar or a list of numeric values."
        )

    start_date = str(cfg.get("start_date", "2003-01-01"))
    freq = str(cfg.get("freq", "ME"))
    index = pd.date_range(start=start_date, periods=periods, freq=freq)
    recharge_raw = pd.Series(values, index=index, dtype=float)
    recharge = _to_m_per_day(
        recharge_raw,
        units=cfg.get("units", "mm/day"),
        label="synthetic_generated recharge",
    )
    runoff_ratio = float(cfg.get("runoff_ratio", 0.1))
    runoff = recharge * runoff_ratio
    return recharge, runoff


def _build_synthetic_csv_series(
    raw_toml: Mapping[str, Any],
    *,
    config_path: Path,
) -> tuple[pd.Series, pd.Series]:
    """Build recharge/runoff series from a CSV payload."""
    cfg_root = _as_mapping(raw_toml.get("recharge_chronicle"), name="recharge_chronicle")
    cfg = _as_mapping(
        cfg_root.get("synthetic_csv"),
        name="recharge_chronicle.synthetic_csv",
    )

    path_file = _resolve_config_path(
        config_path,
        cfg.get("path_file", ""),
        name="recharge_chronicle.synthetic_csv.path_file",
    )
    sep = str(cfg.get("sep", ","))
    date_column = str(cfg.get("date_column", "date"))
    recharge_column = str(cfg.get("recharge_column", "recharge_mm_day"))
    date_format = cfg.get("date_format")
    runoff_column = cfg.get("runoff_column")

    df = pd.read_csv(path_file, sep=sep)
    if date_column not in df.columns:
        raise ValueError(f"Column '{date_column}' not found in synthetic recharge CSV: {path_file}")
    if recharge_column not in df.columns:
        raise ValueError(
            f"Column '{recharge_column}' not found in synthetic recharge CSV: {path_file}"
        )

    if date_format is None:
        dates = pd.to_datetime(df[date_column])
    else:
        dates = pd.to_datetime(df[date_column], format=str(date_format))

    recharge_raw = pd.Series(df[recharge_column].astype(float).values, index=dates).sort_index()
    recharge = _to_m_per_day(
        recharge_raw,
        units=cfg.get("units", "mm/day"),
        label="synthetic_csv recharge",
    )

    if isinstance(runoff_column, str) and runoff_column in df.columns:
        runoff_raw = pd.Series(df[runoff_column].astype(float).values, index=dates).sort_index()
        runoff = _to_m_per_day(
            runoff_raw,
            units=cfg.get("runoff_units", cfg.get("units", "mm/day")),
            label="synthetic_csv runoff",
        )
    else:
        runoff_ratio = float(cfg.get("runoff_ratio", 0.1))
        runoff = recharge * runoff_ratio

    time_step = cfg.get("time_step")
    if isinstance(time_step, str) and time_step.strip():
        recharge = recharge.resample(time_step).mean().ffill()
        runoff = runoff.resample(time_step).mean().ffill()

    return recharge, runoff


def _as_timestamp(value: object, *, name: str) -> pd.Timestamp:
    """Parse one timestamp-like value and validate it."""
    try:
        ts = pd.Timestamp(value)
    except Exception as exc:
        raise ValueError(f"{name} must be a valid datetime value.") from exc
    if pd.isna(ts):
        raise ValueError(f"{name} must be a valid datetime value.")
    return ts


class HydroModPyLauncher:
    """High-level orchestration layer between configuration and execution.

    This class is intentionally small. It does not implement solver-specific
    logic itself; instead, it prepares a ``LauncherRunState`` object and then
    hands a resolved ``SimulationPlan`` to ``SimulationRunner``.

    Example
    -------
    The typical usage is:

    >>> from pathlib import Path
    >>> launcher = HydroModPyLauncher(Path("examples/launcher_simulation/config_standard.toml"))
    >>> run_state = launcher.run()

    After ``run()``, ``run_state`` contains both the shared objects created during
    bootstrap (workspace, domain, flow config, transport config) and the models
    produced by executed runs.
    """

    def __init__(self, config_path: str | Path) -> None:
        """Load configuration and raw TOML for one launcher run.

        Parameters
        ----------
        config_path:
            Path to the TOML file that declares both the shared HydroModPy
            sections (workspace, flow, transport, etc.) and the
            ``[simulation]`` block.

        Notes
        -----
        Two views of the same configuration are kept on purpose:

        - ``self.cfg`` is the validated Pydantic representation used by the core
          code,
        - ``raw_toml`` is the untyped dictionary kept for optional
          launcher-managed custom sections (currently ``[recharge_chronicle]``).
        """
        self.config_path = Path(config_path).resolve()
        self.cfg = HydroModPyConfig.from_toml(self.config_path)

        # HYDROMODPY_OUT_PATH allows redirecting outputs without editing the launcher TOML.
        if out_path_env := os.environ.get("HYDROMODPY_OUT_PATH"):
            self.cfg.workspace.out_dir_path = Path(out_path_env)

        self._apply_simulation_time_window_to_tgrids()

        with self.config_path.open("rb") as fh:
            raw_toml = tomllib.load(fh)

        # Resolve the effective data-manager activation set from:
        # - explicit [data].types declarations,
        # - high-level domain/process/context hints.
        data_plan = DataManagersPlanner().build(
            self.cfg.data,
            domain_zone_ids=self.cfg.domain.zone_ids,
            raw_toml=raw_toml,
            flow_active_bc=self.cfg.flow.active_bc,
        )
        self._log_data_plan(data_plan)
        # Apply resolved types back to cfg so downstream code can keep reading
        # one canonical config tree (`self.cfg.data`).
        self.cfg.data = self.cfg.data.with_resolved_types(data_plan.types)
        self.data_plan = data_plan

        self.run_state = LauncherRunState(
            cfg=self.cfg,
            config_path=self.config_path,
            raw_toml=raw_toml,
        )
        self.run_state.data_plan = data_plan
        self.process_context_factory = ProcessContextFactory()
        self.postprocess_runner = PostprocessRunner(self.cfg.postprocess)

    def _get_simulation_time_window(self) -> tuple[pd.Timestamp, pd.Timestamp, str] | None:
        """Return canonical (start, end, policy) from `[simulation.time]` when configured."""
        simulation_cfg = getattr(self.cfg, "simulation", None)
        time_cfg = getattr(simulation_cfg, "time", None) if simulation_cfg is not None else None
        if time_cfg is None:
            return None
        start = _as_timestamp(time_cfg.start_datetime, name="simulation.time.start_datetime")
        end = _as_timestamp(time_cfg.end_datetime, name="simulation.time.end_datetime")
        if end <= start:
            raise ValueError("simulation.time.end_datetime must be greater than start_datetime.")
        policy = str(getattr(time_cfg, "coverage_policy", "error")).strip().lower()
        if policy not in {"error", "warn", "ignore"}:
            raise ValueError("simulation.time.coverage_policy must be one of: error, warn, ignore.")
        return start, end, policy

    def _apply_simulation_time_window_to_tgrids(self) -> None:
        """Propagate canonical simulation window to solver tgrid sections."""
        window = self._get_simulation_time_window()
        if window is None:
            return
        start, end, _ = window
        for solver_section_name in ("modflownwt", "modflow6"):
            solver_cfg = getattr(self.cfg, solver_section_name, None)
            tgrid_cfg = getattr(solver_cfg, "tgrid", None) if solver_cfg is not None else None
            if tgrid_cfg is None:
                continue
            tgrid_cfg.start_datetime = start.to_pydatetime()
            tgrid_cfg.end_datetime = end.to_pydatetime()

    @staticmethod
    def _handle_recharge_coverage_violation(policy: str, message: str) -> None:
        if policy == "ignore":
            return
        if policy == "warn":
            warnings.warn(message, stacklevel=2)
            return
        raise ValueError(message)

    def _validate_recharge_coverage(self, recharge: object) -> None:
        """Check that recharge covers the configured simulation window."""
        window = self._get_simulation_time_window()
        if window is None:
            return
        start, end, policy = window
        if policy == "ignore":
            return

        if recharge is None:
            self._handle_recharge_coverage_violation(
                policy,
                "Recharge coverage check failed: recharge data is missing.",
            )
            return

        if isinstance(recharge, pd.Series):
            series = recharge.copy()
        elif isinstance(recharge, pd.DataFrame):
            if recharge.empty:
                self._handle_recharge_coverage_violation(
                    policy,
                    "Recharge coverage check failed: recharge DataFrame is empty.",
                )
                return
            series = recharge.iloc[:, 0].copy()
        else:
            # Scalar/mapping recharge cannot be validated against a datetime window.
            self._handle_recharge_coverage_violation(
                policy,
                "Recharge coverage check requires a datetime-indexed Series/DataFrame "
                f"for window [{start}, {end}], got {type(recharge).__name__}.",
            )
            return

        if not isinstance(series.index, pd.DatetimeIndex):
            try:
                series.index = pd.to_datetime(series.index)
            except Exception:
                self._handle_recharge_coverage_violation(
                    policy,
                    "Recharge coverage check failed: recharge index is not datetime-like.",
                )
                return

        series = series.sort_index()
        if series.empty:
            self._handle_recharge_coverage_violation(
                policy,
                "Recharge coverage check failed: recharge series is empty.",
            )
            return

        series_start = pd.Timestamp(series.index.min())
        series_end = pd.Timestamp(series.index.max())
        if series_start > start or series_end < end:
            self._handle_recharge_coverage_violation(
                policy,
                "Recharge coverage check failed: recharge range "
                f"[{series_start}, {series_end}] does not fully cover "
                f"simulation window [{start}, {end}].",
            )
            return

        window_values = series.loc[(series.index >= start) & (series.index <= end)]
        if window_values.empty:
            self._handle_recharge_coverage_violation(
                policy,
                "Recharge coverage check failed: no recharge values inside simulation window "
                f"[{start}, {end}].",
            )
            return

        if window_values.isna().any():
            self._handle_recharge_coverage_violation(
                policy,
                "Recharge coverage check failed: recharge contains NaN values within "
                f"simulation window [{start}, {end}].",
            )

    @staticmethod
    def _log_data_plan(data_plan: DataLoadPlan) -> None:
        """Print concise planner diagnostics when inferred types are present."""
        if not data_plan.inferred_types:
            return
        print(
            "[DataManagersPlanner] inferred data types: "
            + ", ".join(data_plan.inferred_types)
        )
        for type_name in data_plan.inferred_types:
            reasons = data_plan.reasons_for(type_name)
            if reasons:
                print(
                    f"[DataManagersPlanner] {type_name}: "
                    + "; ".join(reasons)
                )

    def run(self) -> LauncherRunState:
        """Execute one full launcher session and return the populated runtime state.

        The execution order is:

        1. validate that the TOML declares at least one simulation process,
        2. build the resolved execution plan,
        3. create the shared structural objects (setup),
        4. load shared forcings (data),
        5. execute planned process runs through ``SimulationRunner``.

        A useful mental model is:

        - ``setup`` and ``loaded_data`` run once per launcher session,
        - planned process runs (flow, transport, etc.) run once per declared
          process/solver pair.

        For example, if the TOML declares:

        - one ``flow`` process with ``["modflownwt", "modflow6"]``
        - one ``transport`` process with ``["mt3dms", "modflow6gwt"]``

        then ``run()`` will still perform setup/loaded_data only once, but it will
        later execute four concrete solver runs in the resolved order.
        """
        if not self.cfg.simulation.has_processes():
            raise ValueError(
                "Launchers require an explicit [simulation] block with at least "
                "one [[simulation.process]] entry."
            )

        run_state = self.run_state
        execution_state = run_state.execution
        plan = self._create_simulation_plan()
        execution_state.simulation_plan = plan
        # Keep a direct lookup table by run id because downstream code often
        # needs concrete run-level lookup, not just the flat list.
        execution_state.process_runs_by_id = {run.id: run for run in plan.runs}

        self._run_setup()
        self._run_data()
        # The runner owns the fine-grained solver dispatch. The launcher
        # only provides process-family callbacks for managed postprocess.
        SimulationRunner(
            callbacks=ProcessCallbacks(
                after_process=self._on_after_process,
            ),
            process_context_factory=self.process_context_factory,
        ).execute(plan, run_state)

        return run_state

    def _run_setup(self) -> None:
        """Initialise the structural objects shared by all later process runs.

        This method builds the stable "session context" of the simulation:

        - workspace and folders,
        - geographic context and topographic support,
        - domain geometry,
        - process-level context objects (``flow``, ``transport``),
        - generic launcher settings.

        It runs once, even when the simulation plan later contains several
        solver runs. For example, two flow solvers still reuse the same domain
        geometry and the same declared flow configuration.
        """
        run_state = self.run_state
        setup_state = run_state.setup
        cfg = self.cfg

        setup_state.workspace = hmp.Workspace(config=cfg.workspace)
        setup_state.geographic = hmp.Geographic(cfg.geographic, setup_state.workspace)
        setup_state.domain_geographic = setup_state.geographic.get_domain_geographic_context()
        surface_topo = setup_state.domain_geographic.surface_topo

        domain_cfg = cfg.domain
        zone_ids = getattr(domain_cfg, "zone_ids", None)
        if isinstance(zone_ids, list):
            normalized_zone_ids = {str(item).strip().lower() for item in zone_ids}
            if "catchment" not in normalized_zone_ids:
                if hasattr(domain_cfg, "model_copy"):
                    domain_cfg = domain_cfg.model_copy(deep=True)
                    domain_cfg.zone_ids.append("catchment")
                else:
                    zone_ids.append("catchment")

        setup_state.domain = Domain(config=domain_cfg, surface_topo=surface_topo)
        apply_catchment_zones_to_domain(
            domain=setup_state.domain,
            geographic=setup_state.domain_geographic,
        )

        setup_state.settings = Settings()
        # Use [simulation].name as the default model/folder base name.
        # Canonical runtime location is setup.model_name.
        simulation_name = "_".join(str(cfg.simulation.name).strip().split())
        if simulation_name:
            setup_state.model_name = simulation_name
            # Keep mirroring for compatibility with code paths still reading
            # settings.model_name directly.
            if hasattr(setup_state.settings, "model_name"):
                setup_state.settings.model_name = simulation_name
        # Keep eager context creation in setup for compatibility with data
        # binders.
        self.process_context_factory.ensure_flow(run_state)
        self.process_context_factory.ensure_transport(run_state)

    def _run_data(self) -> None:
        """Load the external forcings shared by all process runs.

        Runtime loading is delegated to ``DataManagersRuntimeLoader`` in the
        data_managers package. Structural bindings are then applied explicitly
        through domain/process binder modules.
        """
        run_state = self.run_state
        loader = DataManagersRuntimeLoader(
            config_path=self.config_path,
            data_plan=self.data_plan,
        )
        loader.load_all(run_state)
        self._apply_recharge_chronicle_from_toml()
        self._apply_structural_updates_from_data()

    def _apply_recharge_chronicle_from_toml(self) -> None:
        """Optionally materialize climatic recharge from [recharge_chronicle]."""
        run_state = self.run_state
        mode = _normalize_recharge_mode(run_state.raw_toml)
        if mode is None:
            return

        climatic = run_state.loaded_data.climatic
        if climatic is None:
            raise RuntimeError(
                "Launcher internal error: loaded_data.climatic is not initialized."
            )

        sinks_sources = getattr(run_state.setup.flow, "sinks_sources", {})
        recharge_cfg = (
            sinks_sources.get("recharge")
            if isinstance(sinks_sources, dict)
            else None
        )
        default_values = getattr(recharge_cfg, "values", None) if recharge_cfg is not None else None

        if mode == "observed_csv":
            cfg_root = _as_mapping(
                run_state.raw_toml.get("recharge_chronicle"),
                name="recharge_chronicle",
            )
            cfg = _as_mapping(
                cfg_root.get("observed_csv"),
                name="recharge_chronicle.observed_csv",
            )
            default_path = run_state.cfg.workspace.data_path / "_climate_REANALYSIS.csv"
            path_file = _resolve_config_path(
                self.config_path,
                cfg.get("path_file", str(default_path)),
                name="recharge_chronicle.observed_csv.path_file",
            )
            clim_mod = str(cfg.get("clim_mod", "REA"))
            clim_sce = str(cfg.get("clim_sce", "historic"))
            first_year = int(cfg.get("first_year", 2003))
            last_year = int(cfg.get("last_year", first_year))
            time_step = str(cfg.get("time_step", "ME"))
            sim_state = str(cfg.get("sim_state", run_state.setup.flow.flow_regime))

            climatic.update_recharge_reanalysis(
                path_file=path_file,
                clim_mod=clim_mod,
                clim_sce=clim_sce,
                first_year=first_year,
                last_year=last_year,
                time_step=time_step,
                sim_state=sim_state,
            )
            climatic.update_runoff_reanalysis(
                path_file=path_file,
                clim_mod=clim_mod,
                clim_sce=clim_sce,
                first_year=first_year,
                last_year=last_year,
                time_step=time_step,
                sim_state=sim_state,
            )
            self._validate_recharge_coverage(climatic.recharge)
            return

        if mode == "synthetic_generated":
            recharge, runoff = _build_synthetic_generated_series(
                run_state.raw_toml,
                default_values=default_values,
            )
        else:
            recharge, runoff = _build_synthetic_csv_series(
                run_state.raw_toml,
                config_path=self.config_path,
            )

        sim_state = run_state.setup.flow.flow_regime
        self._validate_recharge_coverage(recharge)
        climatic.update_recharge(recharge, sim_state=sim_state)
        climatic.update_runoff(runoff, sim_state=sim_state)

    def _apply_structural_updates_from_data(self) -> None:
        """Bind loaded data objects to runtime structures using explicit updaters."""
        run_state = self.run_state
        setup_state = run_state.setup
        data_state = run_state.loaded_data
        apply_geology_to_domain(domain=setup_state.domain, geology=data_state.geology)
        self.process_context_factory.ensure_flow(run_state)
        apply_oceanic_to_flow(flow=setup_state.flow, oceanic=data_state.oceanic)
        apply_climatic_to_flow_recharge(flow=setup_state.flow, climatic=data_state.climatic)

    def _create_simulation_plan(self):
        """Resolve the declarative ``[simulation]`` block into concrete runs.

        ``SimulationPlanner`` converts a compact declaration into explicit
        executable units. For example, this input:

        - ``type="flow", solvers=["modflownwt"]``
        - ``type="transport", solvers=["mt3dms"]``

        becomes two concrete runs where the second one explicitly depends on
        the first. That explicit plan is what makes execution deterministic and
        reusable outside the launcher as well.
        """
        planner = SimulationPlanner()
        return planner.build(self.cfg.simulation)

    def _on_after_process(self, process_type: str) -> None:
        """Run launcher-level actions after one process-family block."""
        self.postprocess_runner.after_process(process_type, self.run_state)
