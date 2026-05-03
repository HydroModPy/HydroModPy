Worked MODFLOW Case: Linearized Unconfined Recharge Periodic 1D
================================================================

Purpose
-------

This page is the transient counterpart to the simpler steady Dupuit worked
case.

It uses one real public HydroModPy validation benchmark to show:

- how a time-dependent recharge forcing is declared,
- how HydroModPy turns that forcing into stress-period values,
- which MODFLOW packages are then assembled,
- and what real committed transient results look like.

Why This Case
-------------

The chosen case is
``validation_cases/analytical/transient/linearized_unconfined_recharge_periodic_1d``.

It is a strong second worked case because it remains simple while exercising
the main transient controls:

- ``[simulation.time]``,
- unconfined storage through ``Sy`` and ``Ss``,
- diffuse recharge through the common recharge contract,
- ``RCHA`` or ``RCH`` package feeding,
- ``first_clim`` and the general forcing-alignment logic.

It also stays analytically interpretable, which makes it easier to explain
than a natural basin case.

Files Used
----------

- MODFLOW-NWT base config:
  ``validation_cases/analytical/transient/linearized_unconfined_recharge_periodic_1d/config_modflownwt.toml``
- MODFLOW 6 overlay:
  ``validation_cases/analytical/transient/linearized_unconfined_recharge_periodic_1d/config_modflow6.toml``
- Case metadata:
  ``validation_cases/analytical/transient/linearized_unconfined_recharge_periodic_1d/metadata.toml``
- Gallery page with committed metrics:
  :doc:`../../capability_gallery/cases/linearized_unconfined_recharge_periodic_1d`

Minimal TOML Reading
--------------------

Common transient case
^^^^^^^^^^^^^^^^^^^^^

.. code-block:: toml

   [simulation.time]
   start_datetime = "2003-01-01 00:00:00"
   end_datetime = "2003-02-09 00:00:00"
   step_value = "1 day"

   [geographic.synthetic.grid]
   length_x = "100.0 m"
   length_y = "10.0 m"
   nx = 50
   ny = 5

   [domain.depth_model]
   type = "constant_thickness"
   thickness = "20.0 m"

   [flow]
   flow_regime = "transient"
   active_sinks_sources = ["recharge"]
   active_bc = ["west_side", "east_side"]
   param_list = ["K", "Ss", "Sy"]

   [flow.param.K.field_homogeneous]
   value = "1e-4 m/s"

   [flow.param.Ss.field_homogeneous]
   value = "1e-10 m-1"

   [flow.param.Sy.field_homogeneous]
   value = "0.10 -"

   [flow.ic]
   type = "custom"
   value = "10.0 m"

   [flow.bc.dirichlet.west_side]
   value = "10.0 m"

   [flow.bc.dirichlet.east_side]
   value = "10.0 m"

This defines a transient unconfined strip:

- 100 m long and 10 m wide,
- one single layer,
- fixed heads on both sides,
- homogeneous ``K``, ``Ss``, and ``Sy``,
- one initial head at 10 m everywhere.

Recharge forcing
^^^^^^^^^^^^^^^^

.. code-block:: toml

   [flow.sinks_sources.recharge]
   first_clim = "mean"
   negative_to_evt = true

   [[data.recharge.sources]]
   source = "synthetic"
   values = [5.0]
   amplitude = 5.0
   period_days = 10
   start_date = "2003-01-01"
   freq = "D"
   periods = 40
   runoff_ratio = 0.0

HydroModPy reads this as one synthetic recharge series in ``mm/day``:

.. math::

   R(t) = 5 + 5 \sin\left(2\pi t / 10\ \mathrm{days}\right)

sampled daily over 40 days.

The important project-level point is that recharge is still declared through
the common forcing contract, not as one solver-private MF6 input array.

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

   [modflow6.tgrid]
   firstpersteady = false

This keeps the support structured-style and explicitly says:

- stay transient from period 0,
- use one layer,
- use the standard MF6 structured-style support generated from the synthetic
  grid,
- and use the conservative ``COMPLEX`` IMS preset for the transient benchmark.

How The Forcing Becomes Stress-Period Recharge
----------------------------------------------

This is the key transient step.

1. The synthetic recharge manager generates one daily series in ``mm/day``.
2. The common forcing bridge normalizes it toward the groundwater runtime
   contract.
3. HydroModPy aligns the forcing to the simulation window and the stress
   periods.
4. The solver adapter feeds the result to ``RCHA`` in MF6 or ``RCH`` in NWT.

What makes this benchmark especially readable is that the forcing cadence and
the stress-period cadence match:

- source frequency: ``D``
- simulation step: ``1 day``
- simulation length: ``40`` daily periods

So the alignment is close to an identity mapping here: one forcing value is
effectively passed to one stress period.

That means this case does exercise the forcing path, but it does not stress the
``mean`` versus ``last`` aggregation difference. For that broader contract, see
:doc:`../hydrology/forcing-time-aggregation-and-first-clim`.

Why ``first_clim`` And ``negative_to_evt`` Barely Change This Benchmark
-----------------------------------------------------------------------

Two general-purpose recharge options are still active in the config:

- ``first_clim = "mean"``
- ``negative_to_evt = true``

They matter less here than they would in a more irregular forcing case.

``first_clim = "mean"``
^^^^^^^^^^^^^^^^^^^^^^^

