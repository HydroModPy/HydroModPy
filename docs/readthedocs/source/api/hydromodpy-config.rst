hydromodpy.core.config - Parameter Contracts
============================================

All configuration parameters are defined as :class:`~pydantic.BaseModel` classes
loaded from a TOML file. Each field is validated at instantiation time: type,
value constraints (min / max, allowed literals ...) and cross-field rules are
enforced automatically - a :class:`~pydantic.ValidationError` is raised with a
precise message when a contract is violated.

.. code-block:: python

   from hydromodpy.core.config import HydroModPyConfig

   cfg = HydroModPyConfig.from_toml("config.toml")
   cfg.workspace.catch_name      # validated str
   cfg.geographic.catch_def      # validated Literal

----

hydromodpy.core.config.hydromodpy_config
----------------------------------------

.. autopydantic_model:: hydromodpy.core.config.hydromodpy_config.HydroModPyConfig
   :members:
   :undoc-members:
   :member-order: bysource
   :no-index:

----

hydromodpy.core.workspace.config
--------------------------------

.. autopydantic_model:: hydromodpy.core.workspace.config.WorkspaceConfig
   :members:
   :undoc-members:
   :member-order: bysource
   :no-index:

----

hydromodpy.spatial.geographic.geographic_config
------------------------------------------------

.. autopydantic_model:: hydromodpy.spatial.geographic.geographic_config.GeographicConfig
   :members:
   :undoc-members:
   :member-order: bysource
   :no-index:
