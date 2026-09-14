"""The annotation had no reachable field to sit on, so it annotated nothing.

``Calibrable`` and the walk that collects it were written, tested, and returned an
empty dictionary on every configuration in the repository. The reason was a layer
rule, not an oversight: the annotation lived in ``calibration/``, which ``physics``
and ``spatial`` are forbidden to import, so no hydraulic property could carry it.

Moved into the kernel, any layer that declares a field can say what a search
would need to know about it. The scalar value of a homogeneous field parameter is
the first and most obvious one: it is the target every calibration in the
repository writes to.
"""

from __future__ import annotations

from hydromodpy.calibration.optim.parameters import discover_calibrable
from hydromodpy.core.config_kit.calibrable import Calibrable
from hydromodpy.spatial.field.core._field_param_sections import FieldHomogeneousSection


def _annotation(model: type, field: str) -> Calibrable | None:
    extra = model.model_fields[field].json_schema_extra or {}
    found = extra.get("calibrable") if isinstance(extra, dict) else None
    return found if isinstance(found, Calibrable) else None


class TestTheAnnotationIsReachable:
    def test_it_lives_in_the_kernel(self) -> None:
        """So physics and spatial can carry it without breaking the layer matrix."""
        assert Calibrable.__module__ == "hydromodpy.core.config_kit.calibrable"

    def test_there_is_one_class_and_not_two(self) -> None:
        from hydromodpy.calibration import Calibrable as reexported

        assert reexported is Calibrable


class TestWhatIsAnnotated:
    def test_a_homogeneous_field_value_declares_itself(self) -> None:
        found = _annotation(FieldHomogeneousSection, "value")

        assert found is not None

    def test_it_declares_the_space_to_search_in(self) -> None:
        found = _annotation(FieldHomogeneousSection, "value")

        assert found is not None
        assert found.transform == "log"
        assert found.prior == "log_uniform"

    def test_it_leaves_the_range_to_the_site(self) -> None:
        """A conductivity range is a property of the catchment, not of the schema."""
        found = _annotation(FieldHomogeneousSection, "value")

        assert found is not None
        assert found.bounds is None

    def test_the_walk_now_finds_it(self) -> None:
        found = discover_calibrable(FieldHomogeneousSection)

        assert "value" in found
        assert isinstance(found["value"], Calibrable)

    def test_the_walk_reaches_it_through_a_flow_parameter(self) -> None:
        from hydromodpy.physics.flow.flow_param_config import FlowParam

        found = discover_calibrable(FlowParam)

        assert any(path.endswith("value") for path in found), sorted(found)
