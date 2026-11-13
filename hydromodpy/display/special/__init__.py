"""Special figures: one module each, named as its preset, for what no frame draws.

A module holds ``draw(subject, ax, theme)``, which may also take the keywords ``station``
and ``time``. The kind of subject it reads, its width and its keywords are written once,
in its row of ``display.request.SPECIALS``, and a test holds the two together. A row is a
preset, so a TOML file names a special without naming code, and ``render`` imports the
module only when it draws. ``records`` holds the reads that several of them share and is
no figure. The list is closed at twelve.
"""
