hmp project
===========

The :command:`hmp project` family manages the lifecycle of projects inside
a workspace. A project owns its configurations, its runs, its calibration
sessions and the index over them. Every action auto-detects the enclosing
workspace; pass ``--workspace`` to override it.

new
---

Synopsis: ``hmp project new <name> [--workspace <path>]``

Scaffold a project directory under ``projects/`` of the active workspace.
It writes three files and nothing else:

- ``project.toml``, the shared settings, which is also the marker that
  anchors the project root;
- ``run_demo.toml``, an executable run inheriting from it through
  ``base_config = "project.toml"``;
- ``.gitignore``, excluding ``runs/``, ``sessions/``, ``share/`` and
  ``.hmp/``.

No index database is created: the first run creates ``.hmp/index.duckdb``.

Example::

   hmp project new sample-catchment

list
----

Synopsis: ``hmp project list [--workspace <path>]``

List every project directory found under ``projects/``, reporting whether
``project.toml`` is present and how many run configs it holds.

Example::

   hmp project list

show
----

Synopsis: ``hmp project show <name> [--workspace <path>]``

Print a single-project summary: the project path, the presence of
``project.toml``, the run TOMLs, and the runs recorded in the index with
their short id, solver and status. Use it before
:command:`hmp project delete` to confirm what will be removed.

Example::

   hmp project show sample-catchment

delete
------

Synopsis: ``hmp project delete <name> [-w <path>] [-y]``

Remove the whole ``projects/<name>/`` directory, TOMLs included, and report
the bytes freed. Outside a TTY the action refuses to proceed without
``-y``/``--yes`` so that scripts do not silently wipe data.

Example::

   hmp project delete sample-catchment -y
