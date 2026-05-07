Recipes
=======

.. note::
   Cookbook of common HydroModPy configuration tasks. Each recipe gives a
   minimal TOML snippet plus a pointer to the relevant sections in
   :doc:`index`.

.. contents:: On this page
   :local:
   :depth: 1

Run a minimal synthetic 1D Dupuit case
--------------------------------------

Smallest viable project: synthetic flat aquifer, steady state, no external
data, no figures by default. Great as a smoke test.

.. code-block:: toml

   [workflow]
   mode = "simulation"

   [simulation]
   name = "smoke_test"

   [[simulation.process]]
   id = "flow"
   type = "flow"
   solvers = ["modflownwt"]

   [workspace]
   project_root = "."

   [geographic]
   source_mode = "synthetic"

   [geographic.synthetic]
   case_id = "dupuit_smoke"

   [geographic.synthetic.grid]
   length_x = "200.0 m"
   length_y = "10.0 m"
   nx = 40
   ny = 1

   [geographic.synthetic.topography]
   kind = "flat"
   base_elevation = 20.0

   [domain.depth_model]
   type = "constant_thickness"
   thickness = "20.0 m"

   [flow]
   flow_regime = "steady"
   active_sinks_sources = ["recharge"]
   active_bc = ["west_side", "east_side"]
   param_list = ["K"]

   [flow.param.K.field]
   id = "K"
   kind = "homogeneous"

   [flow.param.K.field]
   value = "1e-4 m/s"

   [flow.bc.dirichlet.west_side]
   type = "dirichlet"
   value = "5.0 m"

   [flow.bc.dirichlet.east_side]
   type = "dirichlet"
   value = "5.0 m"

   [data]
   types = ["recharge"]

   [[data.recharge.sources]]
   source = "synthetic"
   values = [3.0]
   runoff_ratio = 0.0

See :doc:`flow`, :doc:`geographic`, :doc:`domain`, :doc:`data`.

Load synthetic recharge
-----------------------

Generate a constant or stepped synthetic recharge series without any
external file.

.. code-block:: toml

   [data]
   types = ["recharge"]

   [[data.recharge.sources]]
   source = "synthetic"
   values = [0.95]
   start_date = "2000-01-01"
   freq = "YE"
   periods = 1
   runoff_ratio = 0.0

Set ``runoff_ratio`` to send a fraction of the recharge to surface
runoff before reaching the saturated zone.

See :doc:`data`.

Load recharge from a CSV chronicle
----------------------------------

Use this when daily/hourly recharge is exported from a separate
hydrological model.

.. code-block:: toml

   [[data.recharge.sources]]
   source = "custom"
   path = "../../data/recharge/daily.csv"

   [flow.sinks_sources.recharge]
   first_clim = "mean"
   negative_to_evt = true
   units = "mm/day"

The ``first_clim`` field controls the period-0 fallback when the
chronicle starts after the simulation start date.

See :doc:`flow`, :doc:`data`.

Add a pumping well
------------------

Pumping wells live under ``[flow.sinks_sources.wells.<id>]`` and accept
either direct cell indices or projected coordinates.

.. code-block:: toml

   [flow.sinks_sources.wells.well_pumping_north]
   location_mode = "absolute_xy"
   layer = 0
   x = 327800.0
   y = 6777900.0
   flux = -1.5e-3
   units = "m3/s"
   description = "Production well, north of the outlet"

Set ``flux`` to a list to drive a per-stress-period schedule, or use
``forcing.kind = "csv"`` to read a chronicle file.

See :doc:`flow`.

Define mixed boundary conditions
--------------------------------

Combine Dirichlet sides with a top-cell drainage:

.. code-block:: toml

   [flow]
   active_bc = ["west_side", "east_side", "drainage"]

   [flow.bc.dirichlet.west_side]
   type = "dirichlet"
   value = "5.0 m"

   [flow.bc.dirichlet.east_side]
   type = "dirichlet"
   value = "5.0 m"

   [flow.bc.cauchy.drainage]
   application_domain = "top"
   type = "cauchy"
   value = 0.0
   units = "m2/s"

The drainage entry routes top-cell head excess back to the surface via a
Cauchy package.

See :doc:`flow`.

Force the MODFLOW solver grid resolution
----------------------------------------

By default the solver grid follows the geographic support. Override the
planar shape and layering explicitly when you want a specific run.

.. code-block:: toml

   [modflow6.sgrid.planar]
   mode = "resample_to_shape"
   nx = 80
   ny = 80
   resampling = "bilinear"

   [modflow6.sgrid.vertical]
   nlay = 5
   genmtd_lay = "decay"
   lay_decay = 1.5

Use :doc:`modflownwt` for MODFLOW-NWT projects with the same key
structure.

See :doc:`modflow6`, :doc:`modflownwt`.

Switch between steady and transient flow
----------------------------------------

The flow regime drives both stress-period generation and IC handling.

.. code-block:: toml

   [flow]
   flow_regime = "transient"

   [flow.ic]
   type = "top_offset"
   value = "1.0 m"

   [simulation.time]
   start_date = "2000-01-01"
   end_date = "2010-12-31"
   freq = "ME"

For a steady run drop ``[simulation.time]`` and switch ``flow_regime`` to
``"steady"``. The transient case requires a valid ``[flow.ic]`` block.

See :doc:`flow`, :doc:`simulation`.

Calibrate a hydraulic-conductivity prior
----------------------------------------

Calibration takes over the ``[flow]`` payload and overrides the requested
parameters at runtime.

.. code-block:: toml

   [workflow]
   mode = "calibration"

   [calibration]
   algorithm = "cma"
   max_iterations = 50

   [[calibration.parameters]]
   path = "flow.param.K.field.value"
   prior = "log_uniform"
   bounds = ["1e-6 m/s", "1e-2 m/s"]

   [[calibration.objectives]]
   id = "kge_discharge"
   weight = 1.0

See :doc:`calibration`.

Activate the capability gallery
-------------------------------

Re-publish a project as a gallery card with tagged figures and metadata.

.. code-block:: toml

   [workflow]
   mode = "analysis"

   [analysis.capability_gallery]
   enabled = true
   slug = "my_case_2d"
   title = "Two-dimensional Dupuit aquifer"
   tags = ["dupuit", "2d", "synthetic"]

See :doc:`analysis`.

See also
--------

- :doc:`index` for the cards-based overview of every section
- :doc:`config_index` for a flat alphabetical index of every TOML path
- :doc:`complete_toml` for a copy-pasteable annotated template
- :doc:`schema_explorer` for the interactive JSON Schema viewer
