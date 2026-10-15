"""The formats of a calibration session directory, ``sessions/<case>/``.

A session is what a search evaluated: ``session.json`` (its descriptor,
:mod:`~hydromodpy.results.session.descriptor`), ``trials.jsonl`` (its journal,
one trial per line with a number unique in the session,
:mod:`~hydromodpy.results.session.journal`) and ``phases/<phase>/session.json``
(one descriptor per phase of a staged search,
:mod:`~hydromodpy.results.session.phase`). The promoted trial is a run under
``runs/<case>/``, linked by ids. Each module writes and reads one format.
"""
