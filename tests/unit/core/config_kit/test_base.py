"""The base class of every configuration model: refused keys, quoted booleans, frozen copies."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

import pytest
from pydantic import Field, PrivateAttr, ValidationError

from hydromodpy.core.config_kit.base import (
    CANNOT_REWRITE,
    ConfigKeyRenamedWarning,
    HydroModelBase,
    frozen_copy,
    thawed_copy,
    warn_old_form,
)
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.config_kit.visible_when import VisibleWhen
from hydromodpy.core.exceptions import FrozenConfigError


class _Inner(HydroModelBase):
    depth: float = 1.0


class _Cfg(HydroModelBase):
    model_refused_keys = {"mode": "use 'engine' instead"}

    engine: str = "grid"
    verbose: bool = False
    inner: _Inner = _Inner()
    rows: list[_Inner] = []
    table: dict[str, _Inner] = {}
    kind: Literal["a", "b"] = "a"
    path: Path = Path("data/in.csv")
    count: int = 3
    label: str | None = None


# A key the model does not hold is refused, whether it is a typo, a key the model dropped
# or an old spelling of a key. A pre-release spelling is refused earlier, by the loader of a
# file, with the sentence that names every such key.


def test_a_visible_when_naming_no_sibling_is_refused() -> None:
    class _Bad(HydroModelBase):
        a: Annotated[int, VisibleWhen("ghost", "x")] = 1

    with pytest.raises(ValidationError, match="references unknown sibling 'ghost'"):
        _Bad()


def test_assignment_is_validated() -> None:
    cfg = _Cfg()
    with pytest.raises(ValidationError):
        cfg.count = "many"  # type: ignore[assignment]


def test_a_frozen_copy_refuses_assignment_at_every_depth_and_equals_the_original() -> None:
    cfg = _Cfg(rows=[_Inner()], table={"a": _Inner()})
    frozen = frozen_copy(cfg)
    assert frozen == cfg
    for target in (frozen, frozen.inner, frozen.rows[0], frozen.table["a"]):
        with pytest.raises(FrozenConfigError, match="frozen copy of the configuration"):
            target.__setattr__("depth" if isinstance(target, _Inner) else "count", 5.0)
    cfg.count = 9
    assert frozen.count == 3


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


def test_a_change_the_migration_could_not_make_is_reported_plainly() -> None:
    with pytest.warns(ConfigKeyRenamedWarning) as caught:
        warn_old_form("f.toml", f"x{CANNOT_REWRITE}y")
    assert str(caught[0].message) == f"f.toml: x{CANNOT_REWRITE}y."


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

    geotiff: bool = Field(default=False, description="Plain boolean.")
    optional: bool | None = Field(default=None, description="Boolean or nothing.")
    tagged: Annotated[bool, Profile.EXPERT] = Field(default=False, description="Tagged boolean.")
    profile: bool | str = Field(default=False, description="Boolean, or a report path.")
    label: str = Field(default="", description="A string field.")
    dest: Path | None = Field(default=None, description="A path field.")


# Named tables: frozen with their section, and listed in its schema ---------------


class _Table(HydroModelBase):
    """Settings of one plugin."""

    steps: Annotated[int, Profile.EXPERT] = 4


class _Section(HydroModelBase):
    name: str = "x"
    _tables: dict[str, _Table] = PrivateAttr(default_factory=lambda: {"plugin": _Table()})

    @classmethod
    def named_tables(cls, *, shipped_only: bool) -> dict[str, type[HydroModelBase]]:
        return {"plugin": _Table}

    def held_tables(self) -> dict[str, _Table]:
        return self._tables


def test_a_frozen_copy_freezes_the_named_tables_of_a_section() -> None:
    frozen = frozen_copy(_Section())

    with pytest.raises(FrozenConfigError):
        frozen.held_tables()["plugin"].steps = 8
    assert thawed_copy(frozen).held_tables()["plugin"].steps == 4
