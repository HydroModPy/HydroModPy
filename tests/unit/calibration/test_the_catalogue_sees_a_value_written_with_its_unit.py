"""A field value can be written two ways in TOML, and the catalogue sees only one.

``[flow.param.K.field] value = 1e-4`` with a sibling ``unit = "m/s"`` and
``value = "1e-4 m/s"`` in one string are the same declaration. A hydrogeologist
reads both the same way; the catalogue does not.

``_is_a_physical_number`` in ``hydromodpy/calibration/targets.py`` requires
``isinstance(value, Real)``, so a string value is filtered out of the walk
before it ever gets a name. Nothing coerces it earlier:
``_validate_value`` in ``hydromodpy/spatial/field/core/_field_param_sections.py``
keeps a string value as a string, unlike ``_coerce_boundary_value_and_units``
in ``hydromodpy/physics/flow/boundary_conditions.py`` (used for
``[flow.bc.<id>]``), which already splits a string into a float plus its unit
before Pydantic sees it as the ``value`` field.

Concretely: ``examples/projects/01_calibration/project.toml`` writes
``value = "1e-4 m/s"`` under ``[flow.param.K.field]``, so its ``K`` cannot be
named ``[calibration.parameters.K]`` at all today, while the very same
spelling under ``[flow.bc.east_side]`` is coerced and does get a target.

Investigation for this test (readers of a homogeneous field's ``.value``
across ``hydromodpy/``, and whether each survives ``.value`` becoming a plain
float with the unit moved to the sibling ``unit``):

- ``hydromodpy/spatial/field/core/field_param_config.py:94-100``
  (``FieldParamConfig._enforce_physical_bounds``). Today it only runs
  ``validate_physical_value`` when ``self.field.value`` is already
  ``(int, float)`` and skips the check for a string, by its own admission
  ("string payloads carry their own unit and are handled by lower-level unit
  resolution"). Coercion survives this reader: it simply starts validating
  what used to be silently skipped.

- ``hydromodpy/spatial/field/core/field_param.py`` (``FieldParam.__init__`` ->
  ``_convert_scalar_payload_to_si``, ~L204-230) via
  ``hydromodpy/core/units/scalar.py:parse_scalar_and_unit``. This is the
  terminal reader that turns a field into SI values for the solver. It
  already accepts either a bare number or a ``"<number> <unit>"`` string
  (``parse_scalar_and_unit`` documents both forms), so it survives unchanged
  either way; the fix would only make its input always the bare-number branch.

- ``hydromodpy/spatial/field/core/_field_param_resolved.py:80-91``
  (``ResolvedFieldParam._validate_value``). An exact duplicate of the
  section validator above, reached through a *second*, independent
  production entry point:
  ``hydromodpy/spatial/field/core/field_param_io.py`` builds its merged
  payload straight from a raw TOML section mapping and calls
  ``validate_resolved_field_param_data`` directly, without ever going
  through ``FieldHomogeneousSection`` / ``_field_param_sections.py``. That
  path is used by the mesh/geology demo cases
  (``hydromodpy/spatial/field/cases/review_cases.py``,
  ``hydromodpy/spatial/mesh/*/examples/*``, ``.../cases/*``), not by the
  project ``[flow.param.*]`` pipeline the calibration catalogue walks, so it
  does not affect the catalogue either way. But fixing only
  ``_field_param_sections.py`` would leave this duplicate validator
  accepting an un-coerced string, i.e. the asymmetry would move one level
  down instead of closing. Coercing survives this reader (it never sees a
  string it didn't already accept), but a full fix costs a second file, kept
  in lockstep with the first.

- ``hydromodpy/calibration/optim/parameters.py:377-395``
  (``_apply_resolved`` / ``set_by_path`` / ``_get_by_path``), used by the
  legacy path-based ``[calibration.parameters.<name>] path = "..."`` form.
  ``mode="replace"`` always ``setattr``s a plain ``float(value)``: it
  survives regardless of ``.value``'s prior type. ``mode="scale"`` reads the
  current value with ``_get_by_path`` and calls ``float(base)`` on it: today
  this *already breaks* for a string field ("1e-4 m/s") --
  ``float("1e-4 m/s")`` raises and the calibration setup fails with "requires
  a numeric base value ... got '1e-4 m/s'". Coercing ``.value`` to a plain
  float fixes this latent bug as a side effect, it does not create a new one.

- ``hydromodpy/config/dynamic_flow_examples.py`` renders TOML examples for
  ``[flow.param.<id>.field]`` but never sets a ``value`` key, so it is
  unaffected either way.

No reader was found that requires ``.value`` to stay a string (no
``.split()``, no ``isinstance(..., str)`` branch whose *absence* would raise,
no string-specific formatting). The only cost of coercing is the duplicate
validator in ``_field_param_resolved.py``, and coercing also fixes an
existing crash in scale-mode calibration through the legacy path form.

Decision applied: both validators now coerce ``value = "<number> <unit>"``
into a plain float, filling a missing sibling ``unit`` or refusing one that
disagrees, through the shared ``coerce_scalar_value_with_unit`` helper (which
itself reuses ``parse_scalar_and_unit``, the same primitive
``boundary_conditions.py`` builds on for ``[flow.bc.*]``).
"""

