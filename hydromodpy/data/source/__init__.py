"""The data-source port and its registry.

``port`` holds the Protocol and its value types, a :class:`FetchRequest` and a
:class:`FetchResult`, and loads nothing heavier than the exception module: a
source needs no import of HydroModPy beyond it and ``data.contracts``. ``registry``
holds ``data_sources``, keyed on the section a source serves and the word a
document writes, and it is the surface a third-party source registers on.

Nothing is re-exported here: import each name from the module that defines it
(the facade ``hydromodpy/__init__.py`` is the one exception this repository
carries), and the source classes are resolved through the registry rather than
imported. See ``README.md`` in this folder for the contract of the port.
"""
