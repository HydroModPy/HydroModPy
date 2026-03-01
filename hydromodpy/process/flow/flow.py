# -*- coding: utf-8 -*-
"""
Flow Runtime Process
====================

Purpose
-------
Provide the runtime representation of the groundwater flow process built from
one validated `FlowConfig`.

Scope
-----
This class is intentionally process-level and solver-agnostic:
- it stores normalized flow parameters,
- it stores one typed initial-conditions structure,
- it stores typed boundary conditions,
- it stores typed sink/source payloads (currently wells).

Runtime lifecycle
-----------------
1. `FlowConfig` is validated by Pydantic.
2. `Flow.set_config(...)` copies and normalizes config sections into runtime
   containers (`parameters`, `initial_conditions`, `boundary_conditions`,
   `sinks_sources`).
3. Solver adapters (outside this module) transform this runtime state into
   solver-ready arrays and stress-period payloads.

Data path (high-level)
----------------------
`[flow] TOML` -> `FlowConfig` -> `Flow` runtime -> `Solver adapter` -> `Solver`

Design rule
-----------
Any transformation to solver-specific formats (for example MODFLOW stress
period dictionaries) is performed outside this class, in solver adapter layers.

Non-goals
---------
- no direct FLOPY/MODFLOW package creation in this module,
- no spatial discretization logic in this module,
- no temporal stress-period formatting in this module.
"""

from hydromodpy.process.flow.flow_config import FlowConfig
from hydromodpy.process.flow.initial_conditions import (
    FlowInitialCondition,
    FlowInitialConditions,
)
from hydromodpy.process.flow.initial_conditions_config import (
    normalize_flow_initial_conditions,
)
from hydromodpy.process.flow.sinks_sources import FlowSinksSourcesConfig
from hydromodpy.process.prototype import BoundaryCondition, ProcessSpatial, SinkSource


class Flow(ProcessSpatial):
    """
    Runtime flow-process object built from a validated `FlowConfig`.

    Notes
    -----
    `Flow` is the canonical runtime container for:
    - `parameters`
    - `initial_conditions`
    - `boundary_conditions`
    - `sinks_sources`
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
        self.initial_conditions: FlowInitialConditions | None
        self.boundary_condition_application_domains: dict[str, str] = {}
        self.initial_condition_types: dict[str, str] = {}
        self.set_config(config)

    def set_config(self, config: FlowConfig) -> None:
        """
        Apply one validated `FlowConfig` payload to runtime state.

        This is the main synchronization point between config and runtime
        containers. Existing runtime members are replaced by values resolved
        from `config`.
        """
        if not isinstance(config, FlowConfig):
            raise TypeError("config must be a FlowConfig instance")

        self.config = config
        self.flow_regime = config.flow_regime
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
    ) -> tuple[dict[str, BoundaryCondition], dict[str, str]]:
        """
        Convert raw boundary-condition payloads into typed runtime structures.

        Returns
        -------
        tuple[dict[str, BoundaryCondition], dict[str, str]]
            - typed BC objects keyed by BC id,
            - optional application-domain mapping keyed by BC id.
        """
        parsed: dict[str, BoundaryCondition] = {}
        application_domains: dict[str, str] = {}

        for bc_id, raw_payload in boundary_conditions_cfg.items():
            # Allow already-instantiated typed payloads.
            if isinstance(raw_payload, BoundaryCondition):
                parsed[bc_id] = raw_payload
                continue
            # For mapping payloads, enforce `id` from section key to keep
            # one stable identifier path.
            payload = dict(raw_payload)
            raw_application_domain = payload.pop("application_domain", None)
            payload["id"] = bc_id
            parsed[bc_id] = BoundaryCondition.model_validate(payload)

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
        Store normalized flow initial conditions.

        Also stores a compact `initial_condition_types` cache used to quickly
        inspect active IC kinds.
        """
        parsed = self.build_initial_conditions(initial_conditions)
        self.initial_conditions = parsed
        if parsed is None:
            self.initial_condition_types = {}
            return
        self.initial_condition_types = {"h": parsed.h.type}

    def set_boundary_conditions(
        self,
        boundary_conditions: dict[str, BoundaryCondition] | None = None,
        *,
        application_domains: dict[str, str] | None = None,
    ) -> None:
        """
        Replace boundary-condition runtime containers.

        Parameters
        ----------
        boundary_conditions : dict[str, BoundaryCondition] | None
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

        Current convention is to store wells under `self.sinks_sources["wells"]`.
        """
        if sinks_sources is None:
            self.sinks_sources["wells"] = {}
            return

        self.sinks_sources["wells"] = dict(sinks_sources.wells)


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
