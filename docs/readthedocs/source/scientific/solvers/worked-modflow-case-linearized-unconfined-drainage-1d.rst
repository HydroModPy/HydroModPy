Worked MODFLOW Case: Linearized Unconfined Drainage 1D
======================================================

Purpose
-------

This page is the worked-case counterpart for the ``DRN`` package path.

It shows, on one real public HydroModPy benchmark:

- how a user-facing drainage boundary is declared,
- how HydroModPy interprets it scientifically,
- how it becomes ``DRN`` payloads in MF6 and MODFLOW-NWT,
- and what committed validation results look like.

Why This Case
-------------

The chosen case is
``validation_cases/analytical/steady/linearized_unconfined_drainage_1d``.

It is the best first drainage case because it is:

- steady and analytically interpretable,
- based on one flat strip, so the geometry stays simple,
- explicitly centered on the top-drainage boundary path,
- already published with committed figures and metrics.

This makes it ideal for isolating one key distinction:

- ``drainage`` is not diffuse recharge,
- and it is not the same thing as a stage-controlled ``CHD`` boundary.

Files Used
----------

- MODFLOW-NWT base config:
  ``validation_cases/analytical/steady/linearized_unconfined_drainage_1d/config_modflownwt.toml``
- MODFLOW 6 overlay:
  ``validation_cases/analytical/steady/linearized_unconfined_drainage_1d/config_modflow6.toml``
- Case metadata:
  ``validation_cases/analytical/steady/linearized_unconfined_drainage_1d/metadata.toml``
- Gallery page:
  :doc:`../../capability_gallery/cases/linearized_unconfined_drainage_1d`

Minimal TOML Reading
--------------------

Core steady case
^^^^^^^^^^^^^^^^

.. code-block:: toml

   [geographic.synthetic.grid]
   length_x = "100.0 m"
   length_y = "10.0 m"
   nx = 50
   ny = 5

   [geographic.synthetic.topography]
   kind = "flat"
   base_elevation = 0.0

   [domain.depth_model]
   type = "constant_thickness"
   thickness = "20.0 m"

   [flow]
   flow_regime = "steady"
   active_sinks_sources = []
   active_bc = ["west_side", "east_side", "drainage"]
   param_list = ["K"]

   [flow.param.K.field_homogeneous]
   value = "1e-4 m/s"

   [flow.ic]
   type = "custom"
   value = "6.0 m"

   [flow.bc.dirichlet.west_side]
   value = "6.2 m"

   [flow.bc.dirichlet.east_side]
   value = "5.8 m"

This defines a steady strip with:

- fixed west and east heads,
- no recharge, no wells, no EVT forcing,
- one homogeneous conductivity,
- one water table everywhere above the drainage elevation.

Drainage declaration
^^^^^^^^^^^^^^^^^^^^

.. code-block:: toml

   [flow.bc.cauchy.drainage]
   application_domain = "top"
   type = "cauchy"
   value = "1e-7 m2/s"

This is the key declaration of the benchmark.

At HydroModPy level, this means:

- activate one head-dependent release operator,
- apply it on the top support,
- use one explicit conductance of ``1e-7 m2/s``,
- let the resulting drainage outflow emerge from the solved head field.

The case metadata confirms the intended analytical reading:

- drainage elevation: ``0.0 m``
- drainage conductance: ``1e-7 m2/s``

So the benchmark is not a seepage-face search or a stream-stage problem. It is
one distributed drainage operator applied everywhere on the top support.

MODFLOW 6 overlay
^^^^^^^^^^^^^^^^^

.. code-block:: toml

   [[simulation.process]]
   solvers = ["modflow6"]

   [modflow6.runtime]
   mf6_ims_complexity = "COMPLEX"

   [modflow6.sgrid.planar]
   mode = "resample_to_shape"
   nx = 50
   ny = 5

   [modflow6.sgrid.vertical]
   nlay = 1

This keeps the support structured-style and uses the normal MF6 public path.

What HydroModPy Resolves Before Package Assembly
------------------------------------------------

Before the solver-specific package writing starts, HydroModPy already resolves
the benchmark into a clearer runtime picture.

.. list-table::
   :header-rows: 1
   :widths: 24 28 48

   * - Input concern
     - Resolved HydroModPy meaning
     - Consequence for this case
   * - ``flow_regime = "steady"``
     - One steady flow solve
     - Storage is not the scientific focus here
   * - ``active_sinks_sources = []``
     - No diffuse climatic forcing
     - ``RCHA`` and ``EVT`` stay irrelevant here
   * - ``active_bc`` includes ``drainage``
     - One boundary-driven release mechanism is active
     - The benchmark is mainly about ``DRN``, not about recharge
   * - Topography base elevation ``0.0 m``
     - Flat top support at 0 m
     - The drainage elevation matches that top support in this benchmark
   * - Homogeneous ``K``
     - One uniform conductivity field
     - The conductance policy stays easy to interpret
   * - Explicit drainage conductance ``1e-7 m2/s``
     - User conductance is already known
     - HydroModPy does not need the ``hk * area`` fallback here

How User-Facing Drainage Becomes ``DRN``
----------------------------------------

This is the main method translation performed by the MODFLOW-family adapters.

Scientific meaning first
^^^^^^^^^^^^^^^^^^^^^^^^

The important distinction is:

- recharge prescribes one inflow rate,
- ``CHD`` prescribes one head,
- ``DRN`` prescribes one release condition.

In this case, the model is allowed to drain through the top support because the
computed head stays above the drainage elevation.

MODFLOW-NWT path
^^^^^^^^^^^^^^^^

