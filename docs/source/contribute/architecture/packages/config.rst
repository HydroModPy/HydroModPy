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

How a TOML file becomes a config. ``hmp run file.toml`` calls ``load(path, base)`` of
``loading.py``. ``read_document`` follows the ``base_config`` chain, reads each file once,
merges, detects cycles, then applies the overlays and the dotted changes. The migration of
``config_migration.py`` runs on the document in memory and leaves the file untouched. If a
profile was asked for, a field above it warns. Then ``_from_payload`` works on a copy of
the document. It resolves the old forms of a key, the retired sections, ``[workspace]`` by
default, the calibration protocol and defaults and the gauge. ``validate_sections`` has one
loader per section and keeps every fault, with the same walk that ``check.py`` uses. The
root takes its name from the file name when ``[simulation].name`` is empty. Every row of
``CROSS_RULES`` runs once, in the order of the table. The first fault is raised, with the
type and the exit code of today, and it carries every diagnostic. A refusal leaves
``_from_payload`` as a ``ConfigValidationError`` that names the section, so it is never a
bare Pydantic error.

Relative paths are read from one folder, the base. A file gives its own, the folder that
holds ``project.toml`` at or above it, else the folder of the root file of its
``base_config`` chain, and a ``base=`` given to ``load`` wins. A mapping or JSON text has
no folder, so ``load``, ``from_dict``, ``from_json`` and ``check`` refuse it without a base
and never read the current folder. Every relative path of every file of a project reads
from that folder, whether it is ``plan/<hash>/<case>.toml``, ``runs/<case>/config.toml`` or
``site_overrides/<site>.toml``, so a file two folders down names the same ``path`` of a
``source = "file"`` entry of ``[data]`` as ``project.toml`` does. No environment variable
moves the base. ``[workspace].project_root`` is never a key of a file or of a mapping,
because the loader sets it from the base.

A run request in JSON is not read here. ``project/request.py`` holds ``RunRequest``, which
carries the document under ``config``, and the runner passes that document to ``load`` with
the base it was given. The name of a run is checked when the run takes its folder
(``core/state/names.py``) and never by the configuration, so a file with a long or
capitalised ``[simulation] name`` still loads. A name made from a file name is folded to
lower case, and the run is refused when that name is still too long or reserved.

A document can be checked before it is whole. ``check(document, partial=True)`` gives a
``to_fill`` diagnostic for each required key not written yet, and runs a rule across
sections once every section it reads is complete. ``partial=False`` turns each ``to_fill``
into an error and changes nothing else, and it is what a run asks for.

The sections. ``HydroModPyConfig`` has one field per top-level TOML section, and
``workflow``, ``workspace`` and ``geographic`` are required. Each section model is defined
in the package it configures. ``core`` holds ``[workspace]`` and ``[site]``, ``catchment``
``[geographic]``, ``model`` ``[domain]``, ``[flow]``, ``[transport]`` and ``[spinup]``,
``data`` ``[data]``, ``mesh`` ``[mesh]``, ``solver`` ``[simulation]``, ``[solver]`` and
``[observation]``, ``results`` ``[[export]]``, ``[metrics]`` and ``[publication]``,
``calibration`` ``[calibration]`` and ``display`` ``[display]`` and ``[overview]``. This
package holds ``[workflow]`` in ``hydromodpy_config.py`` and ``[sites]`` in ``sites.py``.
``[solver]`` has one settings table per flow solver, such as ``[solver.modflow6]``, each
checked by the ``options`` class of that solver. ``[workflow].mode`` is one of
``simulation``, ``calibration`` and ``overview`` (``WorkflowMode``). A project in
``[sites]`` takes the site of each case from its table row, so ``[site]`` and ``[sites]``
never coexist. The parameter reference of the docs is built from these models.

Each section model derives from ``HydroModelBase``, which sets ``extra="forbid"`` and
``validate_assignment=True``, so a typo in a key is refused. Each field is annotated with a
``Profile`` and, for a physical quantity, with a unit alias of ``core/units``. Each field
has a ``Field`` description, which is the text of its card in the reference.

Cross-section rules. Beside the solver rows, the rows of ``CROSS_RULES`` refuse these
cases. ``data.inference_mode = "strict"`` needs a non-empty :toml:`data.types`. A
:toml:`domain.depth_model` of a raster kind needs ``[data.substratum]`` to be declared. A
declared ``[data.soil_capacity]`` needs ``[flow.sinks_sources.recharge.soil]``, and that
soil reservoir is checked against what it reads and where it runs: the precipitation and
ETP sections it needs, no loaded ``recharge`` or ``runoff``, a declared
``[simulation.time]`` and its spin-up. ``[calibration]`` needs a non-empty
:toml:`flow.param_list`. The solver rows come after those, and the rules of the soil
reservoir, the layers and the mesh after them. Every key that the file uses and that the
flow solver leaves out of ``supports`` raises ``IncompatibleCapabilitiesError``, with the
key the file wrote and the solvers that honour it. A transport solver whose ``requires``
does not name the flow solver is refused, and so are the pairs of ``CONTAMINATIONS``, such
as a lake with a ``spinup_cyclic`` start. On a sealed run the rules that check the run only
warn, which is the case of the solver rows, of the window of ``[metrics]`` and of the two
export rows.

Where to add what. A field in an existing section goes on the model of that section, with
a ``Profile``, a unit alias when it is a quantity and a description. The parameter
reference is computed from the model at the next documentation build, and
``tests/unit/docs/test_docs_config_consistency.py`` compares the committed JSON Schema
``docs/source/_static/hydromodpy-schema.json`` with the model. The steps are in
:doc:`../how-to/add-a-config-field`. A new top-level section is a model in the package it
configures, a field on ``HydroModPyConfig`` and its row in ``SECTIONS``. A renamed or
moved key is a ``[[migration]]`` row of ``schema/changes.toml``, with a test, so that earlier
files still load. A row names a function of ``RULES`` only when it cannot say the whole
change. A retired key is refused by the model with the key to write, and no migration
carries it. A retired section is one row of ``RETIRED_SECTIONS`` with the sentence that
names the replacement. A cross-section rule is one row of ``CROSS_RULES`` with the sections
it reads, only when the rule needs two sections.

Reading path. Start with the fields of the root in ``hydromodpy_config.py``, then
``_from_payload``, then ``check.py``, which walks the same sections. Read ``loading.py``
and then ``core/toml_io/loader.py`` for the ``base_config`` chain, then
``core/config_kit/profile.py`` and ``introspect.py`` for the visibility model, then one
section model such as ``model/flow_config.py``, and last ``schema/config_schema.py`` for
what is exported to front ends and editors.
