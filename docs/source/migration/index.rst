Migration guides
================

Map every removed or renamed entry point to its new HydroModPy 1.x
counterpart. The TOML-first interface has been the public API since
v1.0; the older Python-driven API is now reserved for internal
prototyping.

If you are starting a new project, jump straight to
:doc:`/getting_started/index` and skip the migration pages.

API stability legend
--------------------

The reference pages in HydroModPy 1.x carry one of three stability
badges set by custom Sphinx roles:

- ``:stable:`` covered by SemVer guarantees within the 1.x line.
- ``:experimental:`` public surface that may change between minor
  versions; opt in only when the feature is explicitly required.
- ``:deprecated:`` scheduled for removal in a future minor version;
  pair with the removal version inline (for example
  ``:deprecated:`removed in 1.3```).

The badges render as coloured inline tags via ``_static/custom.css``.

Use the role inline like this::

   The new ``Project`` facade is :stable:`since 1.0`.
   The legacy ``Watershed`` Python API is :deprecated:`removed in 1.0`.
   The new mesh hotspot detector is :experimental:`since 1.0`.

.. toctree::
   :maxdepth: 1

   v0_to_v1
