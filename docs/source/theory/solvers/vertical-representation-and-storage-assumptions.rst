Vertical Representation And Storage Assumptions
===============================================

Purpose
-------

This page documents what HydroModPy currently assumes when it turns one
planar support into a layered groundwater model.

That is a scientific issue, not just a geometric one, because the chosen
vertical representation controls:

- how aquifer thickness is interpreted,
- how storage terms are distributed,
- which kinds of heterogeneity can be represented geometrically,
- and which ones must remain property-based only.

Conceptual Cross-Section
------------------------

.. mermaid::

   flowchart TB
     Top["Topography<br/>z_top(x, y)"]
     L1["Layer 1<br/>same planar footprint<br/>head h solved in cell"]
     L2["Layer 2 .. n-1<br/>same planar footprint<br/>properties may vary with depth"]
     Ln["Bottom layer<br/>same planar footprint"]
     Bot["Substratum<br/>z_bot(x, y)"]

     Top -- "local thickness z_top - z_bot" --> L1
     L1 -- "shared vertical proportions p_l" --> L2
     L2 -- "repeated planar connectivity" --> Ln
     Ln --> Bot

This diagram is intentionally schematic. It summarizes the current contract:
one planar support is repeated vertically, while storage and material
properties are then assigned within that layered geometry. The geometry
contract uses one planar support reused at every layer with cell-by-cell top
and bottom variation, geology is represented by layer-wise properties rather
than independent internal interfaces, and the storage law stays separate from
geometry (Sy for drainable storage, Ss for compressive storage).

Common Vertical Construction In The MODFLOW Family Path
-------------------------------------------------------

In the shared MODFLOW-family discretization path, HydroModPy starts from two
domain surfaces:

- ``domain.surface_topo``
- ``domain.substratum``

These two surfaces define the total saturated domain thickness available to the
layered model.

The builder then creates one repeated planar topology with several vertical
layers. The same planar cell layout is reused at every layer. What changes from
cell to cell is:

- the top elevation,
- the bottom elevation,
- the total thickness,
- the material properties assigned to each layer and cell.

Layer Proportions
-----------------

The current shared builder uses one global vertical-distribution rule to split
the thickness between the topographic surface and the substratum.

The supported layer-generation modes are:

- constant thickness proportions,
- decay-based thickness proportions,
- explicit user-provided proportion lists.

If :math:`z^{top}` and :math:`z^{bot}` are the local top and substratum
elevations, and :math:`p_l` is the cumulative proportion at layer
:math:`l`, the current builder constructs:

.. math::

   z^{bot}_l = z^{top} - \left(z^{top} - z^{bot}\right) p_l

This means the local total thickness can vary spatially, but the relative
partitioning rule between layers is shared by the whole model.

What This Means Physically
--------------------------

This representation is layered, but it is not a full 3D geological model with
independent internal interfaces.

It means:

- every layer reuses the same planar connectivity,
- the top and bottom surfaces vary cell by cell,
- the internal layer split follows one global proportion rule,
- internal geological complexity is mostly represented through properties, not
  through fully independent geometry per layer.

This is well adapted to:

- shallow unconfined groundwater models,
- comparisons between structured and irregular planar supports,
- workflows where topography and substratum are the primary geometric controls.

It is less adapted to situations where the main scientific question depends on:

- strongly varying internal stratigraphic surfaces,
- layer pinchout logic as a first-class geometric feature,
- local topology changes from one layer to another,
- a true need for ``DISU``-style connectivity rather than repeated-layer
  ``DISV`` topology.

Validity Checks
---------------

Before building the layered model, HydroModPy checks that the bottom surface is
strictly below the top surface on valid cells.

Cells with invalid or nodata support are then propagated into the inactive
mask. Scientifically, this means that geometry validity is enforced before any
property mapping or solver assembly.

Storage Interpretation
----------------------

The current MODFLOW-family storage path uses:

- ``Sy`` for unconfined storage,
- ``Ss`` for compressive storage.

In the current MODFLOW 6 backend:

- both are carried through ``STO``,
- ``iconvert`` is set to the convertible unconfined path,
- stress periods are flagged steady or transient from the simulation time
  definition.

The important scientific point is that the geometry and the storage law are
still separate:

- geometry says how much thickness exists,
- ``Sy`` and ``Ss`` say how the model stores and releases water within that
  geometry.

Implications For Property Mapping
---------------------------------

Because the same planar topology is repeated vertically, heterogeneous
properties can vary:

- from cell to cell,
- and from layer to layer through depth-aware parameter evaluation.

But the vertical geometry itself remains comparatively simple. This is why some
hydrogeological complexity must currently be represented as parameter variation
within one shared layered geometry rather than as explicit internal surfaces.

Relation To Initial Conditions
------------------------------

Initial heads are currently defined in a correspondingly simple way:

- from the top surface,
- from the deepest bottom,
- or from one custom scalar value.

This is consistent with the current vertical contract: the model starts from a
layered geometry that is simple and global enough to make those initialization
policies meaningful across the whole support.

Current Limits
--------------

The current vertical representation should be read with the following limits in
mind.

- It is topography-plus-substratum driven, not a general internal-surface
  geology engine.
- It reuses one planar connectivity across all layers.
- It does not yet document a public path for complex pinchout logic as a core
  modelling feature.
- It is stronger for shallow groundwater systems than for fully stratified deep
  basin architecture.

Relation To The Boussinesq Backend
----------------------------------

The in-house Boussinesq backend uses a different scientific reduction. It works
on a 2D planar mesh with shallow-groundwater assumptions rather than on a full
stack of MODFLOW layers.

That makes this page especially important in comparison workflows:

- MF6 comparisons are not only about two codes,
- they may also compare a layered groundwater representation against a reduced
  shallow-flow representation.

Those comparisons are still valuable, but only if the different vertical
assumptions are kept explicit.

Related Pages
-------------

- :doc:`mesh-and-discretization-strategies`
- :doc:`modflow-package-semantics-and-boundary-conditions`
- :doc:`../foundations/groundwater-flow-problem-definition`
- :doc:`../boussinesq`
