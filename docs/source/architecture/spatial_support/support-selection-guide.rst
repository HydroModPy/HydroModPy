Choosing A Spatial Support
==========================

Scope
-----

This page complements the UML diagrams with a simple question: which support
type should be used for a given heterogeneous parameterization?

Code map
--------

- ``hydromodpy/spatial/domain/domain_config.py``:
  validation of domain support declarations.
- ``hydromodpy/spatial/domain/spatial_support_config.py``:
  typed support-definition models.
- ``hydromodpy/spatial/domain/spatial_support.py``:
  runtime support builders.
- ``hydromodpy/spatial/field/core/field_param.py``:
  consumer side through ``field_spatial_id``.
- ``hydromodpy/spatial/mesh/cartesian_grid/sgrid_fieldparam_discretization.py``:
  discretization of heterogeneous field parameters.

Recommended reading path
------------------------

1. ``hydromodpy/spatial/domain/spatial_support_config.py``
2. ``hydromodpy/spatial/domain/spatial_support.py``
3. ``hydromodpy/spatial/field/core/field_param.py``
4. ``hydromodpy/spatial/mesh/cartesian_grid/sgrid_fieldparam_discretization.py``

Core Rule
---------

Use a spatial support only when a ``FieldParam`` is heterogeneous. In that
case, ``field_spatial_id`` must reference a support known by the ``Domain``.

When To Use Each Support
------------------------

If all parameters are homogeneous, no spatial support declaration is needed.

Declare a ``geology`` support when the zones come from the geology dataset
managed by the domain workflow. This is the right choice when the support is
not synthetic and should be derived from geology loading/binding.

Declare one or more non-geology supports in ``domain.supports`` for synthetic
or user-defined zonations.

Choose ``generated_bands`` when the domain is partitioned along one axis:

- layered strips along ``x`` or ``y``;
- simple piecewise-constant benchmarks;
- 2D tests that are still analytically 1D.

Choose ``generated_rings`` when the domain is partitioned by distance to a
center:

- radial island or circular benchmark cases;
- concentric transmissivity or recharge zones;
- synthetic tests where the geometry is easier to define by radii than by
  polygons.

Choose ``catchment_zones`` when the zones already exist as catchment-side
partitions and should be reused directly instead of redefined synthetically.

Decision Heuristics
-------------------

Prefer ``geology`` if the zoning is part of the domain data pipeline and should
stay coupled to geology preprocessing.

Prefer ``generated_bands`` if the support can be explained by a small set of
break coordinates along one axis.

Prefer ``generated_rings`` if the support is radial and centered on a known
point.

Prefer ``catchment_zones`` if the support already exists as a watershed or
management partition.

It is valid to mix geology-backed and synthetic supports in the same
``domain.supports`` mapping. Each heterogeneous ``FieldParam`` simply points to
the support it needs through ``field_spatial_id``.

Minimal Configuration Patterns
------------------------------

Homogeneous parameter, no support needed:

.. code-block:: toml

   [domain]

Bands support:

.. code-block:: toml

   [domain]

   [domain.supports.k_x]
   provider = "generated_bands"
   axis = "x"
   coordinate_mode = "absolute"
   breaks = [200.0, 500.0]
   labels = ["left", "middle", "right"]

Rings support:

.. code-block:: toml

   [domain]

   [domain.supports.k_r]
   provider = "generated_rings"
   coordinate_mode = "absolute"
   center_x = 500.0
   center_y = 500.0
   radii = [150.0, 300.0]
   labels = ["inner", "middle", "outer"]

Catchment zones support:

.. code-block:: toml

   [domain]

   [domain.supports.management]
   provider = "catchment_zones"
   source_zone_id = "management"

Geology support:

.. code-block:: toml

   [domain]

   [domain.supports.field_geology]
   provider = "geology"

Heterogeneous parameter referencing a support:

.. code-block:: toml

   [flow.k.field]
   field_spatial_id = "k_x"
   values = { left = 1.0e-4, middle = 5.0e-5, right = 1.0e-5 }

The support identifier (``k_x`` above) must match the ``field_spatial_id``.
The value keys must match the support labels.

Common Mistakes
---------------

Using ``field_spatial_id`` for a heterogeneous parameter without registering a
support under the same identifier.

Expecting geology supports to be inferred implicitly. Geology-backed supports
must now be declared explicitly under ``domain.supports``.

Choosing ``generated_bands`` for a truly radial case, or ``generated_rings``
for a zoning that is really tied to catchment data rather than geometry.

Related diagrams
----------------

Use the companion UML page for structural details and runtime call sequences:

- :doc:`spatial-support-uml-diagrams`
