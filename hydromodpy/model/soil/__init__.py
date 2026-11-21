"""The daily soil reservoir kernel that turns precipitation and ETP into recharge.

MODFLOW 6 only. ``kernel.py`` holds the shell of the reservoir in numpy (sealed
share, curve number, bypass, transit, snow, seasonal kc), ``laws.py`` the storage
law of each method (``fao56``, ``thornthwaite``, ``dingman``, ``edijatno_michel``)
and ``etp.py`` the ETP formulas a ``[data.etp] formula`` names (``oudin``,
``hamon``). The TOML surface and the runs on the SAFRAN grids a project loads are
forcings, in ``model/forcing/soil_config.py``, ``soil_grids.py``,
``soil_columns.py``, ``soil_forcing.py``, ``soil_budget.py`` and
``soil_ru_budget.py``. This file has no imports on purpose, so the kernel reads on
its own.
"""
