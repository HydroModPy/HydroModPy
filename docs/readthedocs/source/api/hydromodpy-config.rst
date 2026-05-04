Configuration API
=================

Configuration parameters are Pydantic models loaded from TOML files. Fields are
validated at instantiation time: type, value constraints, allowed literals, and
cross-field rules.

.. note::

   The historical application-level imports under ``hydromodpy.core`` and
   ``hydromodpy.core.config`` have been removed. Import the top-level
   configuration from ``hydromodpy.config``.

.. code-block:: python

   from hydromodpy.config import HydroModPyConfig

   cfg = HydroModPyConfig.from_toml("config.toml")
   cfg.workspace.catch_name      # validated str
   cfg.geographic.catch_def      # validated Literal

Root configuration
------------------

.. autopydantic_model:: hydromodpy.config.hydromodpy_config.HydroModPyConfig
   :members:
   :undoc-members:
   :member-order: bysource
   :no-index:

Workspace configuration
-----------------------

.. autopydantic_model:: hydromodpy.core.workspace.config.WorkspaceConfig
   :members:
   :undoc-members:
   :member-order: bysource
   :no-index:

Geographic configuration
------------------------

.. autopydantic_model:: hydromodpy.spatial.geographic.geographic_config.GeographicConfig
   :members:
   :undoc-members:
   :member-order: bysource
   :no-index:
