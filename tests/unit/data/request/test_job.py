"""The ``data-request`` job declaration: the hosts it may reach and the files it writes."""

from __future__ import annotations

import re

from hydromodpy.data.request.job import DATA_REQUEST, REACHED_HOSTS
from hydromodpy.schema.capability import HOST_PATTERN


def test_declared_hosts_are_bare_host_names():
    assert all(re.fullmatch(HOST_PATTERN, host) for host in REACHED_HOSTS)


def test_report_is_the_only_artefact_every_run_writes():
    payload = [output for output in DATA_REQUEST.outputs if output.path.startswith("outputs/")]
    assert [output.path for output in payload] == ["outputs/request.json"]
