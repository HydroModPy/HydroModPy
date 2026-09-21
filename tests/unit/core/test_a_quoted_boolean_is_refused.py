"""A string where a boolean belongs is a refusal, not a guess.

TOML has native booleans, so a quoted one is always a mistake. Pydantic's lax
coercion read ``geotiff = "yes"`` as True and refused ``geotiff = "maybe"``,
which made one class of typo behave two different ways and let a run silently
do what the file did not ask for.

The refusal is narrow on purpose: it looks at the model's own fields and fires
only on a field that accepts nothing but a boolean. Every other coercion the
configuration surface depends on - pint quantity strings, str to Path, int to
float - is untouched, which is why ``ConfigDict(strict=True)`` is not the seam.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import pytest
from pydantic import Field, ValidationError

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.simulation.planning.export_config import ExportConfig
from hydromodpy.spatial.domain.depth_model_config import ConstantThicknessDepthModel


class _Toggles(HydroModelBase):
    """One field of each shape a boolean can take."""

    model_legacy_keys = {"raster": "geotiff"}

    geotiff: bool = Field(default=False, description="Plain boolean.")
    optional: bool | None = Field(default=None, description="Boolean or nothing.")
    tagged: Annotated[bool, Profile.EXPERT] = Field(default=False, description="Tagged boolean.")
    profile: bool | str = Field(default=False, description="Boolean, or a report path.")
    label: str = Field(default="", description="A string field.")
    dest: Path | None = Field(default=None, description="A path field.")


@pytest.mark.parametrize("value", ["yes", "true", "false", "no", "maybe", "1"])
def test_a_quoted_boolean_is_refused(value: str) -> None:
    with pytest.raises(ValidationError) as excinfo:
        _Toggles.model_validate({"geotiff": value})
    message = str(excinfo.value)
    assert f"geotiff = {value!r} is quoted" in message
    assert "TOML writes booleans unquoted" in message
    assert "geotiff = true or geotiff = false" in message


@pytest.mark.parametrize("value", [True, False])
def test_a_real_boolean_still_loads(value: bool) -> None:
    assert _Toggles.model_validate({"geotiff": value}).geotiff is value


def test_an_optional_boolean_refuses_a_string_and_keeps_none() -> None:
    with pytest.raises(ValidationError, match="optional = 'yes' is quoted"):
        _Toggles.model_validate({"optional": "yes"})
    assert _Toggles.model_validate({"optional": None}).optional is None
    assert _Toggles.model_validate({"optional": True}).optional is True


def test_a_tagged_boolean_is_refused_like_a_bare_one() -> None:
    with pytest.raises(ValidationError, match="tagged = 'yes' is quoted"):
        _Toggles.model_validate({"tagged": "yes"})


def test_a_field_that_admits_both_still_takes_a_string() -> None:
    """``workflow.profile`` is true, or the path of the HTML report to write."""
    assert _Toggles.model_validate({"profile": "run.profile.html"}).profile == "run.profile.html"
    assert _Toggles.model_validate({"profile": True}).profile is True


def test_the_old_spelling_of_a_boolean_key_is_refused_too() -> None:
    """The rename lands first, so the refusal names the spelling to write."""
    with pytest.warns(DeprecationWarning):
        with pytest.raises(ValidationError, match="geotiff = 'yes' is quoted"):
            _Toggles.model_validate({"raster": "yes"})


def test_the_other_coercions_are_untouched() -> None:
    kept = _Toggles.model_validate({"label": "run", "dest": "out/fields.nc"})
    assert kept.label == "run"
    assert kept.dest == Path("out/fields.nc")


def test_a_quantity_string_still_parses() -> None:
    assert ConstantThicknessDepthModel.model_validate({"thickness": "30.0 m"}).thickness == 30.0


def test_the_export_section_refuses_a_quoted_toggle() -> None:
    with pytest.raises(ValidationError, match="geotiff = 'yes' is quoted"):
        ExportConfig.model_validate({"geotiff": "yes"})
    assert ExportConfig.model_validate({"geotiff": True}).geotiff is True
