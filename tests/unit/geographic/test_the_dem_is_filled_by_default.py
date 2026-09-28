"""The DEM is conditioned by filling unless a file asks for breaching.

Filling is the tool of the paper behind the network criterion, and the
criterion fills the model top on the mesh itself, so one rule runs from the
DEM to the score. Breaching stays available for a file that writes it.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hydromodpy.spatial.geographic.geographic_config import GeographicConfig


def test_a_file_that_says_nothing_gets_fill() -> None:
    assert GeographicConfig(source_mode="synthetic").dem_correc_type == "fill"


def test_a_file_that_writes_breach_keeps_it() -> None:
    config = GeographicConfig(source_mode="synthetic", dem_correc_type="breach")
    assert config.dem_correc_type == "breach"


def test_an_unknown_method_is_refused() -> None:
    with pytest.raises(ValidationError):
        GeographicConfig(source_mode="synthetic", dem_correc_type="carve")


def test_the_description_says_what_each_method_does_and_why_fill_leads() -> None:
    description = GeographicConfig.model_fields["dem_correc_type"].description or ""
    assert "'fill' (default)" in description
    assert "spill level" in description
    assert "'breach'" in description
    assert "Lindsay 2016" in description
    assert "FillDepressions" in description
    assert "recommended" not in description
