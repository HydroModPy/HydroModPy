Numerical Engines And Postprocess
=================================

Numerical engines and result-access surfaces used by HydroModPy to run
groundwater flow, particle tracking, and transport simulations.

Flow Engines
------------

.. autosummary::
   :nosignatures:
   :toctree: generated/modeling

   ~hydromodpy.solver.modflow_nwt.modflow.Modflow
   ~hydromodpy.solver.modflow6.modflow6.Modflow6
   ~hydromodpy.solver.boussinesq.boussinesq.Boussinesq

Transport Engines
-----------------

.. autosummary::
   :nosignatures:
   :toctree: generated/modeling

   ~hydromodpy.solver.modflow_nwt.modpath.Modpath
   ~hydromodpy.solver.modflow_nwt.mt3dms.Mt3dms
   ~hydromodpy.solver.modflow6.modflow6.Modflow6Transport
   ~hydromodpy.solver.modflow_common.masstransfer.Masstransfer

Result access is documented separately in
:doc:`project, run, and catalog API <hydromodpy-project-results>`.
