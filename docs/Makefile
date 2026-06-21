# Minimal makefile for the HydroModPy v1 documentation.
# Builds the single-version HTML site from source/ into build/html.
# -j auto parallelises reading and writing across all cores. Mandatory: the
# autosummary over hydromodpy generates many pages and single-threaded writing
# is slow. Override with `make html SPHINXOPTS=` to disable.

SPHINXOPTS    ?= -j auto
SPHINXBUILD   ?= python -m sphinx
SOURCEDIR     = source
BUILDDIR      = build

.PHONY: help html html-strict clean livehtml linkcheck

help:
	@$(SPHINXBUILD) -M help "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS)

html:
	$(SPHINXBUILD) -b html $(SPHINXOPTS) "$(SOURCEDIR)" "$(BUILDDIR)/html"
	@echo
	@echo "Build finished. The HTML pages are in $(BUILDDIR)/html."

html-strict:
	$(SPHINXBUILD) -b html -W --keep-going $(SPHINXOPTS) "$(SOURCEDIR)" "$(BUILDDIR)/html"
	@echo
	@echo "Strict build finished (warnings treated as errors)."

clean:
	-rm -rf "$(BUILDDIR)"

livehtml:
	sphinx-autobuild -b html --watch ../hydromodpy $(SPHINXOPTS) "$(SOURCEDIR)" "$(BUILDDIR)/html"

linkcheck:
	$(SPHINXBUILD) -b linkcheck $(SPHINXOPTS) "$(SOURCEDIR)" "$(BUILDDIR)/linkcheck"
