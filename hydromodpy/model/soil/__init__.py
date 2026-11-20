"""The daily soil reservoir kernel that turns precipitation and ETP into recharge.

MODFLOW 6 only. ``kernel.py`` holds the equations in numpy. The TOML surface and
the runs on the SAFRAN grids a project loads are forcings, in
``model/forcing/soil_config.py``, ``soil_grids.py``, ``soil_columns.py``,
``soil_forcing.py`` and ``soil_budget.py``. This file has no imports on purpose,
so the kernel reads on its own.
"""
