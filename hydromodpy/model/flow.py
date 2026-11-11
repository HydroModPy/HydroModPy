"""The flow process as the setup binds it, before the ``Model`` is built.

``Flow`` is built from one validated ``FlowConfig`` by the setup step, and the
data step binds what the configuration only names: the ocean level, the
recharge and ETP rates, the lakes, the stream networks, the barriers and the
runoff. The ``prepare_solver`` step then builds the frozen
``hydromodpy.model.model.Model`` from it with ``model_from_flow``, once per run.
No backend reads a ``Flow``.

After ``set_config`` a flow holds ten members: ``config``, ``flow_regime``,
``first_period_steady``, ``parameters`` (a ``FieldParam`` by ``[flow.param]``
id, in the order of ``param_list``), ``initial_conditions``,
``boundary_conditions`` (typed ``[flow.bc]`` payloads by id),
``boundary_condition_bundle``, ``active_bc``, ``sinks_sources`` (keys
``wells``, ``lakes``, ``sfr``, ``flow_barriers``, ``recharge`` and ``etp``) and
``active_sinks_sources``. Recharge and ETP are converted to m/s and well fluxes
to m3/s when they are set. The recharge binder also reads
``native_recharge``, the forcing at the step of its source for a global
solver, in m/s; it stays ``None`` when no source gives one.
"""

from collections.abc import Iterable, Mapping
from numbers import Real

from hydromodpy.core.logging import get_logger
from hydromodpy.core.units.quantities import (
    convert_payload_to_m_per_s,
    convert_to_m3_per_s,
    convert_to_m_per_s,
    normalize_m3_per_s_unit,
    normalize_m_per_s_unit,
)
from hydromodpy.model.boundaries.boundary_condition_registry import BoundaryConditionBundle
from hydromodpy.model.boundaries.boundary_conditions import FlowBoundaryConditionConfig
from hydromodpy.model.flow_config import FlowConfig
from hydromodpy.model.forcing.native import NativeSeries
from hydromodpy.model.initial_config import FlowInitialConditions, normalize_flow_initial_conditions
from hydromodpy.model.payloads import BoundaryCondition
from hydromodpy.model.properties.field_param import FieldParam
from hydromodpy.model.sinks_sources.container import FlowSinksSourcesConfig
from hydromodpy.model.sinks_sources.etp import FlowEtpConfig
from hydromodpy.model.sinks_sources.recharge import FlowRechargeConfig


def _flux_payload_update(
    payload: object,
    *,
    values_si: object,
    canonical_units: str,
    location_prefix: str,
) -> dict[str, object]:
    """Return the SI update for a flux payload, first period included.

    ``first_clim`` overrides one entry of ``values``, so a numeric override is
    written in the payload unit and has to follow it into m/s. The two keywords
    name a statistic of the converted series and stay as they are.
    """
    update: dict[str, object] = {"values": values_si, "units": "m/s"}
    first_clim = getattr(payload, "first_clim", "mean")
    if isinstance(first_clim, Real) and not isinstance(first_clim, bool):
        update["first_clim"] = convert_to_m_per_s(
            first_clim,
            unit=canonical_units,
            label=f"{location_prefix}.first_clim",
        )
    return update


logger = get_logger(__name__)


def flow_profiles(config: FlowConfig, ids: Iterable[str] | None = None) -> dict[str, object]:
    """Return the property profiles of a flow configuration, by ``[flow.param]`` id.

    The ids come in the order ``param_list`` declares. ``ids`` keeps only those
    named, still in that order. A ``Flow`` takes its parameters from here, and a
    calibration trial that moves only properties derives its ``Model`` from the
    same function, so the two never build a profile two ways.
    """
    wanted = None if ids is None else set(ids)
    profiles: dict[str, object] = {}
    for param_id in config.param_list:
        if wanted is not None and param_id not in wanted:
            continue
        param_cfg = config.param.get(param_id)
        if param_cfg is None:
            raise KeyError(f"Missing flow.param.{param_id} payload for declared parameter id")
        resolved_payload = getattr(param_cfg, "resolved_payload", None)
        payload = (
            resolved_payload(param_id=param_id, section_label=f"flow.param.{param_id}")
            if callable(resolved_payload)
            else param_cfg
        )
        profiles[param_id] = _coerce_field_param(param_id, payload)
    if wanted is not None and wanted - profiles.keys():
        missing = ", ".join(sorted(wanted - profiles.keys()))
        raise KeyError(f"flow.param_list declares no {missing}")
    return profiles


