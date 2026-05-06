# Minimal makefile for Sphinx documentation
#
# Use bash with pipefail so that piping sphinx-build output through grep does
# not mask a non-zero exit code from sphinx itself.
SHELL := /usr/bin/env bash
.SHELLFLAGS := -e -o pipefail -c

# You can set these variables from the command line.
# -j auto parallelises reading + writing across all CPU cores. Mandatory:
# the recursive autosummary over hydromodpy generates ~900 pages, single-threaded
# writing takes several minutes. Override with `make html SPHINXOPTS=` to disable.
SPHINXOPTS    ?= -j auto
SPHINXBUILD   ?= python -m sphinx
SPHINXPROJ    = HydroModPy
SOURCEDIR     = source
BUILDDIR      = build

# Strip noisy infrastructure warnings that the build cannot fix from the
# console output:
#   - ``DeprecationWarning: The frontend.Option(Parser) class will be...``
#     (docutils still uses optparse on Python 3.13);
#   - ``DeprecationWarning: This process is multi-threaded, use of fork()``
#     (multiprocessing under ``-j auto``).
# These do not represent doc-side issues. The genuine sphinx warnings, the
# build summary, and the autodoc/autosummary failures stay visible. Override
# with ``HMP_DOCS_QUIET=0 make html`` to see the raw stream.
HMP_DOCS_QUIET ?= 1
NOISY_PATTERNS := -e "frontend\.Option" -e "frontend\.OptionParser" -e "popen_fork" -e "is multi-threaded, use of fork" -e "self.pid = os.fork" -e "option = self.option_class"
ifeq ($(HMP_DOCS_QUIET),1)
SPHINX_FILTER := 2>&1 | grep -v $(NOISY_PATTERNS) || true
else
SPHINX_FILTER :=
endif

# Internal variables.
PAPEROPT_a4     = -D latex_paper_size=a4
PAPEROPT_letter = -D latex_paper_size=letter
ALLSPHINXOPTS   = -d $(BUILDDIR)/doctrees $(PAPEROPT_$(PAPER)) $(SPHINXOPTS) $(SOURCEDIR)
# the i18n builder cannot share the environment and doctrees with the others
I18NSPHINXOPTS  = $(PAPEROPT_$(PAPER)) $(SPHINXOPTS) $(SOURCEDIR)

# Put it first so that "make" without argument is like "make help".
help:
	@$(SPHINXBUILD) -M help "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS) $(O)
	@echo "Please use \`make <target>' where <target> is one of"
	@echo "  html       to make standalone HTML files"
	@echo "  livehtml   to serve HTML with sphinx-autobuild and reload on save"
	@echo "  polyversion       to build a merged multi-version site (master + dev + tags)"
	@echo "  polyversion-local to build only the current working tree under docs/build/html"
	@echo "  dirhtml    to make HTML files named index.html in directories"
	@echo "  singlehtml to make a single large HTML file"
	@echo "  pickle     to make pickle files"
	@echo "  json       to make JSON files"
	@echo "  htmlhelp   to make HTML files and a HTML help project"
	@echo "  qthelp     to make HTML files and a qthelp project"
	@echo "  devhelp    to make HTML files and a Devhelp project"
	@echo "  epub       to make an epub"
	@echo "  latex      to make LaTeX files, you can set PAPER=a4 or PAPER=letter"
	@echo "  latexpdf   to make LaTeX files and run them through pdflatex"
	@echo "  text       to make text files"
	@echo "  man        to make manual pages"
	@echo "  texinfo    to make Texinfo files"
	@echo "  info       to make Texinfo files and run them through makeinfo"
	@echo "  gettext    to make PO message catalogs"
	@echo "  changes    to make an overview of all changed/added/deprecated items"
	@echo "  linkcheck  to check all external links for integrity"
	@echo "  doctest    to run all doctests embedded in the documentation (if enabled)"

