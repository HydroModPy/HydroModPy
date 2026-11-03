"""A solver binary that cannot be fetched raises a typed network error.

A raw connection error used to reach the user as is: exit 1 from ``hmp
install-binaries`` and a bare exception in the ``run_solver`` step of a run.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.cli.helpers import EXIT_VALIDATION, exit_code_for
from hydromodpy.core.exceptions import NetworkError
from hydromodpy.solver.modflow_common import binaries


@pytest.mark.parametrize(
    ("raised", "cause"),
    [
        (
            NetworkError("HTTP GET x failed after 4 retries", last_exception="Connection refused"),
            "Connection refused",
        ),
        (NetworkError("HTTP GET x -> 503", status_code=503), "HTTP GET x -> 503"),
    ],
)
def test_a_network_failure_names_the_address_and_what_to_set(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, raised: NetworkError, cause: str
) -> None:
    def refuse(*_args: object, **_kwargs: object) -> None:
        raise raised

    monkeypatch.setattr(binaries, "cache_dir", lambda: tmp_path / "cache")
    monkeypatch.setattr(binaries, "fetch_pinned", refuse)

    with pytest.raises(NetworkError) as caught:
        binaries.download_solver_binaries(tmp_path, subset=["mf6"], release="23.0")

    message = str(caught.value)
    assert binaries.asset_url("23.0", binaries._release_asset()) in message
    assert cause in message
    assert "HTTPS_PROXY" in message
    assert "HMP_BIN" in message
    assert exit_code_for(caught.value) == EXIT_VALIDATION == 16
