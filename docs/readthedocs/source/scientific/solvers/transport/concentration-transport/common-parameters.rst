Common Concentration Parameters
===============================

``transport/mt3dms`` and ``transport/modflow6gwt`` currently share the same
high-level concentration parameter family.

The shared parameter shape does not mean the two backends are numerically
identical. It means HydroModPy exposes the same project-level vocabulary for
species identity, initial concentration, input concentration, dispersion,
diffusion, and decay.

Shared Parameter Block Shape
----------------------------

.. code-block:: toml

   [transport.mt3dms.parameters]
   spc_name = "NO3"
   sconc_init = 0.0
   sconc_input = 30.0
   disp_long = 10.0
   disp_transh = 0.1
   disp_transv = 0.01
   diffu_coeff = 0.0
   rate_decay = 0.0

   [transport.modflow6gwt.parameters]
   spc_name = "NO3"
   sconc_init = 0.0
   sconc_input = 30.0
   disp_long = 10.0
   disp_transh = 0.1
   disp_transv = 0.01
   diffu_coeff = 0.0
   rate_decay = 0.0

Parameter Semantics
-------------------

.. list-table::
   :header-rows: 1
   :widths: 28 18 54

   * - Parameter
     - Typical role
     - Meaning
   * - ``spc_name``
     - Species identity.
     - Name of the transported species.
   * - ``sconc_init``
     - Initial state.
     - Initial concentration value.
   * - ``sconc_input``
     - Source concentration.
     - Concentration associated with incoming water.
   * - ``disp_long``
     - Dispersion.
     - Longitudinal dispersivity.
   * - ``disp_transh``
     - Dispersion.
     - Horizontal transverse dispersivity ratio.
   * - ``disp_transv``
     - Dispersion.
     - Vertical transverse dispersivity ratio.
   * - ``diffu_coeff``
     - Diffusion.
     - Molecular diffusion coefficient.
   * - ``react_order``
     - Reaction.
     - Optional reaction order for MT3DMS-compatible semantics.
   * - ``rate_decay``
     - Reaction.
     - Decay-rate value.
   * - ``plot_conc``
     - Outputs.
     - Enable concentration plotting outputs where available.

Interpretation Rule
-------------------

When concentration results differ, do not look only at this parameter block.
Also document:

- upstream flow solver and mesh;
- stress-period setup;
- recharge and boundary semantics;
- solver package route;
- output extraction and comparison metric.

Related Pages
-------------

- :doc:`mt3dms`
- :doc:`modflow6gwt`
- :doc:`method-choice`
