Package: core
=============

.. include:: ../../../../../hydromodpy/core/README.md
   :parser: myst_parser.sphinx_
   :start-line: 1

Modules
-------

.. hmp-module-table:: core

Inside the package
------------------

Each folder answers one question. ``config_kit`` answers what all config models share,
``toml_io`` how a TOML file is read, merged and written back, ``units`` what unit a number
is in, ``fields`` how a grid or a field array is described in plain words, ``budget`` what
sign a flux has, ``io`` how a file is read, written or fetched the same safe way
everywhere, ``payload`` what a package installs into a workspace, ``runtime`` how the
running process behaves, ``console`` what a run shows while it works, ``contracts`` what
two layers agree on when neither may import the other, ``site`` what a site is,
``state`` and ``workspace`` where things live on disk, ``time`` how a date becomes a
period and ``tracking`` which files a config reads. The layer rules are checked by
``tests/unit/architecture/``, and the unit tests of a folder are in ``tests/unit/core/``.

Configuration. Every config class of every layer inherits ``HydroModelBase`` of
``config_kit/base.py``, which sets ``extra="forbid"`` and ``validate_assignment=True``, so
the strictness is written once. ``profile.py`` and ``visible_when.py`` decide which field
shows in which profile, and a field visibility rule goes there and in ``introspect.py``.
A shared constrained type goes to ``types.py``. ``calibrable.py`` marks a calibrable field
and lives here so that ``model`` and ``calibration`` need not import each other.
``root.py`` holds ``RootConfig``, the root model class with its two migrations. Every
helper that reads sections or migrates a file receives it as its ``root`` argument, which
is how ``core`` reaches the root config without importing ``config``. A section that must
be listed at the root is added to the root model, never to this folder. ``field_param/``
is the schema of a field-parameter payload. It lives here because ``model/properties``
builds the field from it and ``model/flow_config.py`` embeds it in ``[flow.param.<id>]``.
The ``[[export]]`` request is in ``results/exporters/export_spec.py``.

``toml_io`` is the path of a file into a document. The loader follows ``base_config``,
migrates through the ``RootConfig`` it receives, and ``error_locator.py`` points a
Pydantic error at a line of the file. A new merge or override rule goes to ``merge.py`` or
``overrides.py`` with a test of the round trip, and a key that holds a path goes to
``paths.py``. The commented template is generated from the models, and an example block
that the template shows is a function in the layer that owns the section, passed to
``generate_toml`` as ``flow_examples``.

Units and fields. A bare number is read in SI and a string such as ``"0.36 m/h"`` is
converted, with Pint loaded only when needed. A new alias of a config type goes to
``units/types.py`` with its canonical unit, a new physical bound to ``physical_bounds.py``
and a new axis label to ``labels.py``, so no figure writes one. In ``fields``, a new
nodata convention goes to ``nodata.py`` once, and a new way to store a field goes to
``precision.py`` with its error bound. ``budget`` fixes one sign for every solver, the one
MODFLOW gives it: positive when water enters the aquifer, negative when it leaves. A drain
or release key goes to the tuples of ``flux.py``, and a derived field that needs a new term
to the table behind ``budget_terms_for`` in ``terms.py``.

Paths, names and the host. ``state/layout.py`` holds the names under ``.hmp/``, ``runs/``,
``sessions/``, ``jobs/`` and ``trash/``, so a new folder name inside a project goes there
with its ``*_dir_for`` helper. ``workspace/path_registry.py`` holds the canonical paths
that runtime components share under a workspace, and the metadata of a workspace is
``workspace_toml.py``. The workspace is resolved in four steps, from the ``[workspace]``
keys, then ``HMP_WORKSPACE``, then the scaffold ``<workspace>/projects/<name>/``, then the
project folder itself. The folder of a project is never written in a file, because the
loader sets it from where the file sits. A random consumer asks ``RngManager`` of
``state/rng.py`` for its seed, and nothing seeds globally. A host name or the proof that a
process died comes from ``state/host.py``, never from ``socket.gethostname()`` or a pid
test in the caller.

Files. A new file format is one module of ``io`` that writes through ``atomic_replace.py``.
A new stored document takes a ``schema`` id and a check through ``document_version.py``.
A hard link, a test of a path length and a rename onto a reserved folder go through
``filesystem.py``, a DuckDB open through ``db_retry.py`` and never ``duckdb.connect``, and
a lock file that is empty or holds torn JSON for more than five seconds is stale. A package
that installs files into a workspace, whether an example, a published run or an exported
project, writes the same ``INSTALL.toml`` that ``payload/index.py`` reads and writes. The
installer plans every placement before it writes one, so a new placement rule goes to
``payload/install.py``.

The running process. A bound on what one call may reach or take is a member of ``Bounds``
in ``runtime/bounds.py``, and the check that applies it stays with the owner of the
download or the delivery. A new ``HMP_*`` variable is one entry of ``runtime/env.py``, a
new signal rule or a new reader of the stop flag goes to ``interrupts.py``, and a new kind
of timed block goes to ``MEASURE_KINDS``. A module of ``core`` never needs a higher
layer, because it receives what it needs as an argument, and the bounds travel the same
way on the request or the environment object of the call. For progress, a new kind of line
goes to ``console/progress.py`` with its event in ``ndjson.py``, and a new consumer of
the events reads the NDJSON instead of adding a second display. A new protocol between two
layers is one module of ``contracts`` with the concrete class in the layer that owns it,
and real code never goes there.

Sites and time. A new column of the site table goes to ``site/row.py``, and a new site key
to ``site/config.py``, after a check that ``site_fingerprint`` still ignores what must
not change the identity of a site. ``time/selection.py`` is the one resolver from a date to a
period that figures and exports share, and ``time/window.py`` cuts a long run into windows.
