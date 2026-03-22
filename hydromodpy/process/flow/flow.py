# -*- coding: utf-8 -*-
"""
Flow Runtime Process
====================

Purpose
-------
Provide the runtime representation of the groundwater flow process, built from
one validated ``FlowConfig`` and consumed by solver adapter layers.

Scope
-----
``Flow`` is process-level and solver-agnostic. It exposes the following
runtime attributes after ``set_config(...)`` is called:

- ``flow_regime`` : ``'steady'`` or ``'transient'``, forwarded from config.
- ``runtime_backend`` : optional nonlinear runtime backend hint used by the
  Boussinesq solver implementation (for example ``local``, ``scipy``,
  ``scipy_sparse``).
- ``parameters`` : normalized hydraulic property dict (K, Sy, Ss, …),
  keyed by parameter id and containing ``FieldParam`` objects.
- ``initial_conditions`` : one ``FlowInitialConditions`` instance grouping
  the head IC policy (type + optional scalar value).
- ``initial_condition_types`` : compact cache ``{"h": type_str}`` for fast
  IC-type inspection downstream.
- ``boundary_conditions`` : typed ``BoundaryCondition`` objects keyed by
  BC id (``"ocean"``, ``"drainage"``, ``"west_side"``, …).
- ``boundary_condition_application_domains`` : optional per-BC domain strings
  (e.g. ``"top"``, ``"west side"``), used by some spatial adapters.
- ``active_bc`` : list of BC ids explicitly activated in the config;
  only these ids will be processed by the solver adapter.
- ``sinks_sources`` : dict with two keys:
  ``"wells"`` → ``dict[str, FlowWellConfig]``,
  ``"recharge"`` → ``FlowRechargeConfig | None``.
- ``active_sinks_sources`` : list of sink/source categories explicitly
  activated (e.g. ``["wells", "recharge"]``).

Runtime lifecycle
-----------------
1. ``FlowConfig`` is validated by Pydantic from a TOML/dict payload.
2. ``Flow(config)`` calls ``set_config(config)`` which normalizes each
   config section into the typed runtime containers listed above.
3. Solver adapters (outside this module) read those containers and transform
   them into solver-ready arrays and stress-period payloads.

Data path (high-level)
----------------------
.. code-block:: text

    TOML
     └─> FlowConfig (Pydantic)
          └─> Flow.set_config()
               ├─ [flow]               -> flow_regime
               ├─ [flow.param]         -> parameters
               ├─ [flow.ic]            -> initial_conditions
               ├─ [flow.bc]            -> boundary_conditions, active_bc
               └─ [flow.sinks_sources] -> sinks_sources, active_sinks_sources
                                               └─> FlowToModflowAdapter -> MODFLOW

Design rule
-----------
Any transformation to solver-specific formats (for example MODFLOW stress-period
dictionaries) is performed outside this class, in solver adapter layers.
``Flow`` itself never references FLOPY or any solver convention.

Non-goals
---------
- no direct FLOPY/MODFLOW package creation in this module,
- no spatial discretization or gridding logic in this module,
- no temporal stress-period formatting in this module.
"""

from hydromodpy.process.flow.flow_config import FlowConfig
from hydromodpy.process.flow.boundary_conditions import FlowBoundaryConditionConfig
from hydromodpy.process.flow.initial_conditions import (
    FlowInitialCondition,
    FlowInitialConditions,
)
from hydromodpy.process.flow.initial_conditions_config import (
    normalize_flow_initial_conditions,
)
from hydromodpy.process.flow.sinks_sources import FlowRechargeConfig, FlowSinksSourcesConfig
from hydromodpy.process.prototype import BoundaryCondition, ProcessSpatial, SinkSource
from hydromodpy.support.units import convert_payload_to_m_per_s, normalize_m_per_s_unit
from hydromodpy.support.units.volumetric_flow import (
    convert_to_m3_per_s,
    normalize_m3_per_s_unit,
)


