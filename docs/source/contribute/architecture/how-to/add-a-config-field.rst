Add a config field
==================

Every TOML knob in HydroModPy is backed by a Pydantic v2 model that forbids
extra keys. This page covers a field in an existing section, a new section, and
the way to write the field so that the generated parameter reference documents
it. The reference is built from the models alone, so the declaration of the
field is its documentation.

Files to edit
-------------

A section lives in the package it configures. ``SECTIONS`` in
``hydromodpy/config/section_loader.py`` holds one row per section of the root and
names its loader and its model, and ``HydroModPyConfig`` in
``hydromodpy/config/hydromodpy_config.py`` holds the field of each section. Open the
model there and add the field to it.

The settings of a flow solver are not a section of the root. A key of ``[solver]``
that is not one of its own fields names a flow solver, and its table is validated by
the options class that the adapter declares, for example
``hydromodpy/solver/modflow6/modflow6_config.py``. To add a field to such a table,
add it on that class with the same rules. ``SolverConfig.named_tables`` hands these
classes to the schema, the template and the parameter pages, so none of them needs a
line for the new field. A field that every flow solver reads belongs to ``[solver]``
itself. If a solver ignores it, the solver leaves it out of ``supports`` and a file
that sets it is refused when it is read.

A model inherits from ``HydroModelBase``, which forbids extra keys and validates on
assignment. Each field carries a ``Profile`` annotation and a
``Field(..., description="...")``.

The contract of a field
-----------------------

A quantity uses the unit aliases of ``hydromodpy/core/units/types.py`` (``Length``,
``Area``, ``Time``, ``FlowRate``, ``Velocity``, ``HydraulicConductivity``, and so on).
Each one has a canonical SI unit. A bare number in the file is read in that unit, and
a string such as ``"50 m"`` or ``"0.36 m/h"`` is converted.

The profile says who sees the field in the templates, the JSON Schema and the
frontend forms. Use ``Profile.USER`` unless the field is irrelevant to a
hydrogeologist.

.. literalinclude:: /../../hydromodpy/core/config_kit/profile.py
   :pyobject: Profile

The minimal skeleton of a field reads as follows.

.. code-block:: python

   from typing import Annotated
   from pydantic import Field
   from hydromodpy.core.config_kit.profile import Profile
   from hydromodpy.core.units.types import HydraulicConductivity

   class FlowConfig(HydroModelBase):
       k_aquifer: Annotated[HydraulicConductivity, Profile.USER] = Field(
           default=1e-5,
           description="Aquifer hydraulic conductivity (canonical: m/s).",
           examples=[1e-4, "0.36 m/h"],
       )

.. code-block:: toml

   # not checked: k_aquifer is the example of this page, not a key of the model
   [flow]
   k_aquifer = "0.36 m/h"   # converted to m/s

A field that holds a path carries the marker ``InputFile(role=..., category=...,
portable=...)`` of ``hydromodpy/core/tracking/input_file.py`` in its ``Annotated``
metadata. The manifest of a run then lists the file with its canonical path and its
SHA-256.

.. literalinclude:: /../../hydromodpy/core/tracking/input_file.py
   :pyobject: InputFile

Validators
----------

Use ``@field_validator(mode="before")`` to normalize and ``@model_validator(mode="after")``
for a rule between fields of one model. Keep them small.

A rule that reads two sections belongs to neither of them. It is one row of
``CROSS_RULES`` in ``hydromodpy/config/cross_checks.py``, a ``CrossRule`` named by its
function.

.. literalinclude:: /../../hydromodpy/config/cross_checks.py
   :pyobject: CrossRule

The check of an incomplete document runs the rule once every section in ``reads`` is
complete. A test holds ``reads`` equal to what the function reads, so a section
missing from it would let the rule run too early.

Add a new section
-----------------

1. Create the Pydantic model in the package it configures.
2. Add the field to ``HydroModPyConfig``, with a default factory or ``None``, and its
   row in ``SECTIONS``. ``from_toml`` and ``check`` walk that one table.
3. If a launcher dispatches on the section, wire it in
   ``hydromodpy/project/dispatch/workflow.py``.
4. Regenerate the committed JSON Schema with ``python -m tools.docs.schema_export``.
   ``tests/unit/docs/test_docs_config_consistency.py`` fails while the file in
   ``docs/source/_static/`` differs from what the code exports.

Describe the field
------------------

The parameter reference is generated from the models, so nothing is written on a
page. Change the field and the next build shows the change wherever the key appears.
The table says what the reference reads from a declaration.

