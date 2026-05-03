Worked MODFLOW Case: Dupuit Fixed-Head 1D
=========================================

Purpose
-------

This page is one concrete worked example of the HydroModPy MODFLOW path.

Its goal is simple:

- start from one real public HydroModPy case,
- show which parts of the TOML matter scientifically,
- explain which MODFLOW packages are actually assembled,
- and connect that setup to real committed result figures.

Why This Case
-------------

The chosen case is the validation benchmark
``validation_cases/analytical/steady/dupuit_fixed_head_1d``.

It is a good first worked case because it is:

- public and reproducible,
- physically simple,
- steady-state,
- easy to read package by package,
- already documented with committed figures and metrics in the capability
  gallery.

This is still a real HydroModPy simulation chain. It is just a deliberately
small synthetic one, which makes it much easier to explain than a full basin
case.

Files Used
----------

The case is split into one common file plus solver-specific overlays.

- Common case definition:
  ``validation_cases/analytical/steady/dupuit_fixed_head_1d/config_common.toml``
- MODFLOW 6 structured overlay:
  ``validation_cases/analytical/steady/dupuit_fixed_head_1d/config_modflow6.toml``
- MODFLOW 6 irregular-triangle overlay:
  ``validation_cases/analytical/steady/dupuit_fixed_head_1d/config_modflow6_irregular_tri.toml``
- Case metadata:
  ``validation_cases/analytical/steady/dupuit_fixed_head_1d/metadata.toml``

Minimal TOML Reading
--------------------

Common physical case
^^^^^^^^^^^^^^^^^^^^

.. code-block:: toml

   workflow = "simulation"

   [geographic.synthetic.grid]
   length_x = "400.0 m"
   length_y = "50.0 m"
   nx = 40
   ny = 5

   [domain.depth_model]
   type = "constant_thickness"
   thickness = "20.0 m"

   [flow]
   flow_regime = "steady"
   active_sinks_sources = []
   active_bc = ["west_side", "east_side"]
   param_list = ["K"]

   [flow.param.K.field_homogeneous]
   value = "1e-4 m/s"

   [flow.ic]
   type = "custom"
   value = "7.5 m"

   [flow.bc.dirichlet.west_side]
   value = "10.0 m"

   [flow.bc.dirichlet.east_side]
   value = "5.0 m"

This tells HydroModPy to solve one steady unconfined strip:

- 400 m long and 50 m wide,
- constant thickness 20 m,
- one homogeneous conductivity,
- one custom initial head,
- fixed west and east heads,
- no recharge, no wells, no drainage, no EVT forcing.

MODFLOW 6 structured overlay
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: toml

   [[simulation.process]]
   solvers = ["modflow6"]

   [modflow6.runtime]
   mf6_ims_complexity = "SIMPLE"

   [modflow6.process_specific]
   vka = 1.0

   [modflow6.sgrid.planar]
   mode = "resample_to_shape"
   nx = 40
   ny = 5

   [modflow6.sgrid.vertical]
   nlay = 1

This keeps the case on a structured-style 40 x 5 support and asks MF6 for:

- one simple IMS preset,
- one single layer,
- ``vka = 1.0``, so no vertical anisotropy relative to ``k``.

MODFLOW 6 irregular-triangle overlay
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: toml

   [[simulation.process]]
   solvers = ["modflow6"]

   [modflow6.runtime]
   mf6_ims_complexity = "COMPLEX"

   [modflow6.process_specific]
   vka = 1.0

   [modflow6.sgrid.vertical]
   nlay = 1

   [mesh_input]
   mesh_path = "../../../shared/mesh_bundles/sloping_substratum_irregular_tri_400x50/mesh_2d.msh"
   bundle_dir = "../../../shared/mesh_bundles/sloping_substratum_irregular_tri_400x50"

This keeps the same physical strip problem but changes the planar support:

- HydroModPy now consumes one committed irregular triangular mesh,
- MF6 moves to the ``DISV`` path on that support,
- XT3D is left on auto mode and therefore becomes active on this unstructured
  mesh path.

What HydroModPy Resolves Before MODFLOW Assembly
------------------------------------------------

Before any FLOPY package is written, HydroModPy already resolves the case into
one solver-agnostic runtime picture.

.. list-table::
   :header-rows: 1
   :widths: 24 30 46

   * - Input concern
     - Resolved HydroModPy meaning
     - Consequence for this case
   * - ``flow_regime = "steady"``
     - One steady flow process
     - The case does not exercise transient storage behaviour
   * - ``active_sinks_sources = []``
     - No diffuse or localized source/sink families are active
     - No physical recharge, well, or ETP forcing is intended in the case
   * - West/east Dirichlet boundaries
     - Two imposed-head side supports
     - The case is dominated by ``CHD``-style boundary control
   * - Homogeneous ``K``
     - One uniform conductivity field
     - ``NPF`` receives one simple conductivity payload
   * - ``flow.ic.type = "custom"``
     - One uniform initial head
     - ``IC`` starts from 7.5 m everywhere before the steady solve
   * - ``nlay = 1``
     - One vertically simple support
     - Vertical interpretation is intentionally minimal here
   * - ``vka = 1.0``
     - No vertical/horizontal anisotropy contrast
     - ``k33 = k`` in the common MF6 rule

MF6 Package Assembly On This Case
---------------------------------

The current MF6 builder lives mainly in
``hydromodpy/solver/modflow6/modflow6.py``.

For this particular case, the public package sequence is:

1. ``TDIS``
   Built from the launcher time definition. This steady case still gets one
   valid MF6 time discretization record.
