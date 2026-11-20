"""The supports a heterogeneous parameter reads its zones from, and their providers.

The domain grid is 4 x 4 cells of 5 m from (10, 100) to (30, 120): center (20, 110), inradius 10 m.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.catchment.algorithms.catchment_zones_field import CatchmentZonesField
from hydromodpy.catchment.surface import Surface
from hydromodpy.core.exceptions import ConfigError, ConfigMissingError
from hydromodpy.model.domain.domain import Domain
from hydromodpy.model.domain.domain_config import DomainConfig
from hydromodpy.model.domain.spatial_support import (
    SpatialSupportProviderRegistry,
    SupportBuildContext,
    build_default_spatial_support_provider_registry,
    build_phase_supports,
    collect_requested_support_ids,
    resolve_support_configs,
    support_provider_names,
    validate_domain_support_contract,
)
from hydromodpy.model.domain.spatial_support_config import (
    CatchmentZonesSupportConfig,
    GeneratedBandsSupportConfig,
    GeneratedRingsSupportConfig,
    GeologySupportConfig,
)
from hydromodpy.model.domain.support_fields import (
    AliasedSpatialSupportField,
    GeneratedRingsSupportField,
    RasterZonesSupportField,
)
from hydromodpy.model.flow_config import FlowConfig
from tests._helpers.domain_cases import raster_support, surface

GRID = {"cell": 5.0, "x0": 10.0, "y0": 100.0}
CODES = np.array([[1, 1, 2, 3], [1, 2, 2, 3], [0, 2, 2, 3], [1, 1, 1, 0]], dtype=np.uint8)
ZONES = {1: "domain", 2: "buffer", 3: "core"}
REGISTRY = build_default_spatial_support_provider_registry()


def _domain() -> Domain:
    return Domain(DomainConfig(zone_ids=["catchment"]), surface_topo=surface(np.zeros((4, 4)), **GRID))  # fmt: skip


def _context(domain: object = None, loaded_data: object = None) -> SupportBuildContext:
    return SupportBuildContext(
        cfg=SimpleNamespace(), raw_toml={}, workspace=None, geographic=None, domain_geographic=None,
        domain=_domain() if domain is None else domain, flow=None, loaded_data=loaded_data, time_grid=None,
    )  # fmt: skip


def _build(kind: str, config: object, context: SupportBuildContext | None = None, support_id: str = "support"):  # fmt: skip
    return REGISTRY.get(kind).build(support_id=support_id, config=config, context=context or _context())  # fmt: skip


def _catchment_zones() -> CatchmentZonesField:
    return CatchmentZonesField(identifier="catchment_zones", encoded_codes=CODES, encoded_to_zone=ZONES)  # fmt: skip


@pytest.mark.parametrize(
    ("config", "cut", "points", "labels"),
    [
        (GeneratedBandsSupportConfig(kind="generated_bands", axis="x", breaks=[0.5], labels=["a", "b"]), [20.0], ([12.0, 25.0], [110.0, 110.0]), ["a", "b"]),
        (GeneratedBandsSupportConfig(kind="generated_bands", axis="y", coordinate_mode="absolute", breaks=["0.105 km"], labels=["a", "b"]), [105.0], ([20.0, 20.0], [101.0, 119.0]), ["a", "b"]),
        (GeneratedRingsSupportConfig(kind="generated_rings", radii=[0.5], labels=["a", "b"]), [5.0], ([20.0, 27.0], [110.0, 110.0]), ["a", "b"]),
        (GeneratedRingsSupportConfig(kind="generated_rings", coordinate_mode="absolute", radii=[2.0], center_x=15.0, center_y="0.112 km", labels=["a", "b"]),
         [2.0], ([15.0, 20.0], [111.0, 110.0]), ["a", "b"]),
    ],
    ids=["bands_relative_x", "bands_absolute_y", "rings_relative_around_the_centre", "rings_absolute_around_a_given_point"],
)  # fmt: skip
def test_generated_bands_and_rings_cut_the_domain_along_their_axis_or_around_their_centre(config, cut, points, labels):  # fmt: skip
    support = _build(config.kind, config, support_id="cut")

    assert (support.identifier, support.zone_keys) == ("cut", ("a", "b"))
    assert (support.breaks_abs if config.kind == "generated_bands" else support.radii_abs) == cut
    np.testing.assert_array_equal(support.zone_id(*map(np.array, points)), labels)


def test_catchment_zones_wrap_the_catchment_zone_of_the_domain():
    domain = _domain()
    domain.set_zone("catchment", _catchment_zones())

    support = _build("catchment_zones", CatchmentZonesSupportConfig(kind="catchment_zones"), _context(domain), "zones")  # fmt: skip

    assert isinstance(support, RasterZonesSupportField)
    assert (support.identifier, support.zone_keys, support.shape) == ("zones", ("domain", "buffer", "core"), (4, 4))  # fmt: skip
    x, y = np.array([[12.0, 27.0], [12.0, 40.0]]), np.array([[118.0, 118.0], [107.0, 110.0]])
    np.testing.assert_array_equal(support.zone_id(x, y), [["domain", "core"], ["", ""]])
    np.testing.assert_array_equal(_zonation().zone_id(np.array([0.0]), np.array([0.0])), [""])


def test_a_geology_support_is_the_loaded_geology_or_an_alias_of_it():
    geology = SimpleNamespace(identifier="field_geology", zone_keys=["granite", "schist"], default_cell_samples_per_axis=4,
                              on_mesh=lambda mesh, *, cell_samples_per_axis: (mesh, cell_samples_per_axis), units="lithology")  # fmt: skip
    context = _context(loaded_data=SimpleNamespace(geology=geology))
    config = GeologySupportConfig(kind="geology")

    assert _build("geology", config, context, "field_geology") is geology
    alias = _build("geology", config, context, "rocks")

    assert isinstance(alias, AliasedSpatialSupportField)
    assert (alias.identifier, alias.zone_keys, alias.default_cell_samples_per_axis, alias.units) == ("rocks", ("granite", "schist"), 4, "lithology")  # fmt: skip
    assert alias.on_mesh("mesh", cell_samples_per_axis=3) == ("mesh", 3)


def test_only_the_geology_provider_runs_in_the_data_phase():
    phases = {kind: REGISTRY.get(kind).build_phase for kind in ("generated_bands", "generated_rings", "catchment_zones", " Geology ")}  # fmt: skip

    assert phases.pop(" Geology ") == "data"
    assert set(phases.values()) == {"setup"}
    with pytest.raises(ValueError, match="Unknown spatial support provider 'voronoi'"):
        REGISTRY.get("voronoi")


_NO_SUPPORT = SimpleNamespace(surface_topo=Surface(name="surface_topo", values=np.zeros((2, 2))), get_zone=lambda _id: _catchment_zones())  # fmt: skip
_BANDS = GeneratedBandsSupportConfig(kind="generated_bands", coordinate_mode="absolute", breaks=[35.0], labels=["a", "b"])  # fmt: skip
_RINGS = GeneratedRingsSupportConfig(kind="generated_rings", coordinate_mode="absolute", radii=[10.0], labels=["a", "b"])  # fmt: skip
_CATCHMENT = CatchmentZonesSupportConfig(kind="catchment_zones")
_GEOLOGY = GeologySupportConfig(kind="geology")


@pytest.mark.parametrize(
    ("kind", "config", "context", "error", "match"),
    [
        ("generated_bands", _BANDS, _context(_NO_SUPPORT), ValueError, "requires domain.surface_topo.support"),
        ("generated_rings", _RINGS, _context(_NO_SUPPORT), ValueError, "requires domain.surface_topo.support"),
        ("catchment_zones", _CATCHMENT, _context(_NO_SUPPORT), ValueError, "requires domain.surface_topo.support"),
        ("generated_bands", _BANDS, None, ValueError, r"strictly inside the domain x extent \(10.0, 30.0\)"),
        ("generated_rings", _RINGS, None, ValueError, "strictly inside the largest inscribed circle"),
        ("generated_rings", _RINGS.model_copy(update={"center_x": 10.0}), None, ValueError, "center must lie strictly inside"),
        ("catchment_zones", _CATCHMENT, None, ValueError, "requires domain zone 'catchment'"),
        ("catchment_zones", _CATCHMENT, _context(SimpleNamespace(get_zone=lambda _id: object())), TypeError, "must expose encoded_codes"),
        ("geology", _GEOLOGY, None, ConfigMissingError, r"\[domain.supports.support\] kind = 'geology' reads the geology data, and none"),
        ("geology", _GEOLOGY, _context(loaded_data=SimpleNamespace()), ConfigMissingError, r"Declare \[data.geology\]"),
    ],
)  # fmt: skip
def test_a_provider_refuses_what_it_cannot_build(kind, config, context, error, match):
    with pytest.raises(error, match=match):
        _build(kind, config, context)


def _zonation(**change: object) -> RasterZonesSupportField:
    arguments = {"identifier": "zones", "encoded_codes": CODES, "encoded_to_zone": ZONES, "raster_support": raster_support(4, 4, **GRID)}  # fmt: skip
    return RasterZonesSupportField(**{**arguments, **change})


def _rings(radii: list[float], labels: list[str]) -> GeneratedRingsSupportField:
    return GeneratedRingsSupportField(identifier="rings", center_x=0.0, center_y=0.0, radii_abs=radii, labels=labels)  # fmt: skip


@pytest.mark.parametrize(
    ("build", "error", "match"),
    [
        (lambda: _zonation(encoded_codes=CODES[0]), ValueError, "must be a 2D integer array"),
        (lambda: _zonation(encoded_codes=np.zeros((0, 0))), ValueError, "cannot be empty"),
        (lambda: _zonation(encoded_to_zone={}), ValueError, "encoded_to_zone cannot be empty"),
        (lambda: _zonation(encoded_to_zone={**ZONES, -1: "deep"}), ValueError, "must be positive integers"),
        (lambda: _zonation(encoded_to_zone={**ZONES, 3: " "}), ValueError, "labels cannot be empty"),
        (lambda: _zonation(raster_support="EPSG:2154"), TypeError, "must be a RasterSupport instance"),
        (lambda: _zonation(raster_support=raster_support(4, 3, **GRID)), ValueError, "shape mismatch"),
        (lambda: _zonation(encoded_to_zone={1: "domain", 2: "buffer"}), ValueError, r"unknown class codes: \[3\]"),
        (lambda: _zonation().zone_id(np.zeros(2), np.zeros(3)), ValueError, "same shape"),
        (lambda: _rings([0.0], ["a", "b"]), ValueError, "strictly positive"),
        (lambda: _rings([2.0, 1.0], ["a", "b", "c"]), ValueError, "strictly increasing"),
        (lambda: _rings([1.0, 1.0], ["a", "b", "c"]), ValueError, "cannot contain duplicates"),
        (lambda: _rings([1.0], ["a"]), ValueError, r"len\(radii_abs\) \+ 1"),
        (lambda: _rings([1.0], ["a", " "]), ValueError, "cannot contain empty values"),
        (lambda: _rings([1.0], ["a", "a"]), ValueError, "labels cannot contain duplicates"),
    ],
)  # fmt: skip
def test_a_zonation_that_does_not_fit_its_grid_or_rings_that_do_not_nest_are_refused(build, error, match):  # fmt: skip
    with pytest.raises(error, match=match):
        build()


def test_collect_requested_support_ids_accepts_typed_flow_param():
    cfg = FlowConfig.model_validate(
        {
            "param_list": ["K", "Sy"],
            "param": {
                "K": {
                    "field": {
                        "id": "K",
                        "kind": "heterogeneous",
                        "values": {"left": "1e-4 m/s", "right": "5e-5 m/s"},
                        "field_spatial_id": "k_bands",
                    },
                },
                "Sy": {
                    "field": {"id": "Sy", "kind": "homogeneous", "value": 0.12},
                },
            },
        }
    )

    assert collect_requested_support_ids(cfg) == ("k_bands",)


def test_collect_requested_support_ids_accepts_resolved_dict_payload():
    flow_cfg = type(
        "FlowCfg",
        (),
        {
            "param": {
                "K": {
                    "id": "K",
                    "kind": "heterogeneous",
                    "values": {"left": 1e-4},
                    "field_spatial_id": "k_bands",
                }
            }
        },
    )()

    assert collect_requested_support_ids(flow_cfg) == ("k_bands",)


def test_a_support_with_no_extent_cannot_be_cut_into_bands():
    import dataclasses

    flat = _domain()
    support = dataclasses.replace(flat.surface_topo.support, xmax=flat.surface_topo.support.xmin)
    flat.surface_topo = Surface(name="surface_topo", values=np.zeros((4, 4)), support=support)

    with pytest.raises(ValueError, match="strictly positive"):
        _build("generated_bands", _BANDS, _context(flat))


class _Recorder:
    """A provider that records its builds."""

    def __init__(self, phase: str) -> None:
        self.provider_name = "recorder"
        self.build_phase = phase
        self.built: list[str] = []

    def build(self, *, support_id, config, context):
        self.built.append(support_id)
        return f"field-{support_id}"


class _Zones:
    """A domain that stores zones by id."""

    def __init__(self, **zones: object) -> None:
        self.zones = dict(zones)

    def get_zone(self, zone_id: str):
        return self.zones.get(zone_id)

    def set_zone(self, zone_id: str, field: object) -> None:
        self.zones[zone_id] = field


def _registry_with(provider: _Recorder) -> SpatialSupportProviderRegistry:
    registry = SpatialSupportProviderRegistry()
    registry.register(provider)
    return registry


@pytest.mark.parametrize(
    ("phase", "held", "built", "stored"),
    [
        pytest.param("setup", {}, ["a"], {"a": "field-a"}, id="builds_in_its_phase"),
        pytest.param("Data", {}, [], {}, id="waits_for_its_own_phase"),
        pytest.param("setup", {"a": SimpleNamespace(identifier=" a ")}, [], None, id="keeps_a_held_support"),
    ],
)  # fmt: skip
def test_build_phase_supports_builds_only_what_the_phase_asks(phase, held, built, stored):
    provider = _Recorder(phase)
    domain = _Zones(**held)

    build_phase_supports(
        domain, {"a": SimpleNamespace(kind="recorder")},
        registry=_registry_with(provider), phase="SETUP", context=_context(),
    )  # fmt: skip

    assert provider.built == built
    assert domain.zones == (held if stored is None else stored)


@pytest.mark.parametrize(
    ("param", "expected"),
    [
        pytest.param({"kind": "heterogeneous", "field_spatial_id": "A"}, ("A",), id="flat"),
        pytest.param({"field": {"kind": "heterogeneous", "field_spatial_id": "B"}}, ("B",), id="nested"),
        pytest.param({"field": {"kind": "homogeneous"}}, (), id="nested_homogeneous"),
        pytest.param({"kind": "homogeneous"}, (), id="flat_homogeneous"),
        pytest.param({"field": "not a table"}, (), id="no_kind"),
        pytest.param(SimpleNamespace(field=SimpleNamespace(kind="homogeneous")), (), id="typed_homogeneous"),
    ],
)  # fmt: skip
def test_requested_support_ids_read_flat_nested_and_typed_params(param, expected):
    assert collect_requested_support_ids(SimpleNamespace(param={"K": param})) == expected


def test_requested_support_ids_are_deduplicated_ignoring_case():
    params = {
        "K": {"kind": "heterogeneous", "field_spatial_id": "Bands"},
        "Sy": {"kind": "heterogeneous", "field_spatial_id": "bands"},
    }
    assert collect_requested_support_ids(SimpleNamespace(param=params)) == ("Bands",)


@pytest.mark.parametrize("flow_cfg", [SimpleNamespace(param=[1]), SimpleNamespace()])
def test_a_flow_without_a_param_table_requests_no_support(flow_cfg):
    assert collect_requested_support_ids(flow_cfg) == ()


def test_a_heterogeneous_param_without_a_support_id_is_refused():
    flow_cfg = SimpleNamespace(param={"K": {"kind": "heterogeneous"}})

    with pytest.raises(ConfigError, match="non-empty field_spatial_id"):
        collect_requested_support_ids(flow_cfg)


def test_support_provider_names_keep_order_and_drop_blank_and_repeats():
    configs = {
        "a": SimpleNamespace(kind="Generated_Bands"),
        "b": SimpleNamespace(kind="geology"),
        "c": SimpleNamespace(kind=" generated_bands "),
        "d": SimpleNamespace(),
    }
    assert support_provider_names(configs) == ("generated_bands", "geology")


@pytest.mark.parametrize(
    ("domain_cfg", "ids", "expected"),
    [
        pytest.param(SimpleNamespace(supports={}), (), {}, id="nothing_requested"),
        pytest.param(SimpleNamespace(supports={" Bands ": "cfg"}), ("bands",), {"bands": "cfg"}, id="case_and_blanks"),
        pytest.param(SimpleNamespace(supports=None), (), {}, id="none_with_no_request"),
    ],
)  # fmt: skip
def test_resolve_support_configs_matches_ids_ignoring_case(domain_cfg, ids, expected):
    assert resolve_support_configs(domain_cfg, ids) == expected


@pytest.mark.parametrize(
    ("domain_cfg", "error", "match"),
    [
        (SimpleNamespace(supports=None), ConfigError, "Missing domain support declaration for 'k'"),
        (SimpleNamespace(supports={"other": 1}), ConfigError, "explicit provider"),
        (SimpleNamespace(supports=["k"]), TypeError, "must be a dictionary"),
    ],
)  # fmt: skip
def test_resolve_support_configs_refuses_what_is_not_declared(domain_cfg, error, match):
    with pytest.raises(error, match=match):
        resolve_support_configs(domain_cfg, ("k",))


def _flow(**params: object) -> SimpleNamespace:
    return SimpleNamespace(parameters=params)


def _param(support_id: str, heterogeneous: bool = True) -> SimpleNamespace:
    return SimpleNamespace(is_heterogeneous=heterogeneous, field_spatial_id=support_id)


@pytest.mark.parametrize(
    ("flow", "declared"),
    [
        pytest.param(None, {}, id="no_flow"),
        pytest.param(SimpleNamespace(parameters=3), {}, id="parameters_not_a_table"),
        pytest.param(_flow(K=_param("x", False)), {}, id="homogeneous_param"),
        pytest.param(_flow(K=_param("Bands")), {"bands": 1}, id="declared"),
    ],
)  # fmt: skip
def test_the_support_contract_passes_when_every_support_is_declared(flow, declared):
    validate_domain_support_contract(flow, declared)


def test_the_support_contract_names_each_missing_support_once():
    flow = _flow(K=_param("a"), Sy=_param("A"), Ss=_param("b"))

    with pytest.raises(ConfigError, match=r"declarations for: a, b\."):
        validate_domain_support_contract(flow, {})


def test_the_support_contract_refuses_a_blank_support_id():
    with pytest.raises(ConfigError, match="non-empty field_spatial_id"):
        validate_domain_support_contract(_flow(K=_param("  ")), {})
