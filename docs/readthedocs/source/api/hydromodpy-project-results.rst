Project, Run, and Catalog API
=============================

Programmatic surfaces for opening a workspace, driving project workflows, and
reading persisted simulation results.

Facade functions
----------------

.. autosummary::
   :nosignatures:
   :toctree: generated/project-results

   ~hydromodpy.open
   ~hydromodpy.run
   ~hydromodpy.calibrate
   ~hydromodpy.compare
   ~hydromodpy.doctor

Project and run objects
-----------------------

.. autosummary::
   :nosignatures:
   :toctree: generated/project-results

   ~hydromodpy.project.Project
   ~hydromodpy.results.run.Run
   ~hydromodpy.results.catalog.SimulationCatalog
   ~hydromodpy.results.simulation_group.SimulationGroup
   ~hydromodpy.results.config.ResultsConfig

Export helpers
--------------

.. autosummary::
   :nosignatures:
   :toctree: generated/project-results

   ~hydromodpy.results.exporters.csv.export_csv
   ~hydromodpy.results.exporters.geotiff.export_geotiff
   ~hydromodpy.results.exporters.netcdf.export_netcdf
   ~hydromodpy.results.exporters.shapefile.export_shapefile
   ~hydromodpy.results.exporters.vtu.export_vtu
   ~hydromodpy.results.exporters.hmp_package.export_hmp_package
