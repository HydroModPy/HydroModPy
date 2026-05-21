hmp workspace
=============

The :command:`hmp workspace` family handles the lifecycle of the data
workspace that hosts projects, catalogs, and shared caches. A workspace
is the parent directory of ``projects/`` (and typically of ``data/``).

init
----

Synopsis: ``hmp workspace init [<path>]``

Scaffold a fresh HydroModPy workspace at the given path (default:
current directory). The action creates the ``projects/`` and ``data/``
subtrees and registers the new workspace in the machine-wide index so
:command:`hmp workspace list` can find it later.

Example::

   hmp workspace init ~/hmp-runs

list
----

Synopsis: ``hmp workspace list``

Print every workspace registered in the global index, with its root
path and the count of projects it contains. Useful when juggling
several workspaces on the same machine.

Example::

   hmp workspace list

clean
-----

Synopsis: ``hmp workspace clean [--dry-run]``

Remove generated workspace artefacts (build caches, render outputs,
stale figure folders) while keeping the catalog and the source TOML
files intact. ``--dry-run`` prints the planned deletions without
touching the disk; this is the safest first pass before a real run.

Example::

   hmp workspace clean --dry-run
