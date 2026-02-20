hydromodpy.config — Parameter contracts
========================================

All configuration parameters are defined as :class:`~pydantic.BaseModel` classes
loaded from a TOML file.  Each field is validated at instantiation time: type,
value constraints (min / max, allowed literals …) and cross-field rules are
enforced automatically — a :class:`~pydantic.ValidationError` is raised with a
precise message when a contract is violated.

.. code-block:: python

   from hydromodpy.config import HydroModPyConfig

   cfg = HydroModPyConfig.from_toml("config.toml")
   cfg.initializing.catch_name   # validated str
   cfg.geographic.catch_def      # validated Literal

----

hydromodpy.config.hydromodpy\_config
--------------------------------------

.. automodule:: hydromodpy.config.hydromodpy_config
   :members:
   :undoc-members:
   :member-order: bysource

----

hydromodpy.watershed.initializing\_config
------------------------------------------

.. automodule:: hydromodpy.watershed.initializing_config
   :members:
   :undoc-members:
   :member-order: bysource

----

hydromodpy.watershed.geographic\_config
-----------------------------------------

.. automodule:: hydromodpy.watershed.geographic_config
   :members:
   :undoc-members:
   :member-order: bysource