clean:
	-rm -rf $(BUILDDIR)/*

html:
	$(SPHINXBUILD) -b html $(ALLSPHINXOPTS) $(BUILDDIR)/html $(SPHINX_FILTER)
	@echo
	@echo "Build finished. The HTML pages are in $(BUILDDIR)/html."

html-strict:
	$(SPHINXBUILD) -b html -W --keep-going $(ALLSPHINXOPTS) $(BUILDDIR)/html $(SPHINX_FILTER)
	@echo
	@echo "Strict build finished (warnings treated as errors)."

lint:
	@echo "Running sphinx-lint on $(SOURCEDIR)..."
	@python -m sphinxlint --enable all --max-line-length 100 $(SOURCEDIR) || true
	@echo "Running doc8 on $(SOURCEDIR)..."
	@python -m doc8 --max-line-length 100 $(SOURCEDIR) || true

livehtml:
	sphinx-autobuild -b html --open-browser $(ALLSPHINXOPTS) $(BUILDDIR)/html $(SPHINX_FILTER)

polyversion:
	cd .. && python -m sphinx_polyversion poly.py
	@echo "Multi-version site at docs/build/html/<branch-or-tag>/index.html"

polyversion-local:
	cd .. && python -m sphinx_polyversion poly.py -l --sequential
	@echo "Local mock build at docs/build/html/<current-branch>/index.html"

dirhtml:
	$(SPHINXBUILD) -b dirhtml $(ALLSPHINXOPTS) $(BUILDDIR)/dirhtml
	@echo
	@echo "Build finished. The HTML pages are in $(BUILDDIR)/dirhtml."

singlehtml:
	$(SPHINXBUILD) -b singlehtml $(ALLSPHINXOPTS) $(BUILDDIR)/singlehtml
	@echo
	@echo "Build finished. The HTML page is in $(BUILDDIR)/singlehtml."

pickle:
	$(SPHINXBUILD) -b pickle $(ALLSPHINXOPTS) $(BUILDDIR)/pickle
	@echo
	@echo "Build finished; now you can process the pickle files."

json:
	$(SPHINXBUILD) -b json $(ALLSPHINXOPTS) $(BUILDDIR)/json
	@echo
	@echo "Build finished; now you can process the JSON files."

htmlhelp:
	$(SPHINXBUILD) -b htmlhelp $(ALLSPHINXOPTS) $(BUILDDIR)/htmlhelp
	@echo
	@echo "Build finished; now you can run HTML Help Workshop with the" \
	      ".hhp project file in $(BUILDDIR)/htmlhelp."

qthelp:
	$(SPHINXBUILD) -b qthelp $(ALLSPHINXOPTS) $(BUILDDIR)/qthelp
	@echo
	@echo "Build finished; now you can run "qcollectiongenerator" with the" \
	      ".qhcp project file in $(BUILDDIR)/qthelp, like this:"
	@echo "# qcollectiongenerator $(BUILDDIR)/qthelp/rocks-tutorials.qhcp"
	@echo "To view the help file:"
	@echo "# assistant -collectionFile $(BUILDDIR)/qthelp/rocks-tutorials.qhc"

devhelp:
	$(SPHINXBUILD) -b devhelp $(ALLSPHINXOPTS) $(BUILDDIR)/devhelp
	@echo
	@echo "Build finished."
	@echo "To view the help file:"
	@echo "# mkdir -p $$HOME/.local/share/devhelp/rocks-tutorials"
	@echo "# ln -s $(BUILDDIR)/devhelp $$HOME/.local/share/devhelp/rocks-tutorials"
	@echo "# devhelp"

epub:
	$(SPHINXBUILD) -b epub $(ALLSPHINXOPTS) $(BUILDDIR)/epub
	@echo
	@echo "Build finished. The epub file is in $(BUILDDIR)/epub."

latex:
	$(SPHINXBUILD) -b latex $(ALLSPHINXOPTS) $(BUILDDIR)/latex
	@echo
	@echo "Build finished; the LaTeX files are in $(BUILDDIR)/latex."
	@echo "Run \`make' in that directory to run these through (pdf)latex" \
	      "(use \`make latexpdf' here to do that automatically)."

latexpdf:
	$(SPHINXBUILD) -b latex $(ALLSPHINXOPTS) $(BUILDDIR)/latex
	@echo "Running LaTeX files through pdflatex..."
	$(MAKE) -C $(BUILDDIR)/latex all-pdf
	@echo "pdflatex finished; the PDF files are in $(BUILDDIR)/latex."

text:
	$(SPHINXBUILD) -b text $(ALLSPHINXOPTS) $(BUILDDIR)/text
	@echo
	@echo "Build finished. The text files are in $(BUILDDIR)/text."

man:
	$(SPHINXBUILD) -b man $(ALLSPHINXOPTS) $(BUILDDIR)/man
	@echo
	@echo "Build finished. The manual pages are in $(BUILDDIR)/man."

texinfo:
	$(SPHINXBUILD) -b texinfo $(ALLSPHINXOPTS) $(BUILDDIR)/texinfo
	@echo
	@echo "Build finished. The Texinfo files are in $(BUILDDIR)/texinfo."
	@echo "Run \`make' in that directory to run these through makeinfo" \
	      "(use \`make info' here to do that automatically)."

info:
	$(SPHINXBUILD) -b texinfo $(ALLSPHINXOPTS) $(BUILDDIR)/texinfo
	@echo "Running Texinfo files through makeinfo..."
	make -C $(BUILDDIR)/texinfo info
	@echo "makeinfo finished; the Info files are in $(BUILDDIR)/texinfo."

gettext:
	$(SPHINXBUILD) -b gettext $(I18NSPHINXOPTS) $(BUILDDIR)/locale
	@echo
	@echo "Build finished. The message catalogs are in $(BUILDDIR)/locale."

changes:
	$(SPHINXBUILD) -b changes $(ALLSPHINXOPTS) $(BUILDDIR)/changes
	@echo
	@echo "The overview file is in $(BUILDDIR)/changes."

linkcheck:
	$(SPHINXBUILD) -b linkcheck $(ALLSPHINXOPTS) $(BUILDDIR)/linkcheck
	@echo
	@echo "Link check complete; look for any errors in the above output " \
	      "or in $(BUILDDIR)/linkcheck/output.txt."

doctest:
	$(SPHINXBUILD) -b doctest $(ALLSPHINXOPTS) $(BUILDDIR)/doctest
	@echo "Testing of doctests in the sources finished, look at the " \
	      "results in $(BUILDDIR)/doctest/output.txt."

.PHONY: help Makefile clean html html-strict lint livehtml polyversion polyversion-local dirhtml singlehtml pickle json htmlhelp qthelp devhelp epub latex latexpdf text man changes linkcheck doctest gettext

# Catch-all target: route all unknown targets to Sphinx using the new
# "make mode" option.  $(O) is meant as a shortcut for $(SPHINXOPTS).
%: Makefile
	@$(SPHINXBUILD) -M $@ "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS) $(O)
