hydromodpy.config — Parameter contracts
========================================

.. note::

   All configuration parameters are defined as :class:`~pydantic.BaseModel` classes.
   Each field is validated at instantiation time — types, constraints (min / max,
   allowed literals …) and cross-field rules are all enforced automatically.
   A :class:`~pydantic.ValidationError` is raised with a precise message when any
   contract is violated.

Usage
-----

.. code-block:: python

   from hydromodpy.config import HydroModPyConfig

   # Load and validate from a TOML file
   cfg = HydroModPyConfig.from_toml("config.toml")

   # Direct instantiation
   from hydromodpy.watershed.initializing_config import InitializingConfig
   from hydromodpy.watershed.geographic_config    import GeographicConfig

   init = InitializingConfig(
       catch_name   = "my_watershed",
       out_dir_path = "/data/results",
       data_path    = "/data/inputs",
   )
   geo = GeographicConfig(
       catch_def    = "from_outlet_coord",
       dem_init_path= "/data/dem.tif",
       x_outlet     = 348500.0,
       y_outlet     = 6789000.0,
       snap_dist    = 200,
       buff_area    = 5.0,
   )


Top-level model
---------------

.. autopydantic_model:: hydromodpy.config.hydromodpy_config.HydroModPyConfig
   :model-show-json: False
   :model-show-config-summary: False
   :model-show-validator-summary: False
   :model-show-field-list: True
   :field-show-constraints: True
   :field-show-default: True
   :member-order: bysource


----


Initializing parameters
------------------------

.. admonition:: Purpose

   Defines project layout: the catchment name, the root output directory, and the
   input data folder.  These three paths drive every subsequent step.

.. autopydantic_model:: hydromodpy.watershed.initializing_config.InitializingConfig
   :model-show-json: False
   :model-show-config-summary: False
   :model-show-validator-summary: False
   :model-show-field-list: True
   :field-show-constraints: True
   :field-show-default: True
   :member-order: bysource


----


Geographic parameters
---------------------

.. admonition:: Purpose

   Controls how the model domain and the watershed boundary are delineated from a
   digital elevation model.  The four available modes are mutually exclusive — the
   model validator automatically checks that all required fields are supplied for
   the chosen mode.

Catchment definition modes
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. tab-set::

   .. tab-item:: ``dem``

      Simplest mode: the model domain is read directly from the DEM raster.

      *Required* — ``dem_init_path``

   .. tab-item:: ``txt``

      Model domain from an XYZ point-cloud text file that is rasterised on the fly.

      *Required* — ``dem_init_path``, ``cell_size``

   .. tab-item:: ``from_outlet_coord``

      Automatically delineates the watershed from a single outlet coordinate.

      *Required* — ``dem_init_path``, ``x_outlet``, ``y_outlet``, ``snap_dist``, ``buff_area``

   .. tab-item:: ``from_polyg_shp``

      Uses an existing watershed polygon shapefile to clip the domain.

      *Required* — ``dem_init_path``, ``polyg_shp_path``, ``buff_area``

Field reference
~~~~~~~~~~~~~~~

.. autopydantic_model:: hydromodpy.watershed.geographic_config.GeographicConfig
   :model-show-json: False
   :model-show-config-summary: False
   :model-show-validator-summary: True
   :model-show-field-list: True
   :field-show-constraints: True
   :field-show-default: True
   :member-order: bysource
