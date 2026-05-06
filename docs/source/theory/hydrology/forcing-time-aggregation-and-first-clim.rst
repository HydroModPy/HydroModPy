Forcing Time Aggregation And First_Clim
=======================================

Purpose
-------

This page explains one subtle but important part of the HydroModPy forcing
contract:

- how time series become one value per solver stress period,
- and how the historical ``first_clim`` convention can still modify period 0.

This is scientifically important because two runs may use the same nominal
recharge or ETP chronicle while still differing in the effective values passed
to the solver if:

- the simulation window is different,
- the stress-period partition is different,
- the aggregation rule is different,
- or ``first_clim`` changes the first period.

Current Code Anchors
--------------------

The current public behaviour is mainly implemented in:

- ``hydromodpy/physics/forcing/time_alignment.py``
- ``hydromodpy/physics/flow/time_forcing.py``
- ``hydromodpy/physics/flow/structure_binders.py``
- ``hydromodpy/solver/modflow6/flow_to_modflow_adapter.py``
- ``hydromodpy/solver/modflow_nwt/nwt/flow_to_modflow_adapter.py``

The important point is that time aggregation happens before MODFLOW package
assembly. Package semantics then consume already aligned process payloads.

Two Different Steps
-------------------

HydroModPy currently separates two temporal operations that are easy to mix.

Step 1. Align a chronicle to stress periods
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Non-constant forcing declarations are first resolved against
``[simulation.time]`` so that the runtime obtains one value per solver period.

Step 2. Apply the historical ``first_clim`` convention
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Recharge and ETP payloads may then still modify period 0 through
``first_clim``.

This second step is not the same thing as period aggregation. It is a project
convention layered on top of it.

Stress-Period Alignment Rules
-----------------------------

For non-constant forcing resolved from CSV, HydroModPy currently supports two
public aggregation modes.

``aggregate = "mean"``
^^^^^^^^^^^^^^^^^^^^^^

This is the general period-average path.

The current rule is:

- one output value per stress period,
- arithmetic mean of all samples in ``[period_start, period_end)``,
- if the interval contains no sample, reuse the latest available value before
  the period end.

This is the main "climatic forcing to stress-period forcing" contract used by
the generic alignment helper.

``aggregate = "last"``
^^^^^^^^^^^^^^^^^^^^^^

This is a step-like hold-value path.

The current rule is:

- one output value per stress period,
- use the latest value available at or before the start of the period.

This is not the same thing as the mean path with fallback. It behaves more like
a piecewise-constant driver carried across the simulation window.

Why The Distinction Matters
---------------------------

The difference between ``mean`` and ``last`` is not cosmetic.

- ``mean`` is usually appropriate for period-mean climatic forcing,
- ``last`` is more appropriate when the source series should behave like a
  state held until update.

The same input chronicle can therefore lead to two different solver forcings
depending on the chosen aggregation mode.

What ``first_clim`` Actually Does
---------------------------------

After the forcing is aligned to solver periods, HydroModPy may still modify the
first period of recharge or ETP payloads.

Current accepted values are:

- ``"mean"``
- ``"first"``
- one explicit numeric value

Current meaning:

- ``"mean"``:
  use the mean of the series for period 0,
- ``"first"``:
  keep the first resolved value,
- numeric:
  impose one explicit scalar on period 0.

This convention exists in both MODFLOW-family and Boussinesq paths. It is part
of HydroModPy history and should be described as a warm-up or initialization
policy, not as a property of MODFLOW itself.

Homogeneous Versus Heterogeneous Forcing
----------------------------------------

The same temporal logic exists in both broad spatial cases.

Homogeneous forcing
^^^^^^^^^^^^^^^^^^^

For scalar or sequence payloads:

- the series is aligned to the simulation window,
- then ``first_clim`` may alter period 0,
- then the solver adapter turns the result into package payloads.

Heterogeneous forcing
^^^^^^^^^^^^^^^^^^^^^

For field-based or point-to-grid heterogeneous forcing:

- the data are first discretized to the solver support,
- then period 0 may still be adjusted by ``first_clim`` on the resulting
  per-cell arrays,
- then the solver package receives one per-period spatial payload.

So the temporal policy is not limited to homogeneous recharge.

Relation To Negative Recharge And EVT
-------------------------------------

The current runtime may also route negative recharge to ``EVT``.

That happens after the forcing has become one value per period and after the
relevant period-0 policy has been resolved.

The scientific reading should therefore be:

1. define the time-aligned recharge history,
2. possibly adjust period 0 through ``first_clim``,
3. only then split negative recharge into the EVT path if requested.

This ordering matters in transient comparisons.

What Should Be Reported
-----------------------

If a study uses transient recharge, ETP, boundary stages, or well chronicles,
its method note should state:

- the simulation window,
- the stress-period partition,
- the forcing aggregation mode,
- whether ``first_clim`` is left at ``"mean"``, changed to ``"first"``, or set
  explicitly,
- whether negative recharge is routed to EVT.

Without those controls, two transient runs can look comparable while being
driven by slightly different effective forcings.

Related Pages
-------------

- :doc:`hydrological-forcing-chain`
- :doc:`recharge-and-surface-exchange-semantics`
- :doc:`stream-ocean-and-drainage-semantics`
- :doc:`../solvers/modflow-package-semantics-and-boundary-conditions`
- :doc:`../../user_guide/concepts/comparison-workflow`

Current Limitation
------------------

HydroModPy now has a public explanation of the current aggregation contract,
but it still lacks one worked documentation example that shows one real CSV
chronicle, the resulting stress periods, and the final per-period values fed to
two different solver families.
