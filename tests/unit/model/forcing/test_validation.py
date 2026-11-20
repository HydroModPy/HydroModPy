"""Recharge table {period: rate}: keys read as integer period indices, every period stated.

A TOML key is a string, so a table written in a file reaches the solvers with "0", "1", ...
Each key must name a period of the run and no period may be written twice.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hydromodpy.model.forcing.validation import complete_period_table, integer_period_keys
from hydromodpy.model.sinks_sources.recharge import FlowRechargeConfig

LABEL = "flow.sinks_sources.recharge.values"


@pytest.mark.parametrize("key", ["january", "1.5", "-1", 1.5, True])
def test_key_that_is_no_period_is_refused(key):
    with pytest.raises(ValidationError, match="period index"):
        FlowRechargeConfig(values={key: 1.0})


def test_same_period_written_twice_is_refused():
    with pytest.raises(ValueError, match="names period 1 twice"):
        integer_period_keys({"1": 1.0, 1: 2.0}, label=LABEL)


def test_period_outside_the_run_is_named():
    with pytest.raises(ValueError, match=r"names period\(s\) \[5\]"):
        complete_period_table({0: 1.0, 1: 2.0, 5: 3.0}, nper=2, label=LABEL)
