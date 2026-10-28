"""``[domain.supports.<id>]``: generated bands and rings are checked on load."""

from __future__ import annotations

import pytest

from hydromodpy.spatial.domain.spatial_support_config import (
    GeneratedBandsSupportConfig,
    GeneratedRingsSupportConfig,
)

KINDS = {"breaks": (GeneratedBandsSupportConfig, "generated_bands"), "radii": (GeneratedRingsSupportConfig, "generated_rings")}  # fmt: skip


def _load(key: str, values: object, *, mode: str = "absolute", labels: object = None):
    model, kind = KINDS[key]
    count = len(values) + 1 if isinstance(values, list) else 2
    labels = [f"zone_{index}" for index in range(count)] if labels is None else labels
    return model.model_validate(
        {"kind": kind, "coordinate_mode": mode, key: values, "labels": labels}
    )


@pytest.mark.parametrize("key", list(KINDS))
def test_absolute_coordinates_are_lengths_in_metres_and_labels_are_trimmed(key):
    config = _load(key, ["0.25 km", "300 m", 400.0], labels=[" a ", "b", "c", "d"])

    assert getattr(config, key) == [250.0, 300.0, 400.0]
    assert config.labels == ["a", "b", "c", "d"]


@pytest.mark.xfail(
    strict=True,
    raises=TypeError,
    reason="a bare number written as a string is parsed by pint as dimensionless and "
    "refused with a raw DimensionalityError, instead of being read as metres",
)
@pytest.mark.parametrize("key", list(KINDS))
def test_a_bare_number_written_as_a_string_is_read_as_metres(key):
    assert getattr(_load(key, ["300"]), key) == [300.0]


@pytest.mark.parametrize("key", list(KINDS))
@pytest.mark.parametrize(
    ("values", "mode", "labels", "error", "match"),
    [
        ([1.5], "relative", None, ValueError, "strictly between 0 and 1"),
        ([-3.0], "absolute", None, ValueError, "must be > 0"),
        ([None], "absolute", None, ValueError, "cannot be None"),
        ([True], "absolute", None, TypeError, "rejects boolean input"),
        ([" "], "absolute", None, ValueError, "empty length string"),
        ([[1.0]], "absolute", None, TypeError, "unsupported length value type list"),
        ([20.0, 10.0], "absolute", None, ValueError, "must be strictly increasing"),
        ([10.0, 10.0], "absolute", None, ValueError, "cannot contain duplicates"),
        ([10.0], "absolute", ["a", ""], ValueError, "cannot contain empty values"),
        ([10.0], "absolute", ["a"], ValueError, r"length must be len\("),
        ([10.0], "absolute", ["a", "a"], ValueError, "labels cannot contain duplicates"),
        ("10", "absolute", None, ValueError, "valid list"),
        ([10.0], "absolute", "ab", ValueError, "valid list"),
    ],
)  # fmt: skip
def test_coordinates_and_labels_that_do_not_cut_zones_are_refused(
    key, values, mode, labels, error, match
):
    with pytest.raises(error, match=match):
        _load(key, values, mode=mode, labels=labels)


@pytest.mark.parametrize("model", [GeneratedBandsSupportConfig, GeneratedRingsSupportConfig])
def test_a_support_that_is_not_a_table_is_refused(model):
    with pytest.raises(ValueError, match="valid dictionary"):
        model.model_validate("bands")
