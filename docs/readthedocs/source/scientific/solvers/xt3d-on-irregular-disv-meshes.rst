XT3D On Irregular DISV Meshes
=============================

Purpose
-------

This page documents one concrete numerical policy already encoded in the
MODFLOW 6 backend:

- XT3D is left disabled by default on structured meshes,
- XT3D is auto-enabled by default on unstructured runtime meshes,
- users can still override that choice explicitly.

That policy deserves a scientific note because it affects both accuracy and
cost on catchment-conformal meshes.

Current HydroModPy Policy
-------------------------

The current MODFLOW 6 runtime configuration accepts
``modflow6.runtime.mf6_enable_xt3d``.

Its behaviour is:

.. list-table::
   :header-rows: 1
   :widths: 22 22 18 38

   * - Mesh path
     - User flag
     - Effective XT3D
     - Meaning
   * - Structured mesh
     - ``None``
     - Disabled
     - Keep the simpler default path on orthogonal-style grids
   * - Runtime irregular mesh
     - ``None``
     - Enabled
     - Prefer the more robust option on non-orthogonal cell geometries
   * - Any mesh
     - ``True``
     - Enabled
     - Force XT3D explicitly
   * - Any mesh
     - ``False``
     - Disabled
     - Force the simpler path explicitly

HydroModPy also adjusts the IMS complexity logic accordingly. If XT3D is
active and the user asked for ``SIMPLE``, the backend upgrades the effective
complexity because XT3D can produce an asymmetric coefficient matrix.

Why This Policy Exists
----------------------

The main motivation is geometric.

Catchment-conformal runtime meshes are valuable because they can:

- follow river constraints,
- follow support and geology boundaries more closely,
- create comparison-ready shared supports across solver families.

But those same meshes are not as numerically benign as orthogonal structured
grids. On irregular triangles or non-orthogonal polygons, the basic
two-point-style flow approximation is more exposed to orientation and shape
effects.

HydroModPy therefore chooses the following default:

- on structured grids, keep the simpler path unless the user explicitly wants
  XT3D;
- on irregular runtime meshes, spend more computation to reduce the risk that
  geometry-induced error dominates the comparison.

This is a deliberate "accuracy first" policy for the unstructured path.

Trade-Offs
----------

XT3D is not a free improvement. Its main trade-offs are:

- higher setup and solve cost,
- potentially larger memory footprint,
- a more demanding linear-algebra problem,
- slower comparison sweeps when many cases are run repeatedly.

That is why HydroModPy does not simply enable XT3D everywhere. The project only
auto-enables it where the geometric argument is strongest: runtime unstructured
meshes.

When To Keep It Enabled
-----------------------

The default should generally be kept when:

- the mesh is catchment-conformal or clearly non-orthogonal,
- the run is intended for MODFLOW 6 versus Boussinesq comparison on one shared
  natural mesh,
- the objective is to reduce geometric discretization bias rather than to
  minimize runtime cost.

This is especially true when the support was built precisely to honour river or
geology constraints. Turning XT3D off in that setting may save time while also
weakening the reason the irregular mesh was chosen in the first place.

When To Disable It Deliberately
-------------------------------

Disabling XT3D can still be scientifically reasonable in controlled cases:

- quick debugging runs where only model wiring is being checked,
- structured or nearly orthogonal meshes where the irregular-mesh argument is
  weak,
- explicit comparison experiments whose goal is precisely to measure the
  impact of XT3D itself.

If XT3D is disabled on a runtime irregular mesh, the result should usually be
treated as a method-sensitivity experiment rather than as the default reference
configuration.

How It Should Be Reported
-------------------------

Because XT3D materially changes the numerical formulation, comparison and
validation pages should report it explicitly.

At minimum, one comparison page should make the following visible:

- whether XT3D was auto-enabled or explicitly requested,
- whether the mesh was structured or irregular,
- whether the comparison is isolating solver choice, XT3D choice, or both.

Otherwise, two runs may look like "MF6 versus Boussinesq" or "MF6 versus NWT"
while actually differing in an undocumented numerical option that matters.

Current Evidence Anchors
------------------------

The repository already contains several useful anchors for this topic:

- the XT3D auto-resolution logic in ``hydromodpy/solver/modflow6/modflow6.py``,
- the runtime configuration flag in
  ``hydromodpy/solver/modflow6/modflow6_config.py``,
- diagnostic assets under
  ``docs/readthedocs/source/_static/capability_gallery/validation/``.

The public scientific role of this page is to consolidate those scattered
anchors into one explicit method note.

Related Pages
-------------

- :doc:`mesh-and-discretization-strategies`
- :doc:`modflow-package-semantics-and-boundary-conditions`
- :doc:`modflow-family-methods`
- :doc:`../../getting_started/comparison-workflow`