.. list-table::
   :header-rows: 1
   :widths: 38 62

   * - The reader sees
     - It comes from
   * - The path of the key
     - The model tree under ``HydroModPyConfig``.
   * - The summary line, and the text of the card
     - The first sentence of ``description``, and the whole ``description``.
   * - The unit
     - A quantity type, else ``field_metadata(unit=...)``, else
       ``Calibrable(units=...)``, else a suffix of the name such as ``_m``.
   * - The default, or *required*
     - ``default``, ``default_factory``, or no default.
   * - The range, the allowed values
     - ``ge``, ``gt``, ``le``, ``lt``, and ``Literal[...]``.
   * - What each value does
     - ``field_metadata(value_docs={...})``.
   * - The value on a required line
     - The first item of ``Field(examples=[...])``.
   * - Shown by default, or behind the developer and expert button
     - The ``Profile`` in the annotation.
   * - When the key is read
     - ``VisibleWhen("sibling", value)`` in the annotation.
   * - The *calibrable* badge and its search space
     - ``field_metadata(calibrable=Calibrable(...))``.
   * - The *experimental* and *deprecated* badges
     - ``field_metadata(stability="experimental")`` and ``Field(deprecated=...)``.

``field_metadata`` lives in ``hydromodpy/core/config_kit/field_metadata.py``. It
refuses an unknown key at import, so a typo fails the tests and not the page.

The first sentence of the description is the summary. It shows on the line of the
key, in the tree of the whole file and in the search. Make it say what the key sets,
in the words of the person who writes the file. The conditions and the exceptions
come after it.

Rules for the values:

- A choice between values is a ``Literal``, and every value is explained in
  ``value_docs``. The search finds a key by the name of one of its values.
- A number has a unit.
- A key read only in some cases says so with ``VisibleWhen``, so the card shows the
  condition on its own line.
- A required key with no default has an example in ``Field(examples=[...])``. Never
  take it from an example project.

Build the documentation (``make -C docs html-strict``) to check the page of the
section. The build fails on a cited key that does not exist. The tree of the whole
file, :doc:`/reference/parameters/explorer`, shows the key in context.

Test
----

- A unit test under ``tests/unit/config/`` for the accept and reject cases: extra
  keys refused, units parsed, validators raised on bad combinations.
- An integration test if the field changes the dispatched workflow.

``hmp check <toml>`` validates a candidate file against the model. It lists every
fault at once, and ``--partial`` accepts a file that still lacks required keys.

Rename, move or remove a key
----------------------------

A stable key leaves under the rules of :doc:`/about/versions`, so it keeps loading for
two minor versions. In one change:

1. Add a ``[[migration]]`` row of ``document = "config"`` to
   ``hydromodpy/schema/changes.toml``. Use ``old`` and ``new`` for a key or a table
   that moves, ``key``, ``old_value`` and ``new_value`` for a value that takes another
   name, or ``old`` and ``instead`` for a key that leaves. ``since`` is the version
   that ships the change. Add ``rule`` when the row cannot say the whole change. It
   names a function of ``RULES`` in ``hydromodpy/config/config_migration.py``. A load
   then reads the old name with a warning, and ``hmp doctor --fix-config`` rewrites the
   file and the files it inherits. The same row also covers the dotted paths that name
   the key, such as the ``overrides`` of a calibration phase, ``--set``, ``HMP_SET_*``
   and the keys of ``[sites.bind]``. A figure option is a row with the scope
   ``display.overrides.{*}``.
2. List the old key in the ``model_refused_keys`` of the model, so a config built in
   Python is told what to write. Under ``[calibration]``, ``renamed_to(old, new,
   meaning)`` of ``hydromodpy/calibration/config_terms.py`` writes that sentence.
3. Name the old path in ``renamed_from`` on the new field, so the changes page lists
   the rename.
4. Run ``python -m tools.surface_snapshot``. It refuses a removed stable key that has
   no such row, and it records the key in ``removed_toml_keys.tsv``.
5. Write the old and the new name under ``Changed`` in the changelog.

``tests/unit/config/test_historical_configs.py`` reads real files of the published
alphas from ``tests/unit/config/corpus/``, so a rename with no row fails there.

A row stays in the register after its delay, which ends when the version of the
package reaches ``since`` plus two minor versions. From then on a live file is refused
with the new name, and a run sealed under the old name stays readable for the whole
major line.

Layer boundaries
----------------

The model lives in the layer of the package it configures. Only ``config``,
``workflow``, ``project`` and ``cli`` import ``config``, and ``schema`` and ``results``
never read it. The full rules are on :doc:`../generated/layers`.

See also
--------

- :doc:`../packages/config` for the configuration root.
- :doc:`../packages/core` for ``Profile``, units, and tracking helpers.
- :doc:`build-a-frontend` if the field powers a UI widget.
- :doc:`/reference/parameters/index` for the generated TOML reference.