The periodic forcing oscillates around ``5 mm/day`` and spans an integer number
of periods. Its mean is therefore also about ``5 mm/day``.

So the period-0 override is scientifically almost neutral in this benchmark.
The option is present because it belongs to the common HydroModPy forcing
contract, not because the case needs a strong warm-up correction.

``negative_to_evt = true``
^^^^^^^^^^^^^^^^^^^^^^^^^^

The synthetic recharge varies between ``0`` and ``10 mm/day``. It does not go
negative.

So the option is inert here:

- no recharge is clipped,
- no ``EVT`` package is activated from negative recharge,
- the benchmark remains a pure recharge-driven transient case.

This is actually useful pedagogically, because the page can mention the
general option without mixing in evapotranspiration semantics.

MF6 Package Assembly On This Case
---------------------------------

For the MODFLOW 6 branch, the main public package sequence is:

1. ``TDIS``
   built from the 40 daily periods declared in ``[simulation.time]``;
2. ``IMS``
   built from ``modflow6.runtime`` with the ``COMPLEX`` preset;
3. ``DISV``
   still used as the unified MF6 geometry export path;
4. ``IC``
   built from the uniform initial head ``10 m``;
5. ``NPF``
   built from homogeneous ``K`` and the convertible-cell path;
6. ``STO``
   built from ``Sy`` and ``Ss`` with transient flags active from period 0;
7. ``RCHA``
   fed from the resolved daily recharge schedule;
8. ``CHD``
   used for the west and east imposed-head boundaries;
9. ``OC``
   used to save heads and budgets for validation and postprocessing.

What this case does **not** activate:

- ``EVT`` from negative recharge,
- ``DRN``,
- ``WEL``,
- irregular DISV support,
- XT3D-specific behaviour.

What This Benchmark Is Actually Testing
---------------------------------------

Scientifically, the benchmark is not "MF6 in general". It is narrower.

It is mainly testing:

- transient storage response of a shallow unconfined strip,
- daily recharge propagation through time,
- consistency between the common HydroModPy forcing contract and the MODFLOW
  package feeding,
- and solver-family agreement against a linearized analytical transient
  reference.

It is **not** primarily testing:

- irregular meshes,
- complex boundary-condition mixes,
- drainage,
- or EVT routing.

Real Results Already Committed
------------------------------

The figures below are committed validation artifacts from real runs.

.. tab-set::

   .. tab-item:: MODFLOW-NWT

      .. figure:: /_static/capability_gallery/validation/linearized_unconfined_recharge_periodic_1d__modflownwt.png
         :alt: Linearized unconfined periodic recharge rendered with MODFLOW-NWT
         :width: 100%

         Real committed transient validation figure for the NWT branch.

      - Space-time RMSE: ``0.0078 m``
      - Space-time max abs error: ``0.0194 m``
      - Final-profile RMSE: ``0.0010 m``

   .. tab-item:: MODFLOW 6

      .. figure:: /_static/capability_gallery/validation/linearized_unconfined_recharge_periodic_1d__modflow6.png
         :alt: Linearized unconfined periodic recharge rendered with MODFLOW 6
         :width: 100%

         Real committed transient validation figure for the MF6 branch.

      - Space-time RMSE: ``0.0065 m``
      - Space-time max abs error: ``0.0167 m``
      - Final-profile RMSE: ``0.0009 m``

Those metrics come from
:doc:`../../capability_gallery/cases/linearized_unconfined_recharge_periodic_1d`.

Why This Page Matters More Than The Gallery Page Alone
------------------------------------------------------

The gallery page already proves that the run works and gives metrics.

This worked page adds the missing method reading:

- why the recharge series looks the way it does,
- why period alignment is simple in this benchmark,
- why ``EVT`` stays inactive even though ``negative_to_evt`` is enabled,
- why ``STO`` is part of the scientific story here but not in the steady
  Dupuit case.

How To Reproduce The Case
-------------------------

Run the benchmark directly with:

.. code-block:: powershell

   python -m validation_cases.analytical.transient.linearized_unconfined_recharge_periodic_1d.run_case --no-show --solver modflow6

or the NWT version with:

.. code-block:: powershell

   python -m validation_cases.analytical.transient.linearized_unconfined_recharge_periodic_1d.run_case --no-show --solver modflownwt

For Richer Transient Basin Illustrations
----------------------------------------

After this worked case, the next useful transient illustrations are the larger
MF6 gallery pages:

- :doc:`../../capability_gallery/cases/headwater_100km2_outlet_2_mf6_transient_reference`
- :doc:`../../capability_gallery/cases/modflow6_gmsh_mesh_catchment`

Those show:

- support overviews,
- basin maps,
- cumulative recharge/discharge curves,
- and richer postprocessed outputs.

Recommended Reading Order
-------------------------

1. :doc:`../hydrology/forcing-time-aggregation-and-first-clim`
2. :doc:`modflow-governing-equation-and-cvfd-formulation`
3. :doc:`modflow-package-semantics-and-boundary-conditions`
4. this worked transient case
5. :doc:`modflow6-vs-modflownwt-scientific-comparison`

Current Limitation
------------------

This case explains transient recharge well, but it still avoids:

- negative recharge actually routed to ``EVT``,
- drainage semantics,
- irregular-mesh transient MF6,
- natural-basin forcing heterogeneity.

Those should become later worked cases once the basic transient forcing path is
well documented.
