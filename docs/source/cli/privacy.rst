hmp privacy
===========

The :command:`hmp privacy` family hosts privacy-preserving operations on a
project. Unlike :command:`hmp catalog delete`, which is reversible, every
action here is final and leaves a JSON certificate so the deletion stays
defensible after the fact.

purge
-----

Synopsis: ``hmp privacy purge <ref> [--reason <text>] [--workspace <path>]
[-y] [--archive-pii]``

Hard-delete one run: its index rows, its Zarr store, its Parquet outputs,
and any geographic cache entry no longer referenced.

The action writes a certificate at
``<workspace>/.hmp/purge_certificates/<sim_id>.json``, with mode ``0o600``,
holding the simulation id, the UTC timestamp, the operator, the supplied
``--reason`` and a SHA-256 snapshot taken before deletion. The command also
prints the removed paths and the certificate path. That certificate, plus
the ``sim.purge`` rows in the audit log, is the only remaining evidence
that the run ever existed.

Example::

   hmp privacy purge 1a2b3c4d --reason "GDPR request 2026-05-19" -y

verify
------

Synopsis: ``hmp privacy verify <certificate> [--strict]``

Verify one purge certificate: parse it and check its payload. ``--strict``
additionally requires the POSIX ``0o600`` permissions the purge sets, which
is the tamper signal to gate in CI.

Example::

   hmp privacy verify .hmp/purge_certificates/<sim_id>.json --strict
