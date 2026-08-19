hmp workspace
=============

The :command:`hmp workspace` family handles the lifecycle of the workspace
that hosts the shared input-data cache and the projects. A workspace is the
parent directory of ``projects/`` and ``data/``. The same family also
operates the machine-wide index that federates projects.

The index registers **projects**, not workspaces: one row per project root,
because a project root is what owns an index database at
``.hmp/index.duckdb``. A workspace root holds no index of its own, so passing
one to ``register`` expands it into the project roots it contains.

The default workspace path is ``~/hydromodpy/``.

init
----

Synopsis: ``hmp workspace init [<path>] [--path PATH] [--force]
[--project-name NAME] [--creator-name NAME] [--creator-email MAIL]``

Scaffold a workspace at the given path (default: ``~/hydromodpy/``). The path
is a positional; ``--path`` is the equivalent flag form. It writes
``workspace.toml``, one ``data/<variable>/`` folder per supported variable
with a README and example files, and a ready-to-run ``projects/example/``.
The projects of the new workspace are registered in the machine-wide index.
``--force`` overwrites an existing scaffold.

Example::

   hmp workspace init ~/hmp-runs

list
----

Synopsis: ``hmp workspace list [--json]``

Print every project registered in the machine-wide index, with its
``project_id``, label, ``project_uri`` and timestamps. Registrations whose
index database is missing are skipped with a warning; drop them with
``prune``.

register / forget / prune
-------------------------

Synopsis: ``hmp workspace register <root_uri> [--label L]`` /
``hmp workspace forget <project_id>`` / ``hmp workspace prune``

Add, remove, or clean up entries of the machine-wide index. ``root_uri`` is a
project root, or a workspace root that expands into the projects it holds; a
path or a ``file://`` URI. It prints one ``project_id`` per row added, and
says so when everything was already registered. ``forget`` takes the
``project_id`` shown by ``list`` and removes the registration only; the files
stay untouched. ``prune`` drops every registration whose project index
database no longer exists.

Example::

   hmp workspace register ~/hmp-runs --label field-campaign
   hmp workspace register ~/hmp-runs/projects/naizin

search
------

Synopsis: ``hmp workspace search <term> [--limit N]``

Full-text search across every registered project, for cross-project discovery
when a run name is all you remember.

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
