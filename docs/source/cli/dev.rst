hmp dev
=======

The :command:`hmp dev` family groups developer-only commands: shell
completion, schema export, lockfile management, configuration tooling,
ranking, and the prototype script runner. Stability is best-effort;
flags can change between minor releases.

run-script
----------

Synopsis: ``hmp dev run-script <path> [-- <script_args>...]``

Execute a Python prototype script outside the stable :command:`hmp run`
contract. Forwards every argument after ``--`` to the script untouched.
Useful for one-off experiments that do not warrant a TOML.

Example::

   hmp dev run-script tools/inspect_zarr.py -- --sim 1a2b3c4d

completion
----------

Synopsis: ``hmp dev completion {bash|zsh|fish}``

Emit a shell completion script on stdout. See :doc:`completion` for
the installation snippets.

schema
------

Synopsis: ``hmp dev schema {export|validate-field} [...]``

Export the JSON Schema for :class:`HydroModPyConfig` (consumed by any
frontend hook) or validate a single field value
against its declared type. The exported schema is the canonical
contract between the Python core and external tooling.

lock
----

Synopsis: ``hmp dev lock {update|archive|restore|verify}``

Manage the reproducible data lockfile (``hydromodpy.lock``). ``update``
rescans the cache, ``archive`` snapshots the current lock,
``restore`` reverts to an archived snapshot, ``verify`` checks the
recorded hashes against the on-disk artefacts.

config
------

Moved to the top level: use ``hmp config {template|check|schema|wizard}``
(configuration authoring is an end-user task, not a developer-only one).

rank
----

Synopsis: ``hmp dev rank <project> [--metric <name>] [--top <n>]
[--bottom <n>] [--workspace <path>]``

Rank the runs of a project by a metric (default: ``nse``) and print the top
or bottom N rows.

.. warning::

   This verb currently fails with a DuckDB binder error on every project.
   Use the ``@best:METRIC`` / ``@worst:METRIC`` selectors of
   :doc:`hmp catalog show <catalog>`, or ``Catalog.rank`` from Python,
   until it is fixed.

manage
------

Synopsis: ``hmp dev manage [--workspace <path>] [--scan-root <path>]
[--host <host>] [--port <port>] [--no-browser]``

Launch a local browser UI for workspace inspection and cleanup. Kept
as-is from the legacy interface; will be folded into :command:`hmp viz`
during a later iteration.
