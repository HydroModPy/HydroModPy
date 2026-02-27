
# -*- coding: utf-8 -*-

from collections.abc import Mapping
from numbers import Real

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
		self.boundary_condition_application_domains: dict[str, str] = {}
		if config is not None:
			self.set_config(config)

	def set_config(self, config: FlowConfig | Mapping[str, object]) -> None:
		if isinstance(config, FlowConfig):
			flow_cfg = config
		elif isinstance(config, Mapping):
			if "param" in config:
				flow_cfg = FlowConfig.model_validate(dict(config))
			else:
				shorthand_param: dict[str, dict[str, object]] = {}
				for raw_key, raw_payload in config.items():
					param_id = str(raw_key).strip()
					if param_id == "":
						raise ValueError("Flow shorthand config cannot contain empty parameter ids")
					if not isinstance(raw_payload, Mapping):
						raise TypeError(
							"Flow shorthand config values must be mapping payloads "
							f"(got {type(raw_payload).__name__} for '{param_id}')"
						)
					shorthand_param[param_id] = dict(raw_payload)
				flow_cfg = FlowConfig(param=shorthand_param)
		else:
			raise TypeError("Flow config must be a FlowConfig instance or a mapping")

		self.config = flow_cfg
		self.set_parameters(cfg_flowparam=flow_cfg.param)
		self.set_boundary_conditions(flow_cfg.bc)

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

	def set_boundary_conditions(self, boundary_conditions: Mapping[str, object] | None = None):
		if boundary_conditions is None:
			return
		if not isinstance(boundary_conditions, Mapping):
			raise TypeError("boundary_conditions must be a mapping")

		parsed_boundary_conditions: dict[str, object] = {}

		dirichlet_payload = boundary_conditions.get("dirichlet")
		if isinstance(dirichlet_payload, Mapping):
			for bc_id in ("ocean", "stream"):
				sub_payload = dirichlet_payload.get(bc_id)
				if isinstance(sub_payload, Mapping):
					parsed_boundary_conditions[bc_id] = self._build_dirichlet_boundary_condition(
						bc_id=bc_id,
						payload=sub_payload,
					)

		robin_payload = boundary_conditions.get("robin")
		cauchy_payload = boundary_conditions.get("cauchy")
		if isinstance(cauchy_payload, Mapping):
			drainage_payload = cauchy_payload.get("drainage")
			if isinstance(drainage_payload, Mapping):
				parsed_boundary_conditions["drainage"] = self._build_drainage_boundary_condition(
					drainage_payload,
					expected_section="cauchy",
				)

		if isinstance(robin_payload, Mapping):
			drainage_payload = robin_payload.get("drainage")
			if isinstance(drainage_payload, Mapping):
				parsed_boundary_conditions.setdefault(
					"drainage",
					self._build_drainage_boundary_condition(
						drainage_payload,
						expected_section="robin",
					),
				)

		for raw_id, raw_payload in boundary_conditions.items():
			bc_id = str(raw_id).strip()
			if bc_id == "":
				raise ValueError("boundary_conditions cannot contain empty ids")
			if bc_id in {"dirichlet", "robin", "cauchy"}:
				continue
			if bc_id == "drainage" and "drainage" in parsed_boundary_conditions:
				continue
			parsed_boundary_conditions[bc_id] = self._coerce_boundary_condition_entry(
				bc_id=bc_id,
				raw_payload=raw_payload,
			)

		self.boundary_conditions.update(parsed_boundary_conditions)

	def _coerce_boundary_condition_entry(self, *, bc_id: str, raw_payload: object) -> object:
		if isinstance(raw_payload, BoundaryCondition):
			return raw_payload
		if not isinstance(raw_payload, Mapping):
			return raw_payload
		if "value" not in raw_payload:
			return dict(raw_payload)

		payload = dict(raw_payload)
		payload.setdefault("id", bc_id)
		payload.setdefault("description", "")
		payload.setdefault("units", "")
		payload.setdefault("type", "Dirichlet")
		payload.setdefault("data_value", False)
		return BoundaryCondition.model_validate(payload)

	def _build_drainage_boundary_condition(
		self,
		drainage_payload: Mapping[str, object],
		*,
		expected_section: str,
	) -> BoundaryCondition:
		if "value" not in drainage_payload:
			raise ValueError(f"flow.bc.{expected_section}.drainage.value is required")

		value = drainage_payload["value"]
		if not isinstance(value, Real):
			raise TypeError(
				f"flow.bc.{expected_section}.drainage.value must be a numeric value"
			)

		raw_application_domain = drainage_payload.get("application_domain")
		if not isinstance(raw_application_domain, str):
			raise TypeError(
				f"flow.bc.{expected_section}.drainage.application_domain must be a string"
			)
		application_domain = raw_application_domain.strip()
		if application_domain == "":
			raise ValueError(
				f"flow.bc.{expected_section}.drainage.application_domain cannot be empty"
			)

		allowed_domains = {"top", "north side", "west side", "east side", "south side"}
		if application_domain not in allowed_domains:
			raise ValueError(
				f"flow.bc.{expected_section}.drainage.application_domain contains an invalid value: "
				+ application_domain
			)

		raw_type = drainage_payload.get("type", "cauchy")
		bc_type = str(raw_type).lower()
		if bc_type not in {"cauchy", "robin"}:
			raise ValueError(
				f"flow.bc.{expected_section}.drainage.type must be 'cauchy' or 'robin'"
			)

		data_value = bool(drainage_payload.get("data_value", False))
		units = str(drainage_payload.get("units", "m2/s"))

		self.boundary_condition_application_domains["drainage"] = application_domain

		return BoundaryCondition(
			id="drainage",
			value=float(value),
			description=(
				f"{bc_type.capitalize()} drainage boundary condition on "
				+ application_domain
			),
			units=units,
			type=bc_type,
			data_value=data_value,
		)

	def _build_dirichlet_boundary_condition(
		self,
		*,
		bc_id: str,
		payload: Mapping[str, object],
	) -> BoundaryCondition:
		if "value" not in payload:
			raise ValueError(f"flow.bc.dirichlet.{bc_id}.value is required")

		value = payload["value"]
		if not isinstance(value, Real):
			raise TypeError(f"flow.bc.dirichlet.{bc_id}.value must be a numeric value")

		raw_type = payload.get("type", "dirichlet")
		if str(raw_type).lower() != "dirichlet":
			raise ValueError(f"flow.bc.dirichlet.{bc_id}.type must be 'dirichlet'")

		raw_application_domain = payload.get("application_domain")
		if not isinstance(raw_application_domain, str):
			raise TypeError(
				f"flow.bc.dirichlet.{bc_id}.application_domain must be a string"
			)
		application_domain = raw_application_domain.strip()
		if application_domain == "":
			raise ValueError(
				f"flow.bc.dirichlet.{bc_id}.application_domain cannot be empty"
			)

		allowed_domains = {"top", "north side", "west side", "east side", "south side"}
		if application_domain not in allowed_domains:
			raise ValueError(
				f"flow.bc.dirichlet.{bc_id}.application_domain contains an invalid value: "
				+ application_domain
			)

		self.boundary_condition_application_domains[bc_id] = application_domain

		data_value = bool(payload.get("data_value", False))
		units = str(payload.get("units", "m"))
		description = f"Dirichlet boundary condition '{bc_id}' on {application_domain}"
		if data_value:
			description += " (data_value=True)"

		return BoundaryCondition(
			id=bc_id,
			value=float(value),
			description=description,
			units=units,
			type="dirichlet",
			data_value=data_value,
		)

	def set_sinks_sources(self, wells_sources: dict):
		self.sinks_sources.update(wells_sources)
  
if __name__ == "__main__":
    test = Flow()
    Sy = Parameter(id='Sy', value=0.1, description='Specific yield', units='-', field_type='homogeneous')
    h = Variable(id='h', value=0, description='Hydraulic head', units='m')
    q = Variable(id='q', value=0, description='Flow rate', units='m3/s')
    h0 = InitialCondition(id='h0', value=10, description='Initial hydraulic head', units='m')
    h_ocean = BoundaryCondition(id='h_ocean', value=0, description='Ocean boundary condition', units='m', type='Dirichlet', data_value=False)
    drain = BoundaryCondition(id='drain', value=0, description='Drain boundary condition', units='m', type='Cauchy', data_value=False)
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
    
