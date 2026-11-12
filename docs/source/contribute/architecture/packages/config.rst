Package: config
===============

.. include:: ../../../../../hydromodpy/config/README.md
   :parser: myst_parser.sphinx_
   :start-line: 1

Modules
-------

.. hmp-module-table:: config

Inside the package
------------------

How a TOML file becomes a config
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``hmp run file.toml`` calls ``load(path, base)`` of ``loading.py``.

1. ``read_document`` follows the ``base_config`` chain, reads each file once, merges, detects
   cycles, then applies the overlays and the dotted changes. The migration of
   ``config_migration.py`` runs on the document in memory and leaves the file untouched.
2. ``_from_payload`` works on a copy of the document. It resolves the old forms of a key, the
   retired sections, the default ``[workspace]``, the calibration protocol and defaults and the
   gauge.
3. ``validate_sections`` has one loader per section and keeps every fault, with the same walk
   that ``check.py`` uses. The root takes its name from the file name when
   ``[simulation].name`` is empty.
4. Every row of ``CROSS_RULES`` runs once, in the order of the table. The first fault is
   raised, and it carries every diagnostic. A refusal leaves ``_from_payload`` as a
   ``ConfigValidationError`` that names the section, never as a bare Pydantic error.

Relative paths are read from one folder, the base. A file gives its own, the folder that holds
``project.toml`` at or above it, else the folder of the root file of its ``base_config`` chain,
and a ``base=`` given to ``load`` wins. A mapping or JSON text has no folder, so ``load``,
``from_dict``, ``from_json`` and ``check`` refuse it without a base. So a file two folders down,
such as ``plan/<hash>/<case>.toml``, names a ``path`` of ``[data]`` the same way ``project.toml``
does. No environment variable moves the base. ``[workspace].project_root`` is never a key of a
file, because the loader sets it from the base.

A run request in JSON is read by ``project/request.py``, and the runner passes its document to
``load`` with the base it was given. The name of a run is checked when the run takes its folder
(``core/state/names.py``) and never by the configuration.

A document can be checked before it is whole. ``check(document, partial=True)`` gives a
``to_fill`` diagnostic for each required key not written yet. ``partial=False`` turns each
into an error, and a run asks for it.

Each section model is defined in the package it configures. ``HydroModPyConfig`` has one field
per top-level section, and this package holds only ``[workflow]`` (``WorkflowMode``) and
``[sites]``. Each model derives from ``HydroModelBase``, which sets ``extra="forbid"``, so a
typo in a key is refused. Each field has a ``Profile``, a unit alias from ``core/units`` for a
quantity, and a ``Field`` description that becomes its card in the reference.

The solver rows of ``CROSS_RULES`` come after the rules of the data and the soil, and the
rules of the layers and the mesh come after them. A key that the file uses and that the flow
solver leaves out of ``supports`` raises ``IncompatibleCapabilitiesError``, with the solvers
that honour it. On a sealed run the rules that check the run only warn, so an old run still
loads.

Where to add what
~~~~~~~~~~~~~~~~~

- A field in an existing section goes on the model of that section, with a ``Profile``, a unit
  alias for a quantity and a description. The parameter reference follows at the next build,
  and ``tests/unit/docs/test_docs_config_consistency.py`` compares the committed JSON Schema
  with the model. The steps are in :doc:`../how-to/add-a-config-field`.
- A new top-level section is a model in the package it configures, a field on
  ``HydroModPyConfig`` and its row in ``SECTIONS`` of ``section_loader.py``.
- A renamed or moved key is a ``[[migration]]`` row of ``schema/changes.toml``, with a test.
- A retired key is refused by the model with the key to write. A retired section is a row of
  ``RETIRED_SECTIONS``.
- A cross-section rule is one row of ``CROSS_RULES``, only when the rule needs two sections.

Reading path
~~~~~~~~~~~~

Start with ``hydromodpy_config.py``, then ``_from_payload``, then ``check.py``, then
``loading.py`` and ``core/toml_io/loader.py`` for the ``base_config`` chain.
