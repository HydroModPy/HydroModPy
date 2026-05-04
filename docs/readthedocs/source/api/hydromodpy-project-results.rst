Project And Results API
=======================

Generated reference for the main user API: workspace opening, project
execution, persisted runs, catalogs, simulation groups, and export helpers.

Facade functions
----------------

.. autosummary::
   :nosignatures:
   :toctree: generated/project-results

   ~hydromodpy.open
   ~hydromodpy.run
   ~hydromodpy.calibrate
   ~hydromodpy.compare
   ~hydromodpy.compare_pair
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
