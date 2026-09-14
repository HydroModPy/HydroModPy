"""The FlowLakeConfig physics payload and its outlet discriminated union.

A lake rides inside ``[flow.sinks_sources.lakes.<id>]``. It carries the BC
parameters (bedleak, stageinit, outlets) and the transient forcings. The
tests check:

* a well-formed lake (with WEIR / MANNING / SPECIFIED outlets) validates and the
  discriminated union picks the right outlet class from ``couttype``;
* a bad config is rejected: negative bedleak, a weir without an invert, an extra
  field (``extra='forbid'`` on HydroModelBase), and a SPECIFIED outlet with
  neither rate nor forcing;
* a controlled LAK -> LAK transfer parses into a typed :class:`FlowLakeOutletMover`
  on the outlet's ``mover`` field, with FACTOR / 1.0 defaults, and rejects a
  bad receiving lake, an unknown ``mvrtype`` and a negative ``value``.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from hydromodpy.physics.flow.flow_config import FlowConfig
from hydromodpy.physics.flow.sinks_sources import (
    FlowLakeConfig,
    FlowLakeOutletManning,
    FlowLakeOutletMover,
    FlowLakeOutletSpecified,
    FlowLakeOutletWeir,
    FlowSinksSourcesConfig,
)
from hydromodpy.physics.flow.structure_binders import _lake_payloads_as_mappings
from hydromodpy.solver.modflow6.builders.lake import convert_bedleak_to_per_s


def test_lake_config_validates_outlets_and_picks_the_right_class() -> None:
    lake = FlowLakeConfig.model_validate(
        {
            "bedleak": 0.1,
            "stageinit": "85 m",
            "outlets": [
                {"couttype": "WEIR", "invert": "87 m", "width": "30 m", "lakeout": 1},
                {
                    "couttype": "MANNING",
                    "invert": "90 m",
                    "width": "5 m",
                    "rough": 0.03,
                    "slope": 1.0e-3,
                },
                {"couttype": "SPECIFIED", "rate": "0.5 m**3/s"},
            ],
        }
    )

    assert lake.bedleak == pytest.approx(0.1)
    # stageinit is a Length quantity; its canonical magnitude is metres.
    assert float(lake.stageinit.to("m").magnitude) == pytest.approx(85.0)

    weir, manning, specified = lake.outlets
    assert isinstance(weir, FlowLakeOutletWeir)
    assert isinstance(manning, FlowLakeOutletManning)
    assert isinstance(specified, FlowLakeOutletSpecified)
    assert weir.lakeout == 1
    assert float(weir.invert.to("m").magnitude) == pytest.approx(87.0)
    assert manning.rough == pytest.approx(0.03)
    assert float(specified.rate.to("m**3/s").magnitude) == pytest.approx(0.5)


def test_lake_config_rejects_negative_bedleak() -> None:
    with pytest.raises(ValueError, match="bedleak"):
        FlowLakeConfig.model_validate({"bedleak": -1.0, "stageinit": "85 m"})


def test_bedleak_unit_defaults_and_validates() -> None:
    # bedleak_unit defaults to 1/s, accepts a leakance unit (and its aliases), and
    # rejects a non-leakance unit at config time.
    assert (
        FlowLakeConfig.model_validate({"bedleak": 1.0, "stageinit": "85 m"}).bedleak_unit == "1/s"
    )
    day = FlowLakeConfig.model_validate(
        {"bedleak": 1.0, "stageinit": "85 m", "bedleak_unit": "1/day"}
    )
    assert day.bedleak_unit == "1/day"
    with pytest.raises(ValueError, match="leakance"):
        FlowLakeConfig.model_validate({"bedleak": 1.0, "stageinit": "85 m", "bedleak_unit": "m"})


def test_bedleak_unit_reaches_the_builder_through_the_binder() -> None:
    # The config bedleak_unit must survive normalisation to the dict payload the
    # LAK builder reads, so a 1/day leakance is converted to 1/s rather than being
    # silently taken as 1/s (an 86400x conductance error).
    lake = FlowLakeConfig.model_validate(
        {"bedleak": 1.0, "stageinit": "85 m", "bedleak_unit": "1/day"}
    )
    flow = SimpleNamespace(sinks_sources={"lakes": {"lac0": lake}})
    payloads = _lake_payloads_as_mappings(flow)
    assert payloads["lac0"]["bedleak_unit"] == "1/day"
    converted = convert_bedleak_to_per_s(
        payloads["lac0"]["bedleak"], lake_id="lac0", unit=payloads["lac0"]["bedleak_unit"]
    )
    assert converted == pytest.approx(1.0 / 86400.0)


def test_occupied_layers_defaults_and_validates() -> None:
    # Surface lake by default; a deep reservoir declares more occupied layers.
    assert FlowLakeConfig.model_validate({"bedleak": 0.1, "stageinit": "85 m"}).occupied_layers == 1
    deep = FlowLakeConfig.model_validate(
        {"bedleak": 0.1, "stageinit": "85 m", "occupied_layers": 3}
    )
    assert deep.occupied_layers == 3
    with pytest.raises(ValueError):
        FlowLakeConfig.model_validate({"bedleak": 0.1, "stageinit": "85 m", "occupied_layers": 0})


def test_weir_outlet_without_invert_is_rejected() -> None:
    with pytest.raises(ValueError):
        FlowLakeConfig.model_validate(
            {
                "bedleak": 0.1,
                "stageinit": "85 m",
                "outlets": [{"couttype": "WEIR", "width": "30 m"}],
            }
        )


def test_specified_outlet_needs_rate_or_forcing() -> None:
    with pytest.raises(ValueError, match="requires either rate or forcing"):
        FlowLakeConfig.model_validate(
            {
                "bedleak": 0.1,
                "stageinit": "85 m",
                "outlets": [{"couttype": "SPECIFIED"}],
            }
        )


def test_lake_config_forbids_extra_fields() -> None:
    with pytest.raises(ValueError):
        FlowLakeConfig.model_validate(
            {"bedleak": 0.1, "stageinit": "85 m", "spillway_color": "blue"}
        )


def test_weir_outlet_with_mover_parses_into_typed_mover() -> None:
    # A controlled transfer keeps lakeout = 0 (external on the LAK side) and
    # carries a typed mover spec routed onward through MVR.
    lake = FlowLakeConfig.model_validate(
        {
            "bedleak": 0.1,
            "stageinit": "85 m",
            "outlets": [
                {
                    "couttype": "WEIR",
                    "invert": "87 m",
                    "width": "30 m",
                    "lakeout": 0,
                    "mover": {"lake": 2, "mvrtype": "UPTO", "value": 12.0},
                }
            ],
        }
    )
    (weir,) = lake.outlets
    assert isinstance(weir, FlowLakeOutletWeir)
    assert weir.lakeout == 0
    assert isinstance(weir.mover, FlowLakeOutletMover)
    assert weir.mover.lake == 2
    assert weir.mover.mvrtype == "UPTO"
    assert weir.mover.value == pytest.approx(12.0)


def test_outlet_with_lakeout_and_mover_is_rejected() -> None:
    # An outlet routes either directly (lakeout > 0) or through a mover, never
    # both. Setting both is a config error.
    with pytest.raises(ValueError, match="sets both lakeout and mover"):
        FlowLakeConfig.model_validate(
            {
                "bedleak": 0.1,
                "stageinit": "85 m",
                "outlets": [
                    {
                        "couttype": "WEIR",
                        "invert": "87 m",
                        "width": "30 m",
                        "lakeout": 2,
                        "mover": {"lake": 2, "mvrtype": "FACTOR", "value": 1.0},
                    }
                ],
            }
        )


def test_mover_defaults_to_factor_one() -> None:
    # A bare mover (only the receiving lake) defaults to FACTOR with the whole
    # provider flow (value 1.0).
    mover = FlowLakeOutletMover.model_validate({"lake": 1})
    assert mover.mvrtype == "FACTOR"
    assert mover.value == pytest.approx(1.0)


def test_mover_without_outlet_keeps_field_none() -> None:
    weir = FlowLakeOutletWeir.model_validate(
        {"couttype": "WEIR", "invert": "87 m", "width": "30 m"}
    )
    assert weir.mover is None


def test_mover_rejects_zero_or_external_lake() -> None:
    # The receiving lake is a 1-based number; 0 (external) is not a valid MVR
    # destination -- that case is a plain direct lakeout, not a mover.
    with pytest.raises(ValueError, match="lake"):
        FlowLakeOutletMover.model_validate({"lake": 0})


def test_mover_rejects_unknown_mvrtype() -> None:
    with pytest.raises(ValueError, match="mvrtype"):
        FlowLakeOutletMover.model_validate({"lake": 2, "mvrtype": "SIPHON"})


def test_mover_rejects_negative_value() -> None:
    with pytest.raises(ValueError, match="value"):
        FlowLakeOutletMover.model_validate({"lake": 2, "mvrtype": "UPTO", "value": -1.0})


def test_specified_outlet_carries_mover_too() -> None:
    # The mover field lives on every outlet type, not just WEIR.
    lake = FlowLakeConfig.model_validate(
        {
            "bedleak": 0.1,
            "stageinit": "85 m",
            "outlets": [
                {
                    "couttype": "SPECIFIED",
                    "rate": "0.5 m**3/s",
                    "mover": {"lake": 1, "mvrtype": "EXCESS", "value": 0.2},
                }
            ],
        }
    )
    (specified,) = lake.outlets
    assert isinstance(specified, FlowLakeOutletSpecified)
    assert isinstance(specified.mover, FlowLakeOutletMover)
    assert specified.mover.mvrtype == "EXCESS"


def test_lake_rides_inside_flow_sinks_sources() -> None:
    cfg = FlowConfig(
        active_bc=["lake"],
        sinks_sources=FlowSinksSourcesConfig(
            lakes={
                "lac0": {
                    "bedleak": 0.2,
                    "stageinit": "85 m",
                    "outlets": [{"couttype": "WEIR", "invert": "87 m", "width": "30 m"}],
                    # rainfall is a rate (L/T); the value magnitude rides with a
                    # 'units' label that the LAK builder converts to m/s.
                    "rainfall": {"kind": "constant", "value": 0.004, "units": "m/day"},
                }
            }
        ),
    )

    lake = cfg.sinks_sources.lakes["lac0"]
    assert isinstance(lake, FlowLakeConfig)
    assert isinstance(lake.outlets[0], FlowLakeOutletWeir)
    assert lake.rainfall is not None
    assert lake.rainfall.kind == "constant"
