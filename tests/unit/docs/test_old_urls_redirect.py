"""Every URL of the site published before the restructuring still leads somewhere.

The rules and the reason are in ``tools/docs/check_redirects.py``. The docs workflow
runs the same module on the built site, which also covers the pages the build writes
(``reference/parameters``, ``reference/python``, ``reference/cli``). The last test
reads the built site when ``DOCS_HTML_DIR`` names it, or when ``docs/build/html``
exists (``make -C docs html-strict`` writes it there).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tools.docs import check_redirects

BUILT_SITE = Path(os.environ.get("DOCS_HTML_DIR", check_redirects.ROOT / "docs" / "build" / "html"))


def test_every_old_url_is_a_page_or_has_a_redirect() -> None:
    assert check_redirects.lost_urls() == []


def test_a_redirect_goes_to_a_page_in_one_hop() -> None:
    assert check_redirects.bad_redirects() == []


def test_the_list_of_old_urls_is_not_empty_and_has_no_blank_extension() -> None:
    urls = check_redirects.lines(check_redirects.OLD_URLS)
    assert len(urls) > 500
    assert all(url.endswith(".html") for url in urls)


@pytest.mark.skipif(not BUILT_SITE.is_dir(), reason="needs the built site (DOCS_HTML_DIR)")
def test_every_old_url_exists_in_the_built_site() -> None:
    assert check_redirects.built_site_problems(BUILT_SITE) == []
