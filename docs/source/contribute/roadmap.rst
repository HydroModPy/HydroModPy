Roadmap
=======

The issue tracker is the live source of truth for work in flight. Tagged items
are under the
`roadmap label <https://github.com/HydroModPy/HydroModPy/issues?q=is%3Aissue+label%3Aroadmap>`_.
Shipped releases are in :doc:`/about/changelog`.

To influence it, open an issue with the ``roadmap`` label that describes the use
case and the constraint it lifts, or send a small focused pull request (see the
:doc:`handbook`).

What stays out of scope:

- A hosted web service. HydroModPy is a Python library. The JSON Schema export
  and the partial validator are the supported integration surface for a
  frontend (see :doc:`architecture/how-to/build-a-frontend`).
- A storage format beyond DuckDB, Zarr and Parquet.
- Compatibility shims and alias modules. A concept has one canonical name.