from __future__ import annotations

import pytest

from hydromodpy.calibration.targets import calibration_targets, targets_by_path
from hydromodpy.core.workspace.config import WorkspaceConfig
from hydromodpy.physics.flow.flow_config import FlowConfig
from hydromodpy.spatial.geographic.geographic_config import GeographicConfig


def _config(tmp_path, **flow: object):
    from hydromodpy.config import HydroModPyConfig

    return HydroModPyConfig(
        workflow={"mode": "simulation"},
        workspace=WorkspaceConfig(project_root=str(tmp_path), root=str(tmp_path)),
        geographic=GeographicConfig(source_mode="synthetic"),
        flow=FlowConfig(**flow),
    )


def _config_with_k_written_as(tmp_path, *, value: object, unit: str | None = None):
    field: dict[str, object] = {"id": "K", "kind": "homogeneous", "value": value}
    if unit is not None:
        field["unit"] = unit
    return _config(
        tmp_path,
        param_list=["K"],
        param={"K": {"field": field}},
    )


class TestTheNumericFormIsSeen:
    """The control case: number plus sibling unit, the form the catalogue supports."""

    def test_a_number_with_a_sibling_unit_reaches_the_catalogue(self, tmp_path) -> None:
        cfg = _config_with_k_written_as(tmp_path, value=1e-4, unit="m/s")

        found = targets_by_path(calibration_targets(cfg))

        assert "flow.param.K.field.value" in found
        assert found["flow.param.K.field.value"].current == pytest.approx(1e-4)


class TestTheStringFormIsInvisible:
    """The former asymmetry: same physical declaration, one string away, now closed."""

    def test_a_number_with_its_unit_in_one_string_also_reaches_the_catalogue(
        self, tmp_path
    ) -> None:
        cfg = _config_with_k_written_as(tmp_path, value="1e-4 m/s")

        found = targets_by_path(calibration_targets(cfg))

        assert "flow.param.K.field.value" in found
        assert found["flow.param.K.field.value"].current == pytest.approx(1e-4)

    def test_the_string_form_fills_a_missing_sibling_unit(self, tmp_path) -> None:
        cfg = _config_with_k_written_as(tmp_path, value="1e-4 m/s")

        field = cfg.flow.param["K"].field
        assert field.value == pytest.approx(1e-4)
        assert field.unit == "m/s"


class TestAConflictingUnitIsRefused:
    """Two answers to one question: the schema must pick neither, and raise."""

    def test_a_string_unit_contradicting_the_sibling_unit_is_refused(self, tmp_path) -> None:
        with pytest.raises(Exception, match="conflict"):
            _config_with_k_written_as(tmp_path, value="1e-4 m/s", unit="m/day")
