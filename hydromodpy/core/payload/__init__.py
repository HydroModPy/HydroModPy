"""What a package installs into a workspace, and the one installer that places it.

An example, a published run and an exported project all carry the same
install index: every file with its destination, size and sha256, every row a
station registry needs, every site the package declares. The index is the
document ``INSTALL.toml`` (:mod:`hydromodpy.core.payload.index`); the
installer (:mod:`hydromodpy.core.payload.install`) plans every placement
before it writes one, so a conflict is named before anything changes.
"""
