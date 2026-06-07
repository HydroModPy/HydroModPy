hmp audit
=========

The :command:`hmp audit` family inspects the workspace audit log: the
append-only ledger that records every catalog mutation (insert, update,
delete) with a hash-chained entry. Both actions auto-detect the
catalog; pass ``--workspace`` to point at a different project.

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

Replay the audit chain hash and report any gap or mismatch. ``--strict``
turns warnings into a non-zero exit code, suitable for CI gates that
guard the integrity of an archived workspace.

Example::

   hmp audit verify --strict
