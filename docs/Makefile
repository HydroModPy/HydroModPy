SPHINXOPTS ?= -j auto

.PHONY: html clean

html:
	$(MAKE) -C readthedocs SPHINXOPTS="$(SPHINXOPTS)" BUILDDIR="../build" html

clean:
	$(MAKE) -C readthedocs BUILDDIR="../build" clean
