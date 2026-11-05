"""The base class of every configuration model: legacy, retired and refused keys, frozen copies."""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import Annotated, Literal

import pytest
from pydantic import Field, ValidationError

from hydromodpy.core.config_kit import base
from hydromodpy.core.config_kit.base import (
    CANNOT_REWRITE,
    ConfigKeyRenamedWarning,
    HydroModelBase,
    forget_old_forms_told,
    frozen_copy,
    refuse_old_forms,
    thawed_copy,
    warn_old_form,
    write_resolved,
)
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.config_kit.visible_when import VisibleWhen
from hydromodpy.core.exceptions import ConfigValidationError, FrozenConfigError
from hydromodpy.display.config import DisplayConfig
from hydromodpy.spatial.domain.depth_model_config import ConstantThicknessDepthModel


class _Inner(HydroModelBase):
    depth: float = 1.0


class _Cfg(HydroModelBase):
    model_retired_keys = frozenset({"old_flag"})
    model_refused_keys = {"mode": "use 'engine' instead"}
    model_legacy_keys = {"method": "engine"}

    engine: str = "grid"
    verbose: bool = False
    inner: _Inner = _Inner()
    rows: list[_Inner] = []
    table: dict[str, _Inner] = {}
    kind: Literal["a", "b"] = "a"
    path: Path = Path("data/in.csv")
    count: int = 3
    label: str | None = None


@pytest.fixture(autouse=True)
def _fresh_told() -> None:
    forget_old_forms_told()


def test_an_unknown_key_is_refused() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        _Cfg.model_validate({"enginee": "x"})


def test_a_refused_key_names_what_to_write_instead() -> None:
    with pytest.raises(ValidationError, match="'mode' is not accepted any more: use 'engine'"):
        _Cfg.model_validate({"mode": "x"})


def test_a_retired_key_loads_with_a_warning_and_has_no_effect() -> None:
    with pytest.warns(DeprecationWarning, match="'old_flag' is no longer read by _Cfg"):
        cfg = _Cfg.model_validate({"old_flag": 1, "engine": "x"})
    assert cfg.engine == "x"
    assert "old_flag" not in cfg.model_dump()


def test_an_old_spelling_keeps_loading_with_a_warning_naming_both() -> None:
    with pytest.warns(ConfigKeyRenamedWarning, match="'method' is now called 'engine'"):
        assert _Cfg.model_validate({"method": "x"}).engine == "x"


def test_both_spellings_of_one_key_are_refused() -> None:
    with pytest.raises(ValidationError, match="was given both 'method' and 'engine'"):
        _Cfg.model_validate({"method": "x", "engine": "y"})


@pytest.mark.parametrize("quoted", ["true", "yes", "maybe"])
def test_a_quoted_boolean_is_refused_with_the_form_to_write(quoted: str) -> None:
    with pytest.raises(ValidationError, match="is quoted, so it is a string"):
        _Cfg.model_validate({"verbose": quoted})


def test_a_model_without_boolean_fields_accepts_strings_as_before() -> None:
    assert _Inner.model_validate({"depth": "2.5"}).depth == 2.5


def test_a_non_mapping_input_goes_through_the_validators_untouched() -> None:
    instance = _Cfg()
    assert _Cfg.model_validate(instance) == instance


def test_a_computed_field_in_a_dump_is_dropped_on_the_way_back() -> None:
    from pydantic import computed_field

    class _WithComputed(HydroModelBase):
        a: float = 2.0

        @computed_field  # type: ignore[prop-decorator]
        @property
        def double(self) -> float:
            return self.a * 2

    dumped = _WithComputed(a=3).model_dump()
    assert dumped["double"] == 6
    assert _WithComputed.model_validate(dumped).a == 3


def test_a_visible_when_naming_no_sibling_is_refused() -> None:
    class _Bad(HydroModelBase):
        a: Annotated[int, VisibleWhen("ghost", "x")] = 1

    with pytest.raises(ValidationError, match="references unknown sibling 'ghost'"):
        _Bad()


def test_a_visible_when_naming_a_sibling_is_accepted() -> None:
    class _Good(HydroModelBase):
        mode: str = "x"
        a: Annotated[int, VisibleWhen("mode", "x")] = 1

    assert _Good().a == 1


def test_assignment_is_validated() -> None:
    cfg = _Cfg()
    with pytest.raises(ValidationError):
        cfg.count = "many"  # type: ignore[assignment]


def test_a_string_is_stripped_of_surrounding_blanks() -> None:
    assert _Cfg(engine="  grid  ").engine == "grid"


def test_a_frozen_copy_refuses_assignment_at_every_depth_and_equals_the_original() -> None:
    cfg = _Cfg(rows=[_Inner()], table={"a": _Inner()})
    frozen = frozen_copy(cfg)
    assert frozen == cfg
    for target in (frozen, frozen.inner, frozen.rows[0], frozen.table["a"]):
        with pytest.raises(FrozenConfigError, match="frozen copy of the configuration"):
            target.__setattr__("depth" if isinstance(target, _Inner) else "count", 5.0)
    cfg.count = 9
    assert frozen.count == 3


def test_a_thawed_copy_can_be_changed_and_the_frozen_one_stays_as_it_was() -> None:
    frozen = frozen_copy(_Cfg(rows=[_Inner()]))
    thawed = thawed_copy(frozen)
    thawed.count = 7
    thawed.rows[0].depth = 4.0
    assert (frozen.count, frozen.rows[0].depth) == (3, 1.0)
    assert (thawed.count, thawed.rows[0].depth) == (7, 4.0)


def test_thawing_a_model_never_frozen_gives_the_same_object() -> None:
    cfg = _Cfg()
    assert thawed_copy(cfg) is cfg


