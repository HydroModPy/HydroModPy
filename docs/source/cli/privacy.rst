hmp privacy
===========

The :command:`hmp privacy` family hosts privacy-preserving operations
on a workspace. Unlike :command:`hmp catalog delete`, every action here
leaves a JSON audit certificate so the deletion stays defensible after
the fact.

purge
-----

Synopsis: ``hmp privacy purge <sim_ref> [--reason <text>] [--workspace <path>]``

Hard-delete one simulation: the catalog row, the Zarr store, the
Parquet outputs, and any geographic_cache entry no longer referenced.
The action emits a certificate under
``<workspace>/.hmp/purge_certificates/<sim_id>.json`` capturing the
UTC timestamp, the simulation SHA-256 before deletion, the supplied
``--reason``, and the list of removed paths. The certificate is the
only auditable evidence that the simulation ever existed.

Example::

   hmp privacy purge 1a2b3c4d --reason "GDPR request 2026-05-19"

verify
------

Synopsis: ``hmp privacy verify [--workspace <path>]``

Walk the ``purge_certificates`` directory and check that every
certificate parses, that its referenced simulation is indeed absent
from the catalog, and that no orphan artefact survives on disk. Use it
on a schedule to detect tampering or partial purges.

Example::

   hmp privacy verify
