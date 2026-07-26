hmp workspace
=============

The :command:`hmp workspace` family handles the lifecycle of the workspace
that hosts the shared input-data cache and the projects. A workspace is the
parent directory of ``projects/`` and ``data/``. The same family also
operates the machine-wide index that federates workspaces.

The default workspace path is ``~/hydromodpy/``.

init
----

Synopsis: ``hmp workspace init [<path>] [--force] [--project-name NAME]
[--creator-name NAME] [--creator-email MAIL]``

Scaffold a workspace at the given path (default: ``~/hydromodpy/``). It
writes ``workspace.toml``, one ``data/<variable>/`` folder per supported
variable with a README and example files, and a ready-to-run
``projects/example/``. The new workspace is registered in the machine-wide
index. ``--force`` overwrites an existing scaffold.

Example::

   hmp workspace init ~/hmp-runs

list
----

Synopsis: ``hmp workspace list [--json]``

Print every workspace registered in the machine-wide index. Registrations
whose index database is missing are skipped with a warning; drop them with
``prune``.

register / forget / prune
-------------------------

Synopsis: ``hmp workspace register <workspace_uri> [--label L]`` /
``hmp workspace forget <workspace_id>`` / ``hmp workspace prune``

Add, remove, or clean up entries of the machine-wide index. ``forget``
removes the registration only; the files stay untouched. ``prune`` drops
every registration whose index database no longer exists.

search
------

Synopsis: ``hmp workspace search <term> [--limit N]``

Full-text search across every registered workspace, for cross-workspace
discovery when a run name is all you remember.

clean
-----

Synopsis: ``hmp workspace clean [--workspace <path>] [--all] [--results]
[--data-cache] [--runtime] [--share] [--scratch] [--figures] [--dry-run]
[-y]``

Delete generated artefacts, per category. This is a destructive command:

- ``--results``: the ``runs/`` tree and the index database, for every
  project of the workspace;
- ``--data-cache``: ``data/cache.duckdb`` and ``data/blobs/``;
- ``--runtime``: the whole ``.hmp/`` internals tree;
- ``--share``: the published ``share/`` tree;
- ``--scratch``: ``.hmp/scratch`` only;
- ``--figures``: ``share/figures`` only;
- ``--all``: every category above.

Always start with ``--dry-run``: it lists the exact paths that would be
deleted and touches nothing. Deletion needs ``-y``/``--yes``.

Example::

   hmp workspace clean --workspace . --all --dry-run