def _coerce_field_param(parameter_id: str, raw_parameter: object) -> object:
    """Coerce one raw config value into a runtime parameter object."""
    if not isinstance(raw_parameter, Mapping):
        return raw_parameter

    payload = dict(raw_parameter)
    field_payload = payload.get("field")
    if isinstance(field_payload, Mapping):
        payload = dict(field_payload)
        if "field_vertical_profile" in raw_parameter and "vertical_profile" not in payload:
            payload["vertical_profile"] = raw_parameter["field_vertical_profile"]
    payload.setdefault("id", parameter_id)
    if "kind" not in payload:
        return raw_parameter
    return FieldParam.from_dict(payload)


class Flow:
    """The flow process of one run, built from a validated ``FlowConfig``.

    ``set_config`` fills the members from the configuration, and the data step
    completes ``sinks_sources`` with its ``set_*`` methods and the binders of
    ``model/boundaries``. Holds the runtime containers ``parameters``, ``initial_conditions``,
    ``boundary_conditions`` and ``sinks_sources`` with their active ids.
    """

    def __init__(self, config: FlowConfig):
        """
        Build one `Flow` runtime object from one validated config.

        Parameters
        ----------
        config : FlowConfig
            Typed flow configuration payload.
        """
        if not isinstance(config, FlowConfig):
            raise TypeError("config must be a FlowConfig instance")
        self.parameters: dict[str, object] = {}
        self.boundary_conditions: dict[str, BoundaryCondition] = {}
        self.sinks_sources: dict[str, object] = {}
        self.active_sinks_sources: list[str] = []
        self.active_bc: list[str] = []
        self.config: FlowConfig
        self.flow_regime: str
        self.first_period_steady: bool
        self.initial_conditions: FlowInitialConditions | None = None
        self.native_recharge: NativeSeries | None = None
        self.boundary_condition_bundle: BoundaryConditionBundle = BoundaryConditionBundle(
            conditions={},
            active_ids=(),
        )
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
        4. ``active_*`` lists are read from what config declares, then
           ``boundary_conditions`` and ``boundary_condition_bundle`` are built
           from ``config.bc``.
        5. ``sinks_sources`` is populated from ``config.sinks_sources``
           (wells dict + recharge config).
        """
        if not isinstance(config, FlowConfig):
            raise TypeError("config must be a FlowConfig instance")

        self.config = config
        self.flow_regime = config.flow_regime
        self.first_period_steady = config.first_period_steady
        # Parameters are resolved in the declared order from `flow.param_list`.
        self.parameters = flow_profiles(config)
        # Flow has one typed IC structure (`FlowInitialConditions`).
        self.set_initial_conditions(config.ic)
        # Solver adapters process what is declared and not switched off.
        self.active_sinks_sources = list(config.active_sinks_sources)
        self.active_bc = list(config.active_bc)
        self.set_boundary_conditions(self._build_boundary_conditions(config.bc))
        # Sinks/sources are stored in a process-level dictionary namespace.
        self.set_sinks_sources(config.sinks_sources)
        # The recharge binder reads the forcing at its native step from a
        # data-manager source, if the run carries one; ``None`` when no
        # source gives one.
        self.native_recharge = None

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
    ) -> dict[str, FlowBoundaryConditionConfig]:
        """
        Convert raw boundary-condition payloads into typed boundary conditions.

        Each entry in ``boundary_conditions_cfg`` is either:

        - an already-typed ``FlowBoundaryConditionConfig``;
        - a legacy base ``BoundaryCondition`` converted to the flow model; or
        - a raw mapping validated via ``FlowBoundaryConditionConfig``.

        For mapping payloads, ``id`` is always forced to the TOML section key
        (e.g. ``"ocean"``, ``"west_side"``). This prevents the ``id`` field
        in the TOML from diverging from the key actually used to look up the
        BC at runtime, which would cause silent mismatches in the adapter.
        A mapping's ``application_domain`` is dropped before validation.
        """
        parsed: dict[str, FlowBoundaryConditionConfig] = {}

        for bc_id, raw_payload in boundary_conditions_cfg.items():
            # Allow already-instantiated typed payloads.
            if isinstance(raw_payload, FlowBoundaryConditionConfig):
                if raw_payload.value is None and raw_payload.forcing is None:
                    # A head boundary declared with no head. A solver treats it as
                    # one with nothing to build, or refuses it where it must have one.
                    if raw_payload.enabled:
                        logger.warning(
                            "[flow.bc.%s] gives no value and no forcing, so MODFLOW builds "
                            "no constant head there and Boussinesq refuses the run.",
                            bc_id,
                        )
                    continue
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
            # A mapping's domain hint fed a mirror nothing read; it stays out of
            # validation as before, so the typed payload keeps its own default.
            payload.pop("application_domain", None)
            payload["id"] = bc_id
            parsed[bc_id] = FlowBoundaryConditionConfig.model_validate(payload)

        return parsed

    def set_initial_conditions(
        self,
        initial_conditions: object | None,
    ) -> None:
        """Normalize and store the flow initial conditions."""
        self.initial_conditions = self.build_initial_conditions(initial_conditions)

    def set_boundary_conditions(
        self,
        boundary_conditions: dict[str, FlowBoundaryConditionConfig] | None = None,
    ) -> None:
        """Replace the typed boundary conditions, keyed by boundary id, and their bundle."""
        if boundary_conditions is None:
            self.boundary_conditions = {}
        else:
            self.boundary_conditions = dict(boundary_conditions)
        self._refresh_boundary_condition_bundle()

    def _refresh_boundary_condition_bundle(self) -> None:
        """Rebuild the compact runtime view over active and configured BCs."""
        self.boundary_condition_bundle = BoundaryConditionBundle.from_flow(self)

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
            self.sinks_sources["lakes"] = {}
            self.sinks_sources["sfr"] = {}
            self.sinks_sources["flow_barriers"] = {}
            self.sinks_sources["recharge"] = None
            return

        normalized_wells = {}
        for well_id, well_cfg in sinks_sources.enabled_wells().items():
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
        self.sinks_sources["lakes"] = sinks_sources.enabled_lakes()
        self.sinks_sources["sfr"] = sinks_sources.enabled_networks()
        self.sinks_sources["flow_barriers"] = sinks_sources.enabled_barriers()
        self.sinks_sources["recharge"] = self._normalize_recharge_config(
            sinks_sources.recharge,
            location_prefix="flow.sinks_sources.recharge",
        )
        self.sinks_sources["etp"] = self._normalize_etp_config(
            getattr(sinks_sources, "etp", None),
            location_prefix="flow.sinks_sources.etp",
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
            scale=recharge.factor,
        )
        update = _flux_payload_update(
            recharge,
            values_si=values_si,
            canonical_units=canonical_units,
            location_prefix=location_prefix,
        )
        if "first_clim" in update:
            update["first_clim"] *= recharge.factor
        # The payload now holds the scaled rate, so normalizing it again moves nothing.
        return recharge.model_copy(update={**update, "factor": 1.0})

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

    @staticmethod
    def _normalize_etp_config(
        etp: FlowEtpConfig | None,
        *,
        location_prefix: str,
    ) -> FlowEtpConfig | None:
        if etp is None:
            return None
        raw_units = getattr(etp, "units", "m/s")
        try:
            canonical_units = normalize_m_per_s_unit(raw_units)
        except ValueError as exc:
            raise ValueError(
                f"{location_prefix}.units must be compatible with m/s "
                f"(for example mm/day, m/day, m/s). Got: {raw_units!r}"
            ) from exc

        values_si = convert_payload_to_m_per_s(
            getattr(etp, "values", 0.0),
            unit=canonical_units,
            label=f"{location_prefix}.values",
        )
        return etp.model_copy(
            update=_flux_payload_update(
                etp,
                values_si=values_si,
                canonical_units=canonical_units,
                location_prefix=location_prefix,
            )
        )

    def set_etp(self, etp: FlowEtpConfig | None) -> None:
        """Inject or replace the ETP payload at runtime."""
        self.sinks_sources["etp"] = self._normalize_etp_config(
            etp,
            location_prefix="flow.sinks_sources.etp",
        )