def test_write_resolved_counts_the_field_as_given() -> None:
    cfg = _Cfg()
    write_resolved(cfg, "count", 11)
    assert cfg.count == 11
    assert "count" in cfg.model_fields_set


def test_the_json_schema_carries_profile_and_examples() -> None:
    props = _Cfg.model_json_schema()["properties"]
    assert props["engine"]["x-hmp-profile"] == "user"
    assert props["engine"]["examples"] == ["grid"]
    assert props["kind"]["examples"] == ["a"]
    assert props["verbose"]["examples"] == [False]
    assert props["count"]["examples"] == [3]
    assert props["path"]["examples"] == ["data/input.csv"]


@pytest.mark.parametrize(
    ("annotation", "default", "expected"),
    [
        (str, ..., ["example"]),
        (int, ..., [1]),
        (float, ..., [1.0]),
        (bool, ..., [False]),
        (Path, ..., ["data/input.csv"]),
        (list[int], ..., None),
    ],
)
def test_an_example_is_invented_from_the_type_when_there_is_no_default(
    annotation, default, expected
) -> None:
    class _M(HydroModelBase):
        x: annotation = Field(default)  # type: ignore[valid-type]

    assert _M.model_json_schema()["properties"]["x"].get("examples") == expected


def test_declared_examples_win_over_invented_ones() -> None:
    class _M(HydroModelBase):
        x: int = Field(default=3, examples=[42])

    assert _M.model_json_schema()["properties"]["x"]["examples"] == [42]


def test_an_enum_field_gets_its_first_member_as_example() -> None:
    from enum import Enum

    class _Color(Enum):
        RED = "red"
        BLUE = "blue"

    class _M(HydroModelBase):
        c: _Color = _Color.BLUE
        d: _Color

    props = _M.model_json_schema()["properties"]
    assert props["d"]["examples"] == ["red"]


def test_old_form_warning_is_given_once_per_file_and_change(tmp_path: Path) -> None:
    where = tmp_path / "a.toml"
    with pytest.warns(ConfigKeyRenamedWarning) as first:
        warn_old_form(where, "a -> b")
    assert f"hmp doctor --fix-config {where}" in str(first[0].message)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        warn_old_form(where, "a -> b")
    forget_old_forms_told()
    with pytest.warns(ConfigKeyRenamedWarning):
        warn_old_form(where, "a -> b")


def test_old_form_warning_of_no_file_is_told_every_time() -> None:
    for _ in range(2):
        with pytest.warns(ConfigKeyRenamedWarning, match=r"^config: a -> b\. .*<file>"):
            warn_old_form(None, "a -> b")


def test_old_form_warning_from_set_tells_to_write_the_new_name() -> None:
    with pytest.warns(ConfigKeyRenamedWarning, match="write the new name") as caught:
        warn_old_form("--set", "a -> b", rewritable=False)
    assert "doctor" not in str(caught[0].message)


def test_a_change_the_migration_could_not_make_is_reported_plainly() -> None:
    with pytest.warns(ConfigKeyRenamedWarning) as caught:
        warn_old_form("f.toml", f"x{CANNOT_REWRITE}y")
    assert str(caught[0].message) == f"f.toml: x{CANNOT_REWRITE}y."


@pytest.mark.parametrize(
    ("source", "rewritable", "tail"),
    [
        ("f.toml", True, "`hmp doctor --fix-config f.toml` rewrites the file."),
        (None, True, "`hmp doctor --fix-config <file>` rewrites the file."),
        ("--set", False, "write the new name."),
    ],
)
def test_old_forms_without_delay_are_refused_with_the_fix(source, rewritable, tail) -> None:
    with pytest.raises(ConfigValidationError, match="a -> b; c -> d") as caught:
        refuse_old_forms(source, ["a -> b", "c -> d"], rewritable=rewritable)
    assert str(caught.value).endswith(f"This old form is refused; {tail}")


def test_the_module_remembers_what_it_told_until_forgotten() -> None:
    with pytest.warns(ConfigKeyRenamedWarning):
        warn_old_form("z.toml", "k")
    assert ("z.toml", "k") in base._OLD_FORMS_TOLD
    forget_old_forms_told()
    assert not base._OLD_FORMS_TOLD


# A string where a boolean belongs is a refusal, not a guess.
#
# TOML has native booleans, so a quoted one is always a mistake. Pydantic's lax
# coercion read ``geotiff = "yes"`` as True and refused ``geotiff = "maybe"``,
# which made one class of typo behave two different ways and let a run silently
# do what the file did not ask for.
#
# The refusal is narrow on purpose: it looks at the model's own fields and fires
# only on a field that accepts nothing but a boolean. Every other coercion the
# configuration surface depends on - pint quantity strings, str to Path, int to
# float - is untouched, which is why ``ConfigDict(strict=True)`` is not the seam.


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
    with pytest.warns(ConfigKeyRenamedWarning):
        with pytest.raises(ValidationError, match="geotiff = 'yes' is quoted"):
            _Toggles.model_validate({"raster": "yes"})


def test_the_other_coercions_are_untouched() -> None:
    kept = _Toggles.model_validate({"label": "run", "dest": "out/fields.nc"})
    assert kept.label == "run"
    assert kept.dest == Path("out/fields.nc")


def test_a_quantity_string_still_parses() -> None:
    assert ConstantThicknessDepthModel.model_validate({"thickness": "30.0 m"}).thickness == 30.0


def test_a_real_section_refuses_a_quoted_switch() -> None:
    with pytest.raises(ValidationError, match="save = 'yes' is quoted"):
        DisplayConfig.model_validate({"save": "yes"})
    assert DisplayConfig.model_validate({"save": True}).save is True
