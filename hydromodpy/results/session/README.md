# results/session

This folder answers what a calibration session leaves on disk in `sessions/<case>/`, and how it is read back.
It holds the formats of the files and the read-only view `Session`. The view reads the directory alone, never
the index, so a session copied out of its project reads the same.

## How the work flows

1. The search writes `session.json`, the descriptor of the session (`descriptor.py`).
2. Each trial is appended as one line to `trials.jsonl` (`journal.py`). The trial number is unique in the session.
   A trial written twice, started then completed, is one trial and the last line wins.
3. A staged search writes one descriptor per phase in `phases/<phase>/session.json` (`phase.py`). A phase has no
   journal of its own. Its trials are the lines of the session journal that carry its name.
4. The scored series of a trial go to `trial_series/trial-NNNNNN.parquet` (`trial_series.py`).
5. `Session` (`view.py`) reads all of it. It gives the trials, the best trial, the phases, the frozen
   configuration and the run the best trial was promoted to.
6. The indexer reads the same files to fill the session tables of the index.

## The folder map

```text
session/
├── descriptor.py    SessionDescriptor, SessionCase, SessionProtocol, bounds and best trial
├── journal.py       trials.jsonl, append_trial, read_trials, next_trial_number
├── phase.py         PhaseDescriptor, write_phase, read_phase, list_phases
├── trial_series.py  write_trial_series, read_trial_series
└── view.py          Session, the read-only view of one session directory
```

A session of one case has one best run. On a session of several cases, `best` refuses and `best_by_case` holds
them all.

## Where to add what

| To add | Where |
|--------|-------|
| a field of the session descriptor | `descriptor.py`, with a version change if the format changes |
| a field of a trial line | `TrialLine` in `journal.py` |
| something a phase records | `PhaseDescriptor` in `phase.py` |
| a new read of a session | a property of `Session` in `view.py` |
| a column of the trial frame | `TRIAL_COLUMNS` in `view.py` |
