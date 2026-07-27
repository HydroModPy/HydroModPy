validity_frame
==============

``validity_frame`` is experimental observability tooling shipped as a
standalone distribution at ``validity_frame/src/validity_frame/``, next
to ``hydromodpy/`` and never inside it. It
records runtime metadata and can ingest JSONL capture files into a
DuckDB database for downstream inspection.

V1 status
---------

``validity_frame`` is outside the stable V1 public API. It remains
installed as an experimental package because the current code and
scripts use it directly, but it has no user-facing compatibility
guarantee. It must stay isolated from the modeling layers.

Role
----

The package captures execution context, probes runtime and hardware
metadata, and ingests JSONL records into an observability DuckDB file.
It does not own scientific outputs, project catalogs or user-facing
workflow state.

Sub-modules
-----------

- ``validity_frame/auto_capture/`` -- recorder, context and collector
  utilities.
- ``validity_frame/probes/`` -- runtime, hardware, solver and system
  probes.
- ``validity_frame/loader.py`` -- JSONL-to-DuckDB ingestion helper.
- ``validity_frame/validity.py`` -- the capture entry point.

Sequence diagram
----------------

Runtime envelope showing capture before, during and after simulation:

.. uml:: ../process/diagrams/validity_frame_runtime_sequence.puml

Storage contract
----------------

JSONL and the observability DuckDB file are experimental sidecars. They
are not canonical scientific outputs. The allowed stable V1 stores
remain DuckDB project/catalog databases, Zarr field stores and Parquet
tabular outputs, as described in :doc:`../storage-layout` and
:doc:`../artifact-policy`.

Layer-matrix neighbours
-----------------------

- Allowed targets: ``validity_frame`` only.
- Allowed sources: none in the stable modeling DAG.

See also
--------

- :doc:`../artifact-policy` for sidecar artifact categories.
- :doc:`../layered-architecture` for the matrix contract.
