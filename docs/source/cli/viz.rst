hmp viz
=======

The :command:`hmp viz` family groups the visualization helpers: figure
discovery, one-shot render, and full gallery render.

list
----

Synopsis: ``hmp viz list [--kind <kind>]``

Print the figure names accepted by ``[display].figures``, with their kind
(``spatial``, ``timeseries``, ``comparison``, ``section``, ``balance``) and
the data each one requires.

Example::

   hmp viz list
   hmp viz list --kind spatial

show
----

Synopsis: ``hmp viz show <ref> <figure> [--workspace <path>] [--output <path>]``

Render one registered figure for one run. Without ``--output`` the PNG
lands in ``runs/<name>/figures/<figure>.png``. Use ``hmp viz list`` to get
the exact figure name; an unknown name prints the full registry.

Example::

   hmp viz show demo piezometric_map
   hmp viz show demo watertable_depth_map --output /tmp/depth.png

gallery
-------

Synopsis: ``hmp viz gallery <config.toml> [--run NAME | --sim UUID | --all |
--latest N] [--only F1,F2] [--no-show]``

Render the figures declared under ``[display]`` for the runs produced by
``<config.toml>``. The selectors filter which runs are rendered; the latest
one is used by default.

Example::

   hmp viz gallery projects/my_basin/run_demo.toml --latest 3
