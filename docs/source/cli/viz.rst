hmp viz
=======

The :command:`hmp viz` family groups the visualization helpers: one-shot
figure render and full gallery render.

show
----

Synopsis: ``hmp viz show <sim_ref> <figure> [--workspace <path>] [--output <path>]``

Render a single registered figure for one simulation. The simulation
reference accepts a full UUID, a unique prefix, or the simulation name.

Example::

   hmp viz show baseline watertable_map --output figures/watertable.png

gallery
-------

Synopsis: ``hmp viz gallery <config.toml> [--run NAME | --sim UUID | --all | --latest N] [--only F1,F2]``

Render the figures declared under ``[display]`` for the simulations
produced by ``<config.toml>``. Selectors filter the runs (latest by
default). Use ``--list`` to preview the matching runs without rendering.

Example::

   hmp viz gallery projects/my_basin/run_demo.toml --latest 3
