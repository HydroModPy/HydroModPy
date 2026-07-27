hmp audit
=========

The :command:`hmp audit` family inspects the audit log: the append-only
ledger inside the project index that records every mutation (run
registration, metric write, tag, trash, purge) as a hash-chained entry.
Every action auto-detects the project; pass ``--workspace`` to point at a
different one.

list
----

Synopsis: ``hmp audit list [--since <date>] [--limit <n>] [--workspace <path>]``

Print recent audit log entries in reverse chronological order. ``--since``
takes an ISO date or timestamp lower bound. ``--limit`` caps the number
of rows (default 50). Useful before a :command:`hmp catalog gc` or a
:command:`hmp privacy purge` to confirm what has been touched lately.

Example::

   hmp audit list --since 2026-01-01 --limit 20

verify
------

Synopsis: ``hmp audit verify [--strict] [--workspace <path>]``

Replay the audit chain hash and report any gap or mismatch. On an intact
log it prints ``audit_log hash chain verifies``. ``--strict`` turns
warnings into a non-zero exit code, suitable for CI gates that guard the
integrity of an archived project.

Example::

   hmp audit verify --strict

The audit log has no retention rule: it grows with the project and is
never pruned. Run retention is a separate matter, handled by
``hmp catalog gc`` (see :doc:`catalog`).
