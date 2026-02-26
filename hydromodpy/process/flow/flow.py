
# -*- coding: utf-8 -*-

from collections.abc import Mapping

from hydromodpy.field.core.field_param import FieldParam
from hydromodpy.field.core.field_param_config import (
    resolve_field_param_config_payload,
    validate_resolved_field_param_data,
)
from hydromodpy.process.flow.flow_config import FlowConfig
from hydromodpy.process.process import Process, Parameter, Variable, InitialCondition, BoundaryCondition, SinkSource

class Flow(Process):
	def __init__(self, config: FlowConfig | Mapping[str, object] | None = None):
		super().__init__()
		self.config: FlowConfig | None = None
		if config is not None:
			self.set_config(config)

	def set_config(self, config: FlowConfig | Mapping[str, object]) -> None:
		if isinstance(config, FlowConfig):
			flow_cfg = config
		elif isinstance(config, Mapping):
			if "param" in config:
				flow_cfg = FlowConfig.model_validate(dict(config))
			else:
				flow_cfg = FlowConfig(param=dict(config))
		else:
			raise TypeError("Flow config must be a FlowConfig instance or a mapping")

		self.config = flow_cfg
		self.set_parameters(cfg_flowparam=flow_cfg.param)

	def _build_field_param(self, *, param_id: str, raw_cfg: object) -> FieldParam:
		if isinstance(raw_cfg, Mapping):
			payload = dict(raw_cfg)
		else:
			raise TypeError(
				f"cfg_flowparam['{param_id}'] must be a mapping, "
				f"got {type(raw_cfg).__name__}"
			)

		# Support field_param TOML-style payloads by delegating mode resolution
		# to field_param_config internals.
		if any(
			key in payload
			for key in ("field", "field_homogeneous", "field_heterogeneous", "field_vertical_profile")
		):
			resolved = resolve_field_param_config_payload(
				payload,
				param_id=param_id,
				section_label=f"cfg_flowparam['{param_id}']",
			)
			return FieldParam.from_dict(resolved)

		# Supports already-resolved payload:
		# {id, kind, value|values, field_spatial_id, vertical_profile}
		payload.setdefault("id", param_id)
		resolved = validate_resolved_field_param_data(payload)
		return FieldParam.from_dict(resolved)

	def set_parameters(
		self,
		cfg_flowparam: Mapping[str, object] | None = None,
	):
		if cfg_flowparam is None:
			return
		if not isinstance(cfg_flowparam, Mapping):
			raise TypeError("cfg_flowparam must be a mapping of parameter id to config")

		parsed_parameters: dict[str, FieldParam] = {}
		for raw_id, raw_cfg in cfg_flowparam.items():
			param_id = str(raw_id).strip()
			if param_id == "":
				raise ValueError("cfg_flowparam cannot contain empty parameter ids")
			parsed_parameters[param_id] = self._build_field_param(
				param_id=param_id,
				raw_cfg=raw_cfg,
			)
		self.parameters = parsed_parameters

	def set_variables(self, variables: dict):
		self.variables.update(variables)

	def set_initial_conditions(self, initial_conditions: dict):
		self.initial_conditions.update(initial_conditions)

	def set_boundary_conditions(self, boundary_conditions: dict):
		self.boundary_conditions.update(boundary_conditions)

	def set_sinks_sources(self, wells_sources: dict):
		self.sinks_sources.update(wells_sources)
  
if __name__ == "__main__":
    test = Flow()
    Sy = Parameter(id='Sy', value=0.1, description='Specific yield', units='-', field_type='homogeneous')
    h = Variable(id='h', value=0, description='Hydraulic head', units='m')
    q = Variable(id='q', value=0, description='Flow rate', units='m3/s')
    h0 = InitialCondition(id='h0', value=10, description='Initial hydraulic head', units='m')
    h_ocean = BoundaryCondition(id='h_ocean', value=0, description='Ocean boundary condition', units='m', type='Dirichlet')
    drain = BoundaryCondition(id='drain', value=0, description='Drain boundary condition', units='m', type='Cauchy')
    recharge = SinkSource(id='R', value=1e-8, description='Recharge rate', units='m/s')
    well1 = SinkSource(id='W1', value=-1e-4, description='Pumping well', units='m3/s')
    test.set_parameters(
        cfg_flowparam={
            "K": {
                "field": {"id": "K", "kind": "homogeneous"},
                "field_homogeneous": {"value": 1e-5},
            }
        }
    )
    test.add_parameter(Sy)
    test.set_variables({h.id: h, q.id: q})
    test.set_initial_conditions({h0.id: h0})
    test.set_boundary_conditions({h_ocean.id: h_ocean, drain.id: drain})
    test.set_sinks_sources({well1.id: well1})
    
