# Developer notes (versioned, not published)

This folder holds internal documentation that is tracked by git but not
published on Read the Docs. Use it for everything that contributors need
to keep around but that does not belong in the public docs.

## Subfolders

- `decisions/`
  Architecture Decision Records (ADRs), refactor plans, dated structuring
  decisions. One file per decision, prefer a `YYYY-MM-DD-<slug>.md` name
  for new ADRs.
- `diagnostics/`
  Investigation notes, performance audits, benchmark analyses,
  reproduction reports. One file per diagnostic.
- `drafts/`
  Work in progress, perspective notes, exploratory writeups not yet
  promoted to a decision or to the public docs.
- `legacy/`
  Historical documents preserved for traceability. Read-only in spirit,
  no new files.

## Publication rule

Move a file to `docs/source/developer/` (or another section under
`docs/source/`) only when it becomes a stable, contributor-facing
reference. Otherwise it stays here.