2. ``IMS``
   Built from ``modflow6.runtime``. The structured case keeps ``SIMPLE``.
   The irregular-triangle overlay asks for ``COMPLEX``.
3. ``DISV``
   Built in both MF6 paths. HydroModPy keeps ``DISV`` as the unified MF6
   geometry export contract, even for the structured-style support.
4. ``IC``
   Built from the custom initial head value ``7.5 m``.
5. ``NPF``
   Receives the conductivity payload, the convertible-cell path, and
   ``k33 = k / vka``. Here ``vka = 1.0``, so the public rule reduces to
   ``k33 = k``.
6. ``STO``
   Still assembled by the common MF6 path, but this case is steady and does
   not use the page as a transient-storage benchmark.
7. ``RCHA``
   Still exists in the common MF6 assembly, but carries zero recharge here
   because the case does not activate recharge.
8. ``CHD``
   Carries the west and east side imposed-head boundaries. This is the main
   active stress package in the benchmark.
9. ``OC``
   Saves heads and budgets for postprocessing and validation.

What Is Not Exercised Here
^^^^^^^^^^^^^^^^^^^^^^^^^^

This case is intentionally narrow. It does not exercise:

- ``EVT``,
- ``DRN``,
- ``WEL``,
- nonzero ``RCHA``,
- transient stress-period aggregation.

That makes it a very good first MODFLOW worked case, but not a complete one.

Why The Option Choices Make Sense Here
--------------------------------------

This benchmark is useful precisely because the option logic stays readable.

- ``DISV`` in both MF6 paths:
  this is a HydroModPy architecture choice that keeps one unified MF6 export
  contract for both structured-style and irregular supports.
- ``mf6_ims_complexity = "SIMPLE"`` on the structured overlay:
  reasonable for a small steady case with no recharge, wells, or difficult
  nonlinear forcing.
- ``mf6_ims_complexity = "COMPLEX"`` on the irregular-triangle overlay:
  conservative choice for the less benign support.
- XT3D on the irregular-triangle path:
  left in auto mode, so HydroModPy enables it on the unstructured support.
  That follows the project rule documented in
  :doc:`xt3d-on-irregular-disv-meshes`.
- ``vka = 1.0``:
  removes anisotropy as a confounding factor, which is appropriate for a
  simple validation strip.
- side heads as ``CHD``:
  exactly matches the physical meaning of the case, which is a fixed-head
  boundary benchmark.

Real Results Already Committed
------------------------------

The figures below are not placeholders. They are committed capability-gallery
artifacts produced from the real validation runs.

.. tab-set::

   .. tab-item:: MODFLOW 6 structured-style support

      .. figure:: /_static/capability_gallery/validation/dupuit_fixed_head_1d__modflow6.png
         :alt: Dupuit Fixed-Head 1D rendered with MODFLOW 6
         :width: 100%

         Real committed validation figure for the MF6 structured-style path.

      - Head-profile RMSE: ``0.0001 m``
      - Head-profile max abs error: ``0.0001 m``
      - Reading:
        this small case is mainly a solver-chain sanity check and MF6 matches
        the analytical reference very closely on the structured-style support.

   .. tab-item:: MODFLOW 6 irregular-triangle support

      .. figure:: /_static/capability_gallery/validation/dupuit_fixed_head_1d__modflow6_irregular_tri.png
         :alt: Dupuit Fixed-Head 1D rendered with MODFLOW 6 irregular triangles
         :width: 100%

         Real committed validation figure for the MF6 irregular-triangle path.

      - Head-profile RMSE: ``0.0195 m``
      - Head-profile max abs error: ``0.0453 m``
      - Reading:
        this is still the same physical case, but the support and numerical
        path are no longer the same. It is therefore a good illustration that
        mesh/discretization choice is part of the scientific method choice.

Those metrics come from the committed gallery page
:doc:`../../capability_gallery/cases/dupuit_fixed_head_1d`.

How To Reproduce The Case
-------------------------

The benchmark can be rerun directly with:

.. code-block:: powershell

   python -m validation_cases.analytical.steady.dupuit_fixed_head_1d.run_case --no-show --solver modflow6

and the irregular-triangle overlay with:

.. code-block:: powershell

   python -m validation_cases.analytical.steady.dupuit_fixed_head_1d.run_case --no-show --solver modflow6_irregular_tri

For Richer Basin-Scale Illustrations
------------------------------------

This worked case is ideal for understanding package assembly, but it is not a
natural basin example.

If you want richer maps and more realistic outputs, continue with:

- :doc:`../../capability_gallery/cases/modflow6_gmsh_mesh_catchment`
- :doc:`../../capability_gallery/cases/headwater_100km2_outlet_2_mf6_transient_reference`

Those pages show real HydroModPy MF6 simulations with:

- support overviews,
- head and water-table maps,
- cumulative recharge/discharge figures,
- and transient or catchment-scale behaviour.

Recommended Reading Order
-------------------------

This page works best after the conceptual MODFLOW notes and before larger
comparison or basin pages.

1. :doc:`modflow-governing-equation-and-cvfd-formulation`
2. :doc:`modflow-package-semantics-and-boundary-conditions`
3. this worked case
4. :doc:`modflow6-vs-modflownwt-scientific-comparison`
5. :doc:`../../getting_started/comparison-workflow`

Current Limitation
------------------

This worked case is deliberately minimal.

The next useful worked examples would be:

- one transient recharge case that exercises ``RCHA`` and forcing aggregation,
- one drainage or surface-exchange case that exercises ``DRN`` and ``EVT``,
- one natural-basin case that shows the same TOML-to-package logic on a richer
  support.
