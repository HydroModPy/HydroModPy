"""sphinx-polyversion driver for HydroModPy.

Builds the HTML documentation for the published branches and tags into a
single merged site under ``docs/build/html``. Read the Docs keeps using its
own per-branch builds and ignores this file.

Run locally::

    mamba activate hmp_refact
    python -m sphinx_polyversion poly.py

Add ``-l`` (or ``--local``) to render only the current working tree without
checking out any other revision (useful while iterating)::

    python -m sphinx_polyversion poly.py -l
"""

from __future__ import annotations

from pathlib import Path

from sphinx_polyversion import DefaultDriver
from sphinx_polyversion.environment import Environment
from sphinx_polyversion.git import Git, file_predicate
from sphinx_polyversion.sphinx import SphinxBuilder

ROOT = Path(__file__).parent

# Branches whose `docs/source` is built into the merged site. master + dev
# are the canonical stable / unstable trunks; dev-docs is the active doc
# refactor branch and is included so contributors can preview the in-flight
# rewrite alongside the published versions.
BRANCH_REGEX = r"(master|dev|dev-docs)"

# Tags follow ``vMAJOR.MINOR.PATCH`` once releases resume; meanwhile the
# regex still matches nothing, which is a no-op.
TAG_REGEX = r"v\d+\.\d+\.\d+"

# Only rebuild a revision when files inside the docs source tree changed.
DOCS_SOURCE = "docs/source"

DefaultDriver(
    ROOT,
    ROOT / "docs" / "build" / "html",
    vcs=Git(
        branch_regex=BRANCH_REGEX,
        tag_regex=TAG_REGEX,
        buffer_size=1024 * 1024,
        predicate=file_predicate([DOCS_SOURCE]),
    ),
    builder=SphinxBuilder(
        DOCS_SOURCE,
        args=["-j", "auto", "-b", "html"],
    ),
    env=Environment,
).run()
