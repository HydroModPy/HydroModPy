Choosing A Spatial Support
==========================

This page complements the UML diagrams with a simple question: which support
type should be used for a given heterogeneous parameterization?

Core Rule
---------

Use a spatial support only when a ``FieldParam`` is heterogeneous. In that
case, ``field_spatial_id`` must reference a support known by the ``Domain``.

Relevant code paths:

- ``domain.support_mode`` and ``domain.supports`` are validated in
  ``hydromodpy.domain.domain_config``.
- support definitions are modeled in ``hydromodpy.domain.spatial_support_config``.
- runtime support objects are built in ``hydromodpy.domain.spatial_support``.
- heterogeneous mapping is consumed through ``FieldParam.field_spatial_id`` and
  discretized by ``hydromodpy.solver.utils.mesh.cartesian_grid.sgrid_fieldparam_discretization``.

When To Use Each Support
------------------------

Use ``support_mode = "none"`` when all parameters are homogeneous.

Use ``support_mode = "geology"`` when the zones come from the geology dataset
managed by the domain workflow. This is the right choice when the support is
not synthetic and should be derived from geology loading/binding.

Use ``support_mode = "zones"`` when the zones are explicitly declared in
``domain.supports``. This covers the synthetic and user-defined cases below.

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

Do not mix geology supports into ``support_mode = "zones"``. Likewise, do not
declare non-geology supports under ``support_mode = "geology"``.

Minimal Configuration Patterns
------------------------------

Homogeneous parameter, no support needed:

.. code-block:: toml

   [domain]
   support_mode = "none"

Bands support:

.. code-block:: toml

   [domain]
   support_mode = "zones"

   [domain.supports.k_x]
   provider = "generated_bands"
   axis = "x"
   coordinate_mode = "absolute"
   breaks = [200.0, 500.0]
   labels = ["left", "middle", "right"]

Rings support:

.. code-block:: toml

   [domain]
   support_mode = "zones"

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
   support_mode = "zones"

   [domain.supports.management]
   provider = "catchment_zones"
   source_zone_id = "management"

Geology support:

.. code-block:: toml

   [domain]
   support_mode = "geology"

   [domain.supports.field_geology]
   provider = "geology"

Heterogeneous parameter referencing a support:

.. code-block:: toml

   [flow.k.field_heterogeneous]
   field_spatial_id = "k_x"
   values = { left = 1.0e-4, middle = 5.0e-5, right = 1.0e-5 }

The support identifier (``k_x`` above) must match the ``field_spatial_id``.
The value keys must match the support labels.

Common Mistakes
---------------

Declaring ``domain.supports`` while keeping ``support_mode = "none"``. This is
rejected by ``DomainConfig``.

Using ``field_spatial_id`` for a heterogeneous parameter without registering a
support under the same identifier.

Choosing ``generated_bands`` for a truly radial case, or ``generated_rings``
for a zoning that is really tied to catchment data rather than geometry.

Next Step
---------

Use the companion UML page for structural details and runtime call sequences:

- :doc:`spatial-support-uml-diagrams`
