"""A sealed run whose hydrograph output still carries a removed key is refused for that key.

The protocol compares the point output it writes with the one a sealed run
spelled out. An output that no longer validates is not another output under
the same name: the refusal names the key, here the per-output
``diagonal_neighbors`` the descent D made obsolete.
"""

from __future__ import annotations

import pytest

from hydromodpy.calibration.config import MatchingHydrographicNetworkOptions
from hydromodpy.calibration.protocols.matching_hydrographic_network import (
    HYDROGRAPH_OUTPUT,
    _write_hydrograph_output,
)


def _sealed(**extra: object) -> dict[str, object]:
    return {
        HYDROGRAPH_OUTPUT: {
            "variable": "discharge",
            "support": "point",
            "observes": "NANCON",
            **extra,
        }
    }


def test_a_removed_key_is_named_and_not_read_as_a_collision() -> None:
    outputs = _sealed(diagonal_neighbors=False)

    with pytest.raises(
        ValueError, match="'diagonal_neighbors', which this output does not"
    ) as info:
        _write_hydrograph_output(
            outputs,
            MatchingHydrographicNetworkOptions(name="matching_hydrographic_network"),
            "NANCON",
        )

    assert "Rename it" not in str(info.value)


def test_the_same_output_without_the_key_is_accepted() -> None:
    outputs = _sealed()

    _write_hydrograph_output(
        outputs, MatchingHydrographicNetworkOptions(name="matching_hydrographic_network"), "NANCON"
    )

    assert outputs[HYDROGRAPH_OUTPUT]["observes"] == "NANCON"


def test_another_output_under_the_name_is_still_a_collision() -> None:
    outputs = _sealed(observes="OTHER")

    with pytest.raises(ValueError, match="Rename it"):
        _write_hydrograph_output(
            outputs,
            MatchingHydrographicNetworkOptions(name="matching_hydrographic_network"),
            "NANCON",
        )
