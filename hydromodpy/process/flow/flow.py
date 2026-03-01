# -*- coding: utf-8 -*-

from hydromodpy.process.flow.flow_config import FlowConfig
from hydromodpy.process.flow.initial_conditions import (
    FlowInitialCondition,
    FlowInitialConditions,
)
from hydromodpy.process.flow.initial_conditions_config import (
    normalize_flow_initial_conditions,
)
from hydromodpy.process.flow.sink_sources import FlowSinksSourcesConfig
from hydromodpy.process.prototype import BoundaryCondition, ProcessSpatial, SinkSource


class Flow(ProcessSpatial):
    """Runtime flow-process object built from a validated ``FlowConfig``."""

    def __init__(self, config: FlowConfig):
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
        """Apply one validated ``FlowConfig`` payload to runtime state."""
        if not isinstance(config, FlowConfig):
            raise TypeError("config must be a FlowConfig instance")

        self.config = config
        self.flow_regime = config.flow_regime
        self.set_parameters_from_config(
            config.param,
            parameter_ids=config.param_list,
            context_label="flow.param",
        )
        self.set_initial_conditions(config.ic)
        bc, application_domains = self._build_boundary_conditions(config.bc)
        self.set_boundary_conditions(
            boundary_conditions=bc,
            application_domains=application_domains,
        )
        self.set_sinks_sources(config.sinks_sources)

    def build_initial_conditions(
        self,
        initial_conditions: object | None,
    ) -> FlowInitialConditions | None:
        return normalize_flow_initial_conditions(initial_conditions, location_prefix="flow.ic")

    def _build_boundary_conditions(
        self,
        boundary_conditions_cfg: dict[str, object],
    ) -> tuple[dict[str, BoundaryCondition], dict[str, str]]:
        parsed: dict[str, BoundaryCondition] = {}
        application_domains: dict[str, str] = {}

        for bc_id, raw_payload in boundary_conditions_cfg.items():
            if isinstance(raw_payload, BoundaryCondition):
                parsed[bc_id] = raw_payload
                continue
            payload = dict(raw_payload)
            raw_application_domain = payload.pop("application_domain", None)
            payload["id"] = bc_id
            parsed[bc_id] = BoundaryCondition.model_validate(payload)

            if isinstance(raw_application_domain, str):
                application_domain = raw_application_domain.strip()
                if application_domain:
                    application_domains[bc_id] = application_domain

        return parsed, application_domains

    def set_initial_conditions(
        self,
        initial_conditions: object | None,
    ) -> None:
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
