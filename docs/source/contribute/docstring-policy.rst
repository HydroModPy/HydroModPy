Docstring policy
================

The Python API reference is generated from the code. ``tools/docs/api_registry.py`` reads
``hydromodpy.__all__``, the signatures and the docstrings, and ``docs/source/_ext/hmp_api.py``
renders them with autodoc and the NumPy docstring style (``napoleon``). There is no manifest
to maintain. To put an object in the reference, export it from ``hydromodpy/__init__.py``
(through ``_lazy.py``) and write its docstring. To change what a page says, change the
docstring.

What to document
----------------

Document an object when it is one of these:

- a user entry point;
- a scientific component that can be called directly;
- a developer contract needed to extend the workflow engine;
- a configuration model that appears in TOML or JSON Schema. For a model, the description of
  each field is the documentation (:doc:`architecture/how-to/add-a-config-field`).

Do not document every helper. A private helper stays private unless it becomes part of a clear
external workflow.

Docstring shape
---------------

Use simple technical English. Say what the object does before how it does it.

.. code-block:: python

   def run(config: str | Path, **kwargs: Any) -> Run | None:
       """Run a HydroModPy workflow from a TOML file.

       Parameters
       ----------
       config
           Path to a TOML file with a ``workflow`` field.
       **kwargs
           Runtime options forwarded to the selected workflow.

       Returns
       -------
       Run or None
           Persisted run object for simulation workflows. Other workflows may
           return their own summary type.

       Raises
       ------
       ConfigError
           Raised when the TOML file cannot be resolved or validated.
       """

For user and scientific objects, use these sections:

- ``Parameters`` for inputs that users can control;
- ``Returns`` for the concrete object or data shape;
- ``Raises`` for errors that a caller can handle;
- ``Examples`` for one short runnable pattern (mark one that needs data with
  ``# doctest: +SKIP``);
- ``See Also`` for nearby public objects;
- ``Notes`` only for scientific assumptions or important implementation limits.

Layer rules
-----------

A user docstring describes behaviour in workflow terms and avoids pipeline internals unless the
user must know them. A scientific docstring gives units, array shape, coordinate convention,
solver assumptions and numerical limits when they affect results. A developer docstring names
the contract and the expected caller. It may mention internal state, and stays short.

One import path
---------------

Each documented symbol has one canonical import path, the one in ``hydromodpy.__all__``. Do
not document both a package-level lazy export and the implementation class unless there is a
clear reason.

Checks
------

CI builds the reference with the rest of the site (``make -C docs html-strict``), so a docstring
that Sphinx cannot parse stops the build. The ``unit`` job of ``Main Gate`` also runs the
doctests of the modules that carry examples (``pytest --doctest-modules`` on a list kept in
``main-ci.yml``). ``tests/unit/docs/`` pins other facts of the documentation, such as the fact
that every ``hmp`` command named in a page exists.

A tutorial does not belong in a docstring. It belongs in the guides or the theory pages.