class Flow(ProcessSpatial):
    """
    Runtime flow-process object built from a validated ``FlowConfig``.

    Quick reading guide
    -------------------
    For a first pass, focus on these three methods:
    - ``set_config``: one-shot synchronization from ``FlowConfig`` to runtime.
    - ``_build_boundary_conditions``: validation and normalization of BC payloads.
    - ``set_sinks_sources``: runtime storage of wells and recharge payloads.

    Inherits from ``ProcessSpatial``, which initializes the base containers
    (``parameters``, ``initial_conditions``, ``boundary_conditions``,
    ``sinks_sources``, ``active_bc``, ``active_sinks_sources``) and provides
    the parameter-ingestion helpers.

    ``Flow`` specializes those containers with:

    - ``FlowInitialConditions`` as the typed IC structure (head policy),
    - ``BoundaryCondition`` Pydantic objects for each configured BC,
    - a ``{"wells": ..., "recharge": ...}`` namespace for sinks/sources.

    Runtime attributes (populated by ``set_config``)
    -------------------------------------------------
    flow_regime : str
        ``'steady'`` or ``'transient'``, forwarded from ``FlowConfig``.
    runtime_backend : str
        Optional nonlinear runtime backend hint, currently consumed by the
        Boussinesq solver implementation.
    config : FlowConfig
        Reference to the last validated config applied via ``set_config``.
    parameters : dict[str, FieldParam | object]
        Hydraulic property parameters (K, Sy, Ss, …) keyed by id.
    initial_conditions : FlowInitialConditions | None
        Typed IC container; exposes ``h`` (head IC: type + optional value).
    initial_condition_types : dict[str, str]
        Compact cache ``{"h": type_str}``; allows fast IC-type inspection
        without traversing the full ``FlowInitialConditions`` object.
    boundary_conditions : dict[str, FlowBoundaryConditionConfig]
        Typed BC objects keyed by BC id.
    boundary_condition_application_domains : dict[str, str]
        Optional per-BC spatial domain strings (e.g. ``"top"``,
        ``"west side"``); used by spatial adapters that need to know where
        a BC is applied.
    active_bc : list[str]
        BC ids declared as active in config; only these are processed by
        the solver adapter.
    sinks_sources : dict[str, object]
        Namespace with keys ``"wells"`` (``dict[str, FlowWellConfig]``)
        and ``"recharge"`` (``FlowRechargeConfig | None``).
    active_sinks_sources : list[str]
        Sink/source categories explicitly activated
        (e.g. ``["wells", "recharge"]``).
    """

    def __init__(self, config: FlowConfig):
        """
        Build one `Flow` runtime object from one validated config.

        Parameters
        ----------
        config : FlowConfig
            Typed flow configuration payload.
        """
        super().__init__()
        if not isinstance(config, FlowConfig):
            raise TypeError("config must be a FlowConfig instance")
        self.config: FlowConfig
        self.flow_regime: str
        self.runtime_backend: str
        self.initial_conditions: FlowInitialConditions | None
        self.boundary_condition_application_domains: dict[str, str] = {}
        self.initial_condition_types: dict[str, str] = {}
        self.set_config(config)

    def set_config(self, config: FlowConfig) -> None:
        """
        Apply one validated ``FlowConfig`` payload to runtime state.

        This is the main synchronization point between config and runtime
        containers. All existing runtime attributes are replaced in one
        deterministic pass. Calling this method a second time with a new
        config fully resets the runtime state.

        Steps performed (in order)
        --------------------------
        1. ``flow_regime`` is forwarded directly from the config string.
        2. ``parameters`` are resolved in the order declared by
           ``config.param_list`` (preserves user intent for K/Sy/Ss ordering).
        3. ``initial_conditions`` are built from ``config.ic`` via the
           process-specific normalizer (delegates to
           ``normalize_flow_initial_conditions``).
        4. ``boundary_conditions`` and ``boundary_condition_application_domains``
           are built from ``config.bc`` (typed objects + optional domain map).
        5. ``sinks_sources`` is populated from ``config.sinks_sources``
           (wells dict + recharge config).
        6. ``active_sinks_sources`` and ``active_bc`` are copied from config
           as plain lists; they control which items the solver adapter
           actually processes.
        """
        if not isinstance(config, FlowConfig):
            raise TypeError("config must be a FlowConfig instance")

        self.config = config
        self.flow_regime = config.flow_regime
        self.runtime_backend = config.runtime_backend
        # Parameters are resolved in the declared order from `flow.param_list`.
        self.set_parameters_from_config(
            config.param,
            parameter_ids=config.param_list,
            context_label="flow.param",
        )
        # Flow has one typed IC structure (`FlowInitialConditions`).
        self.set_initial_conditions(config.ic)
        # Boundary conditions are normalized as typed objects + domain hints.
        bc, application_domains = self._build_boundary_conditions(config.bc)
        self.set_boundary_conditions(
            boundary_conditions=bc,
            application_domains=application_domains,
        )
        # Sinks/sources are stored in a process-level dictionary namespace.
        self.set_sinks_sources(config.sinks_sources)
        # active_* lists control which items the solver adapter will process;
        # items absent from these lists are silently ignored downstream.
        self.active_sinks_sources = list(config.active_sinks_sources)
        self.active_bc = list(config.active_bc)

    def build_initial_conditions(
        self,
        initial_conditions: object | None,
    ) -> FlowInitialConditions | None:
        """
        Normalize one raw IC payload into `FlowInitialConditions`.

        Delegates to the dedicated normalizer used by `FlowConfig`, so runtime
        and configuration validation rules stay aligned.
        """
        return normalize_flow_initial_conditions(initial_conditions, location_prefix="flow.ic")

    def _build_boundary_conditions(
        self,
        boundary_conditions_cfg: dict[str, object],
    ) -> tuple[dict[str, FlowBoundaryConditionConfig], dict[str, str]]:
        """
        Convert raw boundary-condition payloads into typed runtime structures.

        Each entry in ``boundary_conditions_cfg`` is either:

        - an already-typed ``BoundaryCondition`` (passed through as-is), or
        - a raw mapping, validated via ``BoundaryCondition.model_validate``.

        For mapping payloads, ``id`` is always forced to the TOML section key
        (e.g. ``"ocean"``, ``"west_side"``). This prevents the ``id`` field
        in the TOML from diverging from the key actually used to look up the
        BC at runtime, which would cause silent mismatches in the adapter.

        The ``application_domain`` key, if present, is extracted from the
        payload before Pydantic validation and stored separately in
        ``boundary_condition_application_domains``. This keeps the domain
        hint available to spatial adapters without polluting the BC model.

        Returns
        -------
        tuple[dict[str, FlowBoundaryConditionConfig], dict[str, str]]
            - typed BC objects keyed by BC id,
            - per-BC application-domain strings keyed by the same BC id.
        """
        parsed: dict[str, FlowBoundaryConditionConfig] = {}
        application_domains: dict[str, str] = {}

        for bc_id, raw_payload in boundary_conditions_cfg.items():
            # Allow already-instantiated typed payloads.
            if isinstance(raw_payload, FlowBoundaryConditionConfig):
                parsed[bc_id] = raw_payload
                continue
            if isinstance(raw_payload, BoundaryCondition):
                parsed[bc_id] = FlowBoundaryConditionConfig.model_validate(
                    raw_payload.model_dump(mode="python")
                )
                continue
            # For mapping payloads, enforce `id` from section key to keep
            # one stable identifier path.
            payload = dict(raw_payload)
            raw_application_domain = payload.pop("application_domain", None)
            payload["id"] = bc_id
            parsed[bc_id] = FlowBoundaryConditionConfig.model_validate(payload)

            # Keep domain information in a dedicated runtime map for explicit
            # downstream usage.
            if isinstance(raw_application_domain, str):
                application_domain = raw_application_domain.strip()
                if application_domain:
                    application_domains[bc_id] = application_domain

        return parsed, application_domains

    def set_initial_conditions(
        self,
        initial_conditions: object | None,
    ) -> None:
        """
        Normalize and store flow initial conditions.

        Delegates normalization to ``build_initial_conditions`` (which calls
        ``normalize_flow_initial_conditions``), then stores the result in
        ``self.initial_conditions``.

        Also maintains ``self.initial_condition_types``, a compact
        ``{"h": type_str}`` dict. This cache lets downstream code (e.g.
        solver adapters) check the IC type in O(1) without traversing the
        full ``FlowInitialConditions`` object.
        """
        parsed = self.build_initial_conditions(initial_conditions)
        self.initial_conditions = parsed
        if parsed is None:
            self.initial_condition_types = {}
            return
        self.initial_condition_types = {"h": parsed.h.type}

    def set_boundary_conditions(
        self,
        boundary_conditions: dict[str, FlowBoundaryConditionConfig] | None = None,
        *,
        application_domains: dict[str, str] | None = None,
    ) -> None:
        """
        Replace boundary-condition runtime containers.

        Parameters
        ----------
        boundary_conditions : dict[str, FlowBoundaryConditionConfig] | None
            Typed BC payloads keyed by BC id.
        application_domains : dict[str, str] | None
            Optional per-BC domain targets (for example `top`, `west side`).
        """
        if boundary_conditions is None:
            self.boundary_conditions = {}
        else:
            self.boundary_conditions = dict(boundary_conditions)
        if application_domains is None:
            self.boundary_condition_application_domains = {}
        else:
            self.boundary_condition_application_domains = dict(application_domains)

    def set_sinks_sources(
        self,
        sinks_sources: FlowSinksSourcesConfig | None = None,
    ) -> None:
        """
        Replace flow sink/source runtime payloads.

        Stores wells under `self.sinks_sources["wells"]` and recharge config
        under `self.sinks_sources["recharge"]`.

        Well fluxes are converted to SI volumetric flow (`m3/s`) at load time
        using each well `units` field.
        """
        if sinks_sources is None:
            self.sinks_sources["wells"] = {}
            self.sinks_sources["recharge"] = None
            return

        normalized_wells = {}
        for well_id, well_cfg in sinks_sources.wells.items():
            raw_units = getattr(well_cfg, "units", "m3/s")
            try:
                canonical_units = normalize_m3_per_s_unit(raw_units)
            except ValueError as exc:
                raise ValueError(
                    f"flow.sinks_sources.wells.{well_id}.units must be compatible with m3/s "
                    f"(for example m3/day, m3/h, m3/s, l/s). Got: {raw_units!r}"
                ) from exc

            flux_payload = well_cfg.flux
            if flux_payload is None:
                normalized_wells[well_id] = well_cfg.model_copy(update={"units": canonical_units})
                continue
            if isinstance(flux_payload, list):
                flux_si = [
                    convert_to_m3_per_s(
                        flux_item,
                        unit=canonical_units,
                        label=f"flow.sinks_sources.wells.{well_id}.flux[{idx}]",
                    )
                    for idx, flux_item in enumerate(flux_payload)
                ]
            else:
                flux_si = convert_to_m3_per_s(
                    flux_payload,
                    unit=canonical_units,
                    label=f"flow.sinks_sources.wells.{well_id}.flux",
                )

            normalized_wells[well_id] = well_cfg.model_copy(
                update={"flux": flux_si, "units": "m3/s"}
            )

        self.sinks_sources["wells"] = normalized_wells
        self.sinks_sources["recharge"] = self._normalize_recharge_config(
            sinks_sources.recharge,
            location_prefix="flow.sinks_sources.recharge",
        )

    @staticmethod
    def _normalize_recharge_config(
        recharge: FlowRechargeConfig | None,
        *,
        location_prefix: str,
    ) -> FlowRechargeConfig | None:
        if recharge is None:
            return None

        raw_units = getattr(recharge, "units", "m/s")
        try:
            canonical_units = normalize_m_per_s_unit(raw_units)
        except ValueError as exc:
            raise ValueError(
                f"{location_prefix}.units must be compatible with m/s "
                f"(for example mm/day, m/day, m/s). Got: {raw_units!r}"
            ) from exc

        values_si = convert_payload_to_m_per_s(
            getattr(recharge, "values", 0.0),
            unit=canonical_units,
            label=f"{location_prefix}.values",
        )
        return recharge.model_copy(update={"values": values_si, "units": "m/s"})

    def set_recharge(self, recharge: FlowRechargeConfig | None) -> None:
        """
        Inject or replace the recharge payload at runtime.

        Useful when recharge is computed dynamically (e.g. from a PyHELP run)
        and must be set after `Flow` is already configured from TOML.

        Parameters
        ----------
        recharge : FlowRechargeConfig | None
            Typed recharge payload, or None to clear.
        """
        self.sinks_sources["recharge"] = self._normalize_recharge_config(
            recharge,
            location_prefix="flow.sinks_sources.recharge",
        )


if __name__ == "__main__":
    test = Flow(FlowConfig())
    h0 = FlowInitialCondition(
        type="custom",
        value=10,
        units="m",
    )
    h_ocean = BoundaryCondition(
        id="h_ocean",
        value=0,
        description="Ocean boundary condition",
        units="m",
        type="Dirichlet",
        data_value=False,
    )
    drain = BoundaryCondition(
        id="drain",
        value=0,
        description="Drain boundary condition",
        units="m",
        type="Cauchy",
        data_value=False,
    )
    well1 = SinkSource(id="W1", value=-1e-4, description="Pumping well", units="m3/s")
    test.set_parameters_from_config(
        {
            "K": {"id": "K", "kind": "homogeneous", "value": 1e-5, "unit": "m/s"},
            "Sy": {"id": "Sy", "kind": "homogeneous", "value": 0.1, "unit": "-"},
        },
        parameter_ids=["K", "Sy"],
        context_label="flow.param",
    )
    test.set_initial_conditions(h0)
    test.set_boundary_conditions({h_ocean.id: h_ocean, drain.id: drain})
    test.set_sinks_sources(
        FlowSinksSourcesConfig(
            wells={well1.id: {"cell": (0, 0, 0), "flux": -1e-4}},
        )
    )
