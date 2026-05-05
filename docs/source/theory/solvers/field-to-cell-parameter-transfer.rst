Field-To-Cell Parameter Transfer
================================

Purpose
-------

This page explains how HydroModPy turns one spatially defined physical
parameter into solver-ready cell values.

That operation is easy to underestimate. It is not just a data-format step. It
is one of the main places where:

- geometric simplification enters the model,
- heterogeneous geology becomes one value per solver cell,
- vertical variation is introduced,
- backend comparisons can become unfair if the transfer path changes between
  runs.

The Three Objects To Keep Separate
----------------------------------

HydroModPy intentionally separates three things:

1. the spatial support
   This says where a field exists geometrically, for example geology zones or
   one recharge-support partition.
2. the parameter law
   This says which value belongs to each support key, and optionally how that
   value changes with depth.
3. the solver mesh
   This is the final cell topology that needs one value per cell, or one value
   per cell and per layer.

This separation is visible in the public concepts:

- ``Field`` or another support object for geometry,
- ``FieldParam`` for the physical value law,
- one solver mesh or support discretization for the receiving cells.

Common Mapping Chain
--------------------

At a high level, the transfer chain is:

.. code-block:: text

   spatial support
   -> support discretization on one mesh
   -> FieldParam evaluation on that discretization
   -> cell values on the final solver support
   -> optional layer-by-layer reevaluation with depth

This is a scientific choice because the final model always consumes discrete
cell values, even when the source information started as polygons, rasters, or
zone labels.

Homogeneous Versus Heterogeneous Parameters
-------------------------------------------

HydroModPy distinguishes two broad parameter families.

Homogeneous parameters
^^^^^^^^^^^^^^^^^^^^^^

A homogeneous parameter can be evaluated directly on the target mesh. No zone
support is required. The scientific interpretation is simple: every cell
receives the same base value, possibly modified by a depth law.

Heterogeneous parameters
^^^^^^^^^^^^^^^^^^^^^^^^

A heterogeneous parameter points to one support identifier through
``field_spatial_id``. HydroModPy then:

- resolves that support from the domain,
- discretizes the support on the target mesh,
- evaluates the parameter by zone composition on each receiving cell,
- optionally reevaluates by depth for each layer.

This is the path used when one property such as ``K`` or ``Sy`` depends on
geology zones, support classes, or another spatial partition.

Why This Is Not Exact Geometry Preservation
-------------------------------------------

The transfer result is usually one cell value, not a full subcell map.

That means two scientifically different situations can produce the same-looking
solver array:

1. a cell is effectively homogeneous because the support and the mesh align
   well;
2. a cell is assigned one effective value even though multiple support classes
   intersect it.

The second case is not an error. It is a parameterization choice. But it should
be described as such, especially when comparing:

- a coarse structured grid to a finer irregular mesh,
- two meshes with different alignment to geology boundaries,
- one reduced Boussinesq support to one layered MODFLOW support.

Structured Grid Path
--------------------

For the structured MODFLOW path, HydroModPy uses a 2D support discretization
followed by 3D layer evaluation.

The scientific reading is:

- the planar support is first projected on the XY footprint of the structured
  grid,
- the parameter is evaluated on that support at the surface or reference depth,
- the parameter is then reevaluated at each layer-center depth to build 3D
  arrays such as ``hk``, ``sy``, or ``ss``.

This means the support discretization is planar, while the final parameter
arrays are volumetric through repeated depth evaluation.

Irregular MODFLOW 6 Path
------------------------

For the irregular MF6 path, the logic is analogous but the receiving support is
the planar mesh used by the DISV-style solver mesh.

HydroModPy still separates:

- planar support discretization,
- per-cell parameter values on that planar mesh,
- layer-by-layer reevaluation for the extruded layered model.

The main scientific consequence is that irregular MF6 runs can preserve
polygon, hydrography, and catchment constraints more faithfully than a
structured grid, but they also make cell shape and mesh quality more important.

Boussinesq Path
---------------

The in-house Boussinesq backend uses a shallower contract.

Its property mapping stays on one planar triangular mesh and currently resolves
the per-cell quantities needed by the reduced shallow-groundwater formulation,
not a full MODFLOW-style layered stack.

This is why a MODFLOW-versus-Boussinesq comparison should not be read as "same
parameter transfer, different code" without qualification. The physical and
geometric reduction is not identical.

Depth Dependence
----------------

HydroModPy allows one parameter to vary with depth through the ``FieldParam``
vertical-profile logic.

Scientifically, this matters because the project does not need a fully
independent 3D geology object to express:

- stronger conductivity near surface,
- weaker conductivity with depth,
- one tabulated or exponential property profile shared over the model.

This is powerful, but it also means that part of the 3D heterogeneity can live
in the parameter law rather than in explicit internal surfaces.

What Should Be Reported
-----------------------

When a study relies on heterogeneous properties, the following information
should be stated explicitly:

- which support carries the heterogeneity,
- whether the support and the solver mesh are aligned or only intersected,
- whether the comparison uses the same support for all runs,
- whether depth-dependent variation is active,
- whether the final values are planar only or layered.

Without those controls, "same K field" can be more ambiguous than it appears.

Where To Go Deeper
------------------

This page stays at scientific level. For implementation details and diagrams,
continue with:

- :doc:`../../architecture/field/index`
- :doc:`../../architecture/mesh/sgrid-fieldparam-discretization-diagrams`
- :doc:`../../architecture/spatial_support/spatial-support-uml-diagrams`
- ``hydromodpy/spatial/field/README.md``
- ``hydromodpy/spatial/mesh/cartesian_grid/README.md``

Related Scientific Pages
------------------------

- :doc:`mesh-and-discretization-strategies`
- :doc:`vertical-representation-and-storage-assumptions`
- :doc:`mesh-quality-and-acceptance-criteria`
- :doc:`modflow-governing-equation-and-cvfd-formulation`

Current Limitation
------------------

HydroModPy now exposes the public concepts needed to explain this transfer, but
the full project still lacks one compact worked example that follows a real
heterogeneous ``K`` field from geographic support to final MF6 and NWT arrays
side by side.
