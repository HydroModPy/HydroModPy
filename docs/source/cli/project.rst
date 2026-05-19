hmp project
===========

The :command:`hmp project` family manages the lifecycle of projects
inside a workspace. A project owns its catalog rows, its simulation
artefacts, and its TOML configurations. Every action below auto-detects
the enclosing workspace; pass ``--workspace`` to override it.

new
---

Synopsis: ``hmp project new <name> [--workspace <path>]``

Scaffold a new project directory under ``projects/`` of the active
workspace. The action creates the catalog skeleton and a starter TOML
suitable for :command:`hmp run`.

Example::

   hmp project new sample-catchment

list
----

Synopsis: ``hmp project list [--workspace <path>]``

List every project registered in the workspace, with one row per
project showing the project name, the number of simulations stored,
and the latest activity timestamp.

Example::

   hmp project list

show
----

Synopsis: ``hmp project show <name> [--workspace <path>]``

Print a single-project summary: catalog statistics, last successful
run, on-disk footprint, and a sample of recent simulations. Use it
before :command:`hmp project delete` to confirm what will be removed.

Example::

   hmp project show sample-catchment

delete
------

Synopsis: ``hmp project delete <name> [--force]``

Delete a project entry and all its catalog rows + Zarr stores. Outside
a TTY the action refuses to proceed without ``--force`` so that scripts
do not silently wipe data.

Example::

   hmp project delete sample-catchment --force