In the NWT adapter, the drainage builder creates rows of the form:

``[lay, row, col, elevation, conductance]``

with:

- elevation = local top elevation,
- conductance = the explicit user value when it is positive,
- one payload populated at period 0 for the steady case.

So here the NWT branch effectively builds one distributed ``DRN`` layer at
elevation ``0 m`` with conductance ``1e-7 m2/s`` on the active top cells.

MODFLOW 6 path
^^^^^^^^^^^^^^

In the MF6 builder, the drainage package rows are built as:

``[layer, cellid, elevation, conductance]``

Again, for this case:

- elevation = ``top_flat[cid] = 0.0 m``,
- conductance = explicit configured value ``1e-7 m2/s``,
- every active top cell participates because there are no stream or ocean
  supports removing cells from the drainage mask.

The scientific contract is therefore the same across both MODFLOW branches,
even if the raw package syntax differs.

What This Case Is Not Testing
-----------------------------

This benchmark intentionally avoids several other effects.

It is not testing:

- recharge-driven response,
- negative recharge routed to ``EVT``,
- stage-controlled stream or ocean boundaries,
- transient storage,
- or basin-specific topographic complexity.

That is why it complements the periodic-recharge worked case well.

MF6 Package Assembly On This Case
---------------------------------

For the MODFLOW 6 branch, the public package picture is:

1. ``TDIS``
   one steady-compatible time frame is still created by the common MF6 path;
2. ``IMS``
   built from the MF6 runtime preset;
3. ``DISV``
   used as the unified MF6 geometry export path;
4. ``IC``
   built from the uniform initial head ``6.0 m``;
5. ``NPF``
   built from homogeneous ``K`` and the convertible-cell path;
6. ``STO``
   assembled by the common path but not central to the benchmark;
7. ``CHD``
   used for the west and east fixed heads;
8. ``DRN``
   used for the distributed drainage operator;
9. ``OC``
   used to save heads and budgets.

The main scientific difference from the Dupuit fixed-head worked case is
therefore:

- Dupuit fixed-head 1D is dominated by ``CHD``,
- this drainage benchmark is dominated by the combination ``CHD + DRN``.

Why The Conductance Choice Matters
----------------------------------

HydroModPy supports two broad drainage conductance policies:

- explicit user conductance when the boundary value is positive,
- fallback conductance derived from ``hk * cell_area`` when the configured
  value is zero or negative.

This benchmark deliberately uses the first branch:

- the TOML states ``1e-7 m2/s``,
- the analytical reference also uses that explicit conductance,
- so the method comparison is not confounded by a fallback conductance rule.

That makes this page a clean worked example of the explicit ``DRN`` path.

Why Boussinesq Is Not In This Worked Case
-----------------------------------------

The benchmark is published for MODFLOW-family solvers only.

The local Boussinesq backend is intentionally not highlighted here because the
benchmark was designed to stay on a distributed drainage branch while keeping
the water table above the drainage elevation everywhere. The case README notes
that this collides with the current saturation-excess surface closure of the
Boussinesq path instead of staying on the intended linearized distributed
drainage interpretation.

So this page is specifically about how the MODFLOW-family path interprets the
drainage boundary.

Real Results Already Committed
------------------------------

The figures below are committed validation artifacts from real runs.

.. tab-set::

   .. tab-item:: MODFLOW-NWT

      .. figure:: /_static/capability_gallery/validation/linearized_unconfined_drainage_1d__modflownwt.png
         :alt: Linearized unconfined drainage rendered with MODFLOW-NWT
         :width: 100%

         Real committed validation figure for the NWT drainage path.

      - Head-profile RMSE: ``0.0127 m``
      - Head-profile max abs error: ``0.0175 m``
      - Cross-row spread: ``1.91e-07 m``

   .. tab-item:: MODFLOW 6

      .. figure:: /_static/capability_gallery/validation/linearized_unconfined_drainage_1d__modflow6.png
         :alt: Linearized unconfined drainage rendered with MODFLOW 6
         :width: 100%

         Real committed validation figure for the MF6 drainage path.

      - Head-profile RMSE: ``0.0127 m``
      - Head-profile max abs error: ``0.0175 m``
      - Cross-row spread: ``1.59e-07 m``

These figures show that the benchmark is well suited to checking whether the
distributed drainage boundary was assembled consistently across MODFLOW-family
solvers.

For support-sensitivity on the same drainage case, see the committed gallery
page:
:doc:`../../capability_gallery/cases/linearized_unconfined_drainage_1d`.

How To Reproduce The Case
-------------------------

Run the benchmark directly with:

.. code-block:: powershell

   python -m validation_cases.analytical.steady.linearized_unconfined_drainage_1d.run_case --no-show --solver modflow6

or the NWT version with:

.. code-block:: powershell

   python -m validation_cases.analytical.steady.linearized_unconfined_drainage_1d.run_case --no-show --solver modflownwt

Related Reading
---------------

- :doc:`../hydrology/stream-ocean-and-drainage-semantics`
- :doc:`modflow-package-semantics-and-boundary-conditions`
- :doc:`worked-modflow-case-dupuit-fixed-head-1d`
- :doc:`worked-modflow-case-linearized-unconfined-recharge-periodic-1d`
- :doc:`../../capability_gallery/cases/linearized_unconfined_hillslope_drainage_1d`

Current Limitation
------------------

This worked case documents ``DRN`` clearly, but it still does not document:

- one case where negative recharge actually activates ``EVT``,
- one case where drainage interacts with transient recharge,
- one natural-basin seepage or drainage interpretation on a richer support.
