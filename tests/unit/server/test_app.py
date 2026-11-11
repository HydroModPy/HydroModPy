"""The routes of the server: what crosses the wire, what a call is given, what is refused."""

from __future__ import annotations

import ast
import collections.abc
import dataclasses
import datetime
import hashlib
import http.client
import importlib
import inspect
import json
import os
import socket
import threading
import time
import types
import typing
import urllib.error
import urllib.request
from collections.abc import Iterator
from enum import Enum
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

import hydromodpy as hmp
from hydromodpy.core.exceptions import BoundsError, ConfigError
from hydromodpy.core.runtime.bounds import Bounds
from hydromodpy.project import api
from hydromodpy.project.environment import Environment
from hydromodpy.project.request import RunRequest
from hydromodpy_server.app import (
    IN_A_CHILD,
    IN_A_THREAD,
    OF_AN_ORGANISATION,
    OPEN_REFUSED,
    Refused,
    Settings,
    arguments_of,
    call,
    child,
    jsonable,
    refusal,
    serve,
    upload_name,
)

SERVED = tuple(sorted(IN_A_CHILD | IN_A_THREAD | OF_AN_ORGANISATION))
SYNTHETIC = {"source_mode": "synthetic"}
OLD_FORM = {"geographic": SYNTHETIC, "modflow6": {"runtime": {"mf6_ims_complexity": "SIMPLE"}}}


class Color(Enum):
    RED = "red"


@dataclasses.dataclass
class Box:
    where: Path
    tags: list[str]
    when: datetime.date


class Told:
    def to_dict(self) -> dict[str, Any]:
        return {"said": Path("/p/runs/a")}


# ---------------------------------------------------------------------------
# jsonable
# ---------------------------------------------------------------------------

ROOT = Path("/p")
JSONABLE = {
    "none": (None, None),
    "scalars": ([1, 2.5, "a", True], [1, 2.5, "a", True]),
    "a number that is not one": (float("nan"), None),
    "an enum by its value": (Color.RED, "red"),
    "a date": (datetime.date(2020, 1, 2), "2020-01-02"),
    "a path below the root": (ROOT / "runs" / "a", "runs/a"),
    "the root itself": (ROOT, "."),
    "a text that is a path below the root": (f"{ROOT}/runs/a", "runs/a"),
    "a text that only starts like the root": ("/pq/runs/a", "/pq/runs/a"),
    "a path elsewhere": (Path("/etc/x"), "/etc/x"),
    "a model": (RunRequest(config={"a": 1}), RunRequest(config={"a": 1}).model_dump(mode="json")),
    "a dataclass with a path": (
        Box(ROOT / "o", ["t"], datetime.date(2020, 1, 2)),
        {"where": "o", "tags": ["t"], "when": "2020-01-02"},
    ),
    "an object with to_dict": (Told(), {"said": "runs/a"}),
    "a dict with other keys": ({1: (2, 3)}, {"1": [2, 3]}),
    "a numpy scalar": (np.int64(3), 3),
    "a series": (
        pd.Series([1.0, float("nan")], index=["a", "b"], name="q"),
        {"name": "q", "index": ["a", "b"], "data": [1.0, None]},
    ),
    "a table": (
        pd.DataFrame({"x": [1, 2]}),
        {"columns": ["x"], "index": [0, 1], "data": [[1], [2]]},
    ),
}


def test_every_verb_of_the_facade_has_a_route() -> None:
    verbs = set(api.__all__)
    assert verbs <= set(hmp.__all__)
    routed = IN_A_CHILD | IN_A_THREAD | OF_AN_ORGANISATION
    assert routed | {"open"} == verbs
    assert not IN_A_CHILD & IN_A_THREAD
    assert not (IN_A_CHILD | IN_A_THREAD) & OF_AN_ORGANISATION
    assert "open" not in routed


@pytest.mark.parametrize(("value", "expected"), JSONABLE.values(), ids=list(JSONABLE))
def test_jsonable_gives_json_data(value: Any, expected: Any) -> None:
    given = jsonable(value, ROOT)
    assert given == expected
    json.dumps(given, allow_nan=False)


def test_a_type_that_does_not_cross_is_refused() -> None:
    with pytest.raises(TypeError, match="a object does not cross the wire"):
        jsonable({"a": object()})


def _return_classes() -> dict[str, list[Any]]:
    """Return the classes each served verb names as its return, from its annotations."""
    api = importlib.import_module("hydromodpy.project.api")
    tree = ast.parse(inspect.getsource(api))
    checking = next(
        node
        for node in tree.body
        if isinstance(node, ast.If) and ast.unparse(node.test) == "TYPE_CHECKING"
    )
    names = dict(vars(api))
    exec(compile(ast.Module(checking.body, []), "<types>", "exec"), names)  # noqa: S102

    def flatten(hint: Any) -> list[Any]:
        origin = typing.get_origin(hint)
        if origin in (typing.Union, types.UnionType, list, tuple, collections.abc.Sequence):
            return [c for arg in typing.get_args(hint) if arg is not Ellipsis for c in flatten(arg)]
        if hint is typing.Any:
            return []
        return [origin or (type(None) if hint is None else hint)]

    found = {}
    for verb in SERVED:
        function = getattr(hmp, verb)
        found[verb] = [
            cls
            for each in (function, *typing.get_overloads(function))
            for cls in flatten(typing.get_type_hints(each, globalns=names)["return"])
        ]
    return found


def _crosses(cls: type) -> bool:
    plain = (
        str,
        int,
        float,
        bool,
        type(None),
        Enum,
        datetime.date,
        os.PathLike,
        collections.abc.Mapping,
    )
    return (
        issubclass(cls, plain)
        or hasattr(cls, "model_dump")
        or hasattr(cls, "to_json")
        or hasattr(cls, "to_dict")
        or dataclasses.is_dataclass(cls)
    )


def test_every_return_of_a_served_verb_crosses_or_is_refused_by_show() -> None:
    refused_by_show = {"DataArray", "Figure"}
    loose = [
        (verb, cls.__name__)
        for verb, classes in _return_classes().items()
        for cls in classes
        if not _crosses(cls) and not (verb == "show" and cls.__name__ in refused_by_show)
    ]
    assert loose == []


# ---------------------------------------------------------------------------
# place
# ---------------------------------------------------------------------------


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    (tmp_path / "root" / "acme" / "projects" / "island").mkdir(parents=True)
    (tmp_path / "root" / "bare").mkdir()
    (tmp_path / "creds").mkdir()
    (tmp_path / "creds" / "acme.toml").write_text("", encoding="utf-8")
    (tmp_path / "creds" / "acme.toml").chmod(0o600)
    return Settings(tmp_path / "root", tmp_path / "creds")


PLACES = {
    "a name the rule changes": ("Acme", "island"),
    "an inbox name": (".inbox", "island"),
    "a project name the rule changes": ("acme", "Is land"),
    "an absent space": ("nobody", "island"),
    "an absent project": ("acme", "nowhere"),
    "a space without projects": ("bare", "island"),
}


@pytest.mark.parametrize(("org", "project"), PLACES.values(), ids=list(PLACES))
def test_a_route_that_names_nothing_is_a_404(settings: Settings, org: str, project: str) -> None:
    with pytest.raises(Refused) as caught:
        settings.place(org, project)
    assert caught.value.status == 404


def test_the_place_of_a_project_is_its_only_allowed_root(settings: Settings) -> None:
    root, environment = settings.place("acme", "island")
    assert root == settings.root / "acme" / "projects" / "island"
    assert environment.bounds.allowed_roots == (root,)
    assert environment.credentials == settings.credentials_dir / "acme.toml"
    space, _ = settings.place("acme")
    assert space == settings.root / "acme"


def test_credentials_are_none_without_a_file_or_a_folder(settings: Settings) -> None:
    (settings.root / "bare" / "projects" / "p").mkdir(parents=True)
    assert settings.place("bare", "p")[1].credentials is None
    assert Settings(settings.root).place("acme", "island")[1].credentials is None


def test_the_bounds_of_the_operator_are_kept(settings: Settings) -> None:
    settings.bounds = Bounds(allowed_hosts=frozenset({"example.org"}), max_download_bytes=99)
    bounds = settings.place("acme", "island")[1].bounds
    assert (bounds.allowed_hosts, bounds.max_download_bytes) == (frozenset({"example.org"}), 99)


# ---------------------------------------------------------------------------
# What a call is given
# ---------------------------------------------------------------------------


def fake_verb(
    source: Any,
    *,
    base: Any = None,
    workspace: Any = None,
    environment: Any = None,
    headless: bool = False,
    project: str | None = None,
    out: Any = None,
) -> dict[str, Any]:
    return {
        "base": base,
        "workspace": workspace,
        "environment": environment,
        "headless": headless,
        "project": project,
        "out": out,
        "source": source,
    }


@pytest.fixture
def fakes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hmp, "fake_verb", fake_verb, raising=False)


def test_the_server_fills_what_the_signature_takes(fakes: None, tmp_path: Path) -> None:
    environment = Environment()
    given = call("fake_verb", {"source": {"a": 1}, "project": "label"}, tmp_path, environment)
    assert given == {
        "base": tmp_path,
        "workspace": tmp_path,
        "environment": environment,
        "headless": True,
        "project": "label",
        "out": None,
        "source": {"a": 1},
    }


@pytest.mark.parametrize("name", ["base", "workspace", "environment", "headless"])
def test_the_body_never_names_what_the_server_sets(fakes: None, tmp_path: Path, name: str) -> None:
    with pytest.raises(Refused, match=f"{name} are set by the server") as caught:
        arguments_of("fake_verb", {"source": {}, name: 1}, tmp_path, Environment())
    assert caught.value.status == 400


def test_a_verb_gets_only_the_names_it_takes(tmp_path: Path) -> None:
    given = arguments_of("stop", {"ref": "a"}, tmp_path, Environment())
    assert given == {"ref": "a", "workspace": tmp_path}
    assert arguments_of("doctor", {}, tmp_path, Environment()) == {}


def test_an_unknown_or_missing_argument_is_a_400(tmp_path: Path) -> None:
    for body in ({"ref": "a", "nope": 1}, {}):
        with pytest.raises(Refused) as caught:
            arguments_of("stop", body, tmp_path, Environment())
        assert caught.value.status == 400


PATHS = {
    "ref absolute": ("stop", {"ref": "/etc"}, "ref names a path outside the project"),
    "ref in a home": ("stop", {"ref": "~/x"}, "ref names a path outside the project"),
    "ref that climbs": ("trash", {"ref": "a/../../b"}, "ref names a path outside the project"),
    "ref of a drive": ("status", {"ref": "C:\\x"}, "ref names a path outside the project"),
    "ref that is no text": ("stop", {"ref": 3}, "ref is a text"),
    "refs with an absolute": ("compare", {"refs": ["a", "/b"]}, "refs names a path outside"),
    "refs that is no list": ("compare", {"refs": "a"}, "refs is a list of texts"),
    "source that climbs": ("run", {"source": "../x.toml"}, "source names a path outside"),
    "source absolute": ("check", {"source": "/etc/passwd"}, "source names a path outside"),
    "source of another type": ("check", {"source": 3}, "source is a document"),
    "out absolute": ("compare", {"refs": ["a"], "out": "/tmp/x"}, "out names a path outside"),
    "folder that climbs": ("export", {"ref": "a", "folder": "../x"}, "folder names a path outside"),
    "file absolute": ("export", {"ref": "a", "file": "/x.nc"}, "file names a path outside"),
    "save absolute": ("show", {"ref": "a", "save": "/x.png"}, "save names a path outside"),
    "to absolute": ("publish", {"ref": "a", "to": "/srv"}, "to names a path outside"),
    "a field": ("show", {"ref": "a", "what": "field"}, "a field crosses as a file: use export"),
    "a figure without save": ("show", {"ref": "a", "what": "figure"}, "give save"),
}


@pytest.mark.parametrize(("verb", "body", "phrase"), PATHS.values(), ids=list(PATHS))
def test_a_path_that_leaves_the_project_is_refused(
    tmp_path: Path, verb: str, body: dict[str, Any], phrase: str
) -> None:
    with pytest.raises(Refused, match=phrase) as caught:
        arguments_of(verb, body, tmp_path, Environment())
    assert caught.value.status == 400


def test_a_link_out_of_the_project_is_refused(tmp_path: Path) -> None:
    project, outside = tmp_path / "p", tmp_path / "out"
    project.mkdir()
    outside.mkdir()
    try:
        (project / "link").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symbolic links are not allowed here")
    with pytest.raises(Refused, match="out names a path outside"):
        arguments_of("compare", {"refs": ["a"], "out": "link/x"}, project.resolve(), Environment())


def test_a_path_inside_the_project_is_made_absolute_and_a_ref_is_left(tmp_path: Path) -> None:
    given = arguments_of(
        "export", {"ref": "runs/a", "folder": "out", "file": "a.nc"}, tmp_path, Environment()
    )
    assert (given["ref"], given["folder"], given["file"]) == (
        "runs/a",
        str(tmp_path / "out"),
        str(tmp_path / "a.nc"),
    )
    given = arguments_of("check", {"source": "inputs/cfg.toml"}, tmp_path, Environment())
    assert given["source"] == str(tmp_path / "inputs" / "cfg.toml")
    given = arguments_of(
        "show", {"ref": "a", "what": "figure", "save": "f.png"}, tmp_path, Environment()
    )
    assert given["save"] == str(tmp_path / "f.png")


def test_a_json_text_source_is_not_a_path(tmp_path: Path) -> None:
    text = '{"a": 1}'
    assert arguments_of("run", {"source": text}, tmp_path, Environment())["source"] == text


def test_a_run_request_in_a_source_is_read_as_one(tmp_path: Path) -> None:
    body = {"source": {"schema": "hydromodpy.request.v1", "config": {"a": 1}, "name": "x"}}
    request = arguments_of("run", body, tmp_path, Environment())["source"]
    assert isinstance(request, RunRequest)
    assert (request.config, request.name) == ({"a": 1}, "x")
    with pytest.raises(Refused, match="the run request is refused"):
        arguments_of(
            "run", {"source": {"schema": "hydromodpy.request.v1"}}, tmp_path, Environment()
        )
    document = {"schema": "hydromodpy.request.v1", "config": {}}
    assert (
        arguments_of("check", {"source": document}, tmp_path, Environment())["source"] == document
    )


def test_example_add_is_refused_under_named_hosts(tmp_path: Path) -> None:
    named = Environment(bounds=Bounds(allowed_hosts=frozenset({"example.org"})))
    with pytest.raises(Refused, match="example add fetches outside the hosts") as caught:
        arguments_of("example", {"name": "04", "add": True}, tmp_path, named)
    assert caught.value.status == 400
    assert arguments_of("example", {"name": "04"}, tmp_path, named)["workspace"] == tmp_path
    assert arguments_of("example", {"name": "04", "add": True}, tmp_path, Environment())["add"]


# ---------------------------------------------------------------------------
# The name of an upload
# ---------------------------------------------------------------------------

NAMES = {
    "spaces and capitals": ("Rain Data.CSV", "rain_data.csv"),
    "no extension": ("README", "readme"),
    "two dots": ("my.data.csv", "my.data.csv"),
    "a long extension": ("a.abcdefghijklmnopqrst", "a.abcdefghijkl"),
    "an extension that ends with a dot": ("a.abcdefghijk.x", "a.abcdefghijk"),
    "other characters": ("é$t.c/v", "_" + "_t.c_v"),
    "a trailing dot": ("a.", "a"),
}


@pytest.mark.parametrize(("raw", "kept"), NAMES.values(), ids=list(NAMES))
def test_an_upload_name_is_folded(raw: str, kept: str) -> None:
    assert upload_name(raw) == kept


@pytest.mark.parametrize("raw", ["", ".csv", ".hidden.csv"])
def test_an_upload_name_without_a_stem_is_a_400(raw: str) -> None:
    with pytest.raises(Refused) as caught:
        upload_name(raw)
    assert caught.value.status == 400


# ---------------------------------------------------------------------------
# A server on a free port
# ---------------------------------------------------------------------------


class Client:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.server = serve(settings, "127.0.0.1", 0)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def ask(
        self, method: str, path: str, body: Any = None, raw: bytes | None = None
    ) -> tuple[int, Any]:
        data = raw if raw is not None else (None if body is None else json.dumps(body).encode())
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data, method=method)
        try:
            with urllib.request.urlopen(request, timeout=30) as answer:
                return answer.status, json.loads(answer.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def head_only(self, method: str, path: str, length: int) -> int:
        """Send only the head of a request that claims *length* bytes, and return the status."""
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        connection.putrequest(method, path)
        connection.putheader("Content-Length", str(length))
        connection.endheaders()
        status = connection.getresponse().status
        connection.close()
        return status

    def short_body(self, path: str, claimed: int, sent: bytes) -> int:
        """Send *sent* under a longer claimed length, close the sending side, return the status."""
        with socket.create_connection(("127.0.0.1", self.port), timeout=30) as sock:
            head = f"PUT {path} HTTP/1.0\r\nContent-Length: {claimed}\r\n\r\n".encode()
            sock.sendall(head + sent)
            sock.shutdown(socket.SHUT_WR)
            reply = b""
            while chunk := sock.recv(4096):
                reply += chunk
        return int(reply.split(b" ", 2)[1])


@pytest.fixture
def start() -> Iterator[Any]:
    clients: list[Client] = []

    def make(settings: Settings) -> Client:
        clients.append(Client(settings))
        return clients[-1]

    yield make
    for client in clients:
        client.server.shutdown()
        client.server.server_close()


@pytest.fixture
def client(settings: Settings, start: Any) -> Client:
    return start(settings)


def test_health_and_the_schema_of_a_request(
    client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("HMP_IMAGE_TAG", raising=False)
    assert client.ask("GET", "/v1/health") == (200, {"version": hmp.__version__, "image": {}})
    status, schema = client.ask("GET", "/v1/schema/request")
    assert (status, schema) == (200, RunRequest.model_json_schema())
    digest = "sha256:" + "a" * 64
    monkeypatch.setenv("HMP_IMAGE_TAG", "t1")
    monkeypatch.setenv("HMP_IMAGE_DIGEST", digest)
    assert client.ask("GET", "/v1/health")[1]["image"] == {"tag": "t1", "digest": digest}


REFUSALS = {
    "a name the server does not serve": ("POST", "/v1/ACME/island/check", {}, 404, "not a name"),
    "an unknown organisation": ("POST", "/v1/nobody/island/check", {"source": {}}, 404, "no space"),
    "an unknown project": ("POST", "/v1/acme/nowhere/check", {"source": {}}, 404, "no project"),
    "an unknown verb": ("POST", "/v1/acme/island/frobnicate", {}, 404, "no route"),
    "a project verb on a space": ("POST", "/v1/acme/check", {}, 404, "no route"),
    "a space verb on a project": ("POST", "/v1/acme/island/doctor", {}, 404, "no route"),
    "an unknown route": ("GET", "/v2/health", None, 404, "no route"),
    "an unknown job": ("GET", "/v1/acme/island/jobs/abc", None, 404, "no job"),
    "open": ("POST", "/v1/acme/island/open", {"path": "x"}, 400, OPEN_REFUSED),
    "a reserved name": (
        "POST",
        "/v1/acme/island/check",
        {"base": "/etc"},
        400,
        "set by the server",
    ),
    "a body that is not JSON": ("POST", "/v1/acme/island/run", b"not json", 400, "not JSON"),
    "a body that is a list": ("POST", "/v1/acme/island/check", [1], 400, "JSON object"),
    "a field": ("POST", "/v1/acme/island/show", {"ref": "a", "what": "field"}, 400, "use export"),
    "a figure": ("POST", "/v1/acme/island/show", {"ref": "a", "what": "figure"}, 400, "give save"),
    "a ref outside": ("POST", "/v1/acme/island/stop", {"ref": "/etc"}, 400, "outside the project"),
    "a source outside": (
        "POST",
        "/v1/acme/island/run",
        {"source": "../x"},
        400,
        "outside the project",
    ),
    "an upload without a stem": ("PUT", "/v1/acme/island/inputs/.csv", b"x", 400, "no file name"),
}


@pytest.mark.parametrize(
    ("method", "path", "body", "status", "phrase"), REFUSALS.values(), ids=list(REFUSALS)
)
def test_each_refusal_has_its_status_and_its_phrase(
    client: Client, method: str, path: str, body: Any, status: int, phrase: str
) -> None:
    raw = body if isinstance(body, bytes) else None
    answer = client.ask(method, path, None if raw else body, raw)
    assert answer[0] == status
    assert phrase in answer[1]["message"]


def test_example_add_is_a_400_when_hosts_are_named(settings: Settings, start: Any) -> None:
    settings.bounds = Bounds(allowed_hosts=frozenset({"example.org"}))
    status, said = start(settings).ask("POST", "/v1/acme/example", {"name": "04", "add": True})
    assert (status, "fetches outside the hosts" in said["message"]) == (400, True)


def test_a_file_sent_without_its_length_is_a_413(client: Client) -> None:
    connection = http.client.HTTPConnection("127.0.0.1", client.port, timeout=30)
    connection.putrequest("PUT", "/v1/acme/island/inputs/a.csv")
    connection.endheaders()
    status = connection.getresponse().status
    connection.close()
    assert status == 413


def test_a_body_that_is_too_long_is_a_413(client: Client) -> None:
    assert client.head_only("POST", "/v1/acme/island/check", (16 << 20) + 1) == 413


def test_a_file_longer_than_the_ceiling_is_a_413_before_it_is_read(
    settings: Settings, start: Any
) -> None:
    settings.bounds = Bounds(max_download_bytes=10)
    assert start(settings).head_only("PUT", "/v1/acme/island/inputs/a.csv", 11) == 413


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------


def test_an_upload_lands_under_inputs_with_its_digest(client: Client, settings: Settings) -> None:
    body = b"date,rain\n2020-01-01,1.0\n"
    sha = hashlib.sha256(body).hexdigest()
    status, said = client.ask("PUT", "/v1/acme/island/inputs/Rain%20Data.CSV", raw=body)
    name = f"inputs/{sha[:8]}_rain_data.csv"
    assert (status, said) == (201, {"path": name, "sha256": sha, "bytes": len(body)})
    project = settings.root / "acme" / "projects" / "island"
    assert (project / name).read_bytes() == body
    assert list((settings.root / ".inbox").iterdir()) == []


def test_the_same_upload_twice_is_the_same_answer(client: Client) -> None:
    path = "/v1/acme/island/inputs/a.csv"
    assert client.ask("PUT", path, raw=b"abc") == client.ask("PUT", path, raw=b"abc")
    assert client.ask("PUT", path, raw=b"")[0] == 201


def test_other_bytes_under_a_taken_name_are_a_409(client: Client, settings: Settings) -> None:
    body = b"abc"
    sha = hashlib.sha256(body).hexdigest()
    taken = settings.root / "acme" / "projects" / "island" / "inputs" / f"{sha[:8]}_a.csv"
    taken.parent.mkdir()
    taken.write_bytes(b"other")
    status, said = client.ask("PUT", "/v1/acme/island/inputs/a.csv", raw=body)
    assert (status, "already holds other bytes" in said["message"]) == (409, True)
    assert taken.read_bytes() == b"other"
    assert list((settings.root / ".inbox").iterdir()) == []


def test_a_body_shorter_than_its_length_is_a_400_and_leaves_no_part(
    client: Client, settings: Settings
) -> None:
    assert client.short_body("/v1/acme/island/inputs/a.csv", 10, b"abcd") == 400
    assert list((settings.root / ".inbox").iterdir()) == []
    assert not (settings.root / "acme" / "projects" / "island" / "inputs").exists()


# ---------------------------------------------------------------------------
# The verbs by HTTP, in a thread
# ---------------------------------------------------------------------------


def test_a_verb_answers_in_json_and_a_refusal_is_a_422(
    client: Client, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = settings.root / "acme" / "projects" / "island"

    def status(ref: Any = None, *, workspace: Any = None, plan: bool = False) -> Any:
        if ref == "bounds":
            raise BoundsError("project_root is outside the allowed roots")
        if ref == "fault":
            raise RuntimeError("boom")
        if ref == "type":
            return object()
        return [Box(Path(workspace) / "runs" / "a", ["t"], datetime.date(2020, 1, 2))]

    monkeypatch.setattr(hmp, "status", status)
    path = "/v1/acme/island/status"
    assert client.ask("POST", path, {"ref": "a"}) == (
        200,
        [{"where": "runs/a", "tags": ["t"], "when": "2020-01-02"}],
    )
    code, said = client.ask("POST", path, {"ref": "bounds"})
    assert (code, said["code"], "outside the allowed roots" in said["message"]) == (
        422,
        BoundsError.code,
        True,
    )
    assert client.ask("POST", path, {"ref": "fault"}) == (
        500,
        {"code": "RuntimeError", "message": "boom"},
    )
    code, said = client.ask("POST", path, {"ref": "type"})
    assert (code, said["code"]) == (500, "TypeError")
    assert project.is_dir()


def test_the_environment_of_a_call_bounds_its_project_root(
    client: Client, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    def check(
        source: Any,
        *,
        base: Any = None,
        partial: bool = True,
        inputs: bool = False,
        environment: Any = None,
    ) -> list[Any]:
        environment.check(project_root=source["root"], workspace_root=base)
        return []

    monkeypatch.setattr(hmp, "check", check)
    path = "/v1/acme/island/check"
    inside = str(settings.root / "acme" / "projects" / "island" / "sub")
    assert client.ask("POST", path, {"source": {"root": inside}}) == (200, [])
    code, said = client.ask("POST", path, {"source": {"root": str(settings.root / "acme")}})
    assert (code, said["code"]) == (422, BoundsError.code)


def test_a_refusal_carries_its_diagnostics() -> None:
    from hydromodpy.core.diagnostic import Diagnostic

    found = Diagnostic(path="a.b", code="unknown_key", severity="error", detail="x")
    said = refusal(ConfigError("bad", diagnostics=[found]))
    assert said["code"] == ConfigError.code
    assert said["diagnostics"][0]["loc"] == "a.b"
    assert refusal(ValueError("v")) == {"code": "ValueError", "message": "v"}


def test_two_checks_in_two_threads_keep_their_own_warnings(client: Client) -> None:
    path = "/v1/acme/island/check"
    seen: dict[str, list[set[str]]] = {"old": [], "clean": []}

    def play(label: str, document: dict[str, Any]) -> None:
        for _ in range(4):
            _, diagnostics = client.ask("POST", path, {"source": document})
            seen[label].append({item["code"] for item in diagnostics})

    threads = [
        threading.Thread(target=play, args=("old", OLD_FORM)),
        threading.Thread(target=play, args=("clean", {"geographic": SYNTHETIC})),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert all("old_key" in codes for codes in seen["old"])
    assert all("old_key" not in codes for codes in seen["clean"])


# ---------------------------------------------------------------------------
# Jobs: one process per long verb
# ---------------------------------------------------------------------------


def fake_target(verb: str, arguments: dict[str, Any], place: Path, pipe: Any) -> None:
    """Stand in for ``child`` in a spawned process: each verb is one way to end."""
    if verb == "done":
        pipe.send(("done", jsonable({"run_dir": place / "runs" / "a"}, place)))
    elif verb == "refused":
        pipe.send(("refused", refusal(ConfigError("bad document"))))
    elif verb == "failed":
        pipe.send(("failed", refusal(RuntimeError("boom"))))
    elif verb == "died":
        os._exit(3)
    else:
        time.sleep(120)


def _wait(settings: Settings, org: str, project: str, job: str) -> dict[str, Any]:
    end = time.monotonic() + 90
    while time.monotonic() < end:
        said = settings.read_job(org, project, job)
        if said["state"] != "running":
            return said
        time.sleep(0.05)
    raise AssertionError("the job did not end")


ENDS = {
    "done": ("done", {"result": {"run_dir": "runs/a"}}),
    "refused": ("refused", {"refusal": {"code": ConfigError.code, "message": "bad document"}}),
    "failed": ("failed", {"refusal": {"code": "RuntimeError", "message": "boom"}}),
    "died": ("died", {"exitcode": 3}),
}


@pytest.mark.parametrize("verb", ENDS)
def test_a_job_tells_how_its_process_ended(settings: Settings, tmp_path: Path, verb: str) -> None:
    started = settings.start("acme", "island", verb, {}, tmp_path, target=fake_target)
    said = _wait(settings, "acme", "island", started["job"])
    state, rest = ENDS[verb]
    assert said == {"state": state, **rest}
    assert settings.read_job("acme", "island", started["job"]) == said


def test_a_job_is_running_until_it_ends_and_is_private_to_its_project(
    settings: Settings, tmp_path: Path
) -> None:
    started = settings.start("acme", "island", "slow", {}, tmp_path, target=fake_target)
    assert settings.read_job("acme", "island", started["job"]) == {
        "state": "running",
        "pid": started["pid"],
    }
    for org, project in (("acme", "other"), ("other", "island")):
        with pytest.raises(Refused) as caught:
            settings.read_job(org, project, started["job"])
        assert caught.value.status == 404
    settings.stop_jobs()
    assert _wait(settings, "acme", "island", started["job"])["state"] == "died"


def test_a_long_verb_answers_202_with_its_job(
    client: Client, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    started = {}
    original = settings.start

    def start(*args: Any, **kwargs: Any) -> dict[str, Any]:
        started["verb"] = args[2]
        started["arguments"] = args[3]
        return original(*args, target=fake_target)

    monkeypatch.setattr(settings, "start", start)
    status, said = client.ask("POST", "/v1/acme/island/run", {"source": {"a": 1}, "name": "x"})
    assert status == 202
    assert started["verb"] == "run"
    assert started["arguments"]["headless"] is True
    assert started["arguments"]["base"] == settings.root / "acme" / "projects" / "island"
    assert said["pid"] > 0
    code, job = client.ask("GET", f"/v1/acme/island/jobs/{said['job']}")
    assert code == 200
    assert job["state"] in {"running", "died"}
    settings.stop_jobs()


@pytest.mark.parametrize("how", ["done", "refused", "failed"])
def test_the_target_of_a_process_sends_what_the_verb_did(
    how: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import multiprocessing

    def fake(*, a: int) -> Any:
        if how == "refused":
            raise ConfigError("no")
        if how == "failed":
            raise RuntimeError("no")
        return {"path": tmp_path / "runs" / "a", "a": a}

    monkeypatch.setattr(hmp, "fake_long", fake, raising=False)
    ours, theirs = multiprocessing.get_context("spawn").Pipe(duplex=False)
    child("fake_long", {"a": 1}, tmp_path, theirs)
    state, payload = ours.recv()
    assert state == how
    if how == "done":
        assert payload == {"path": "runs/a", "a": 1}
    else:
        assert payload["message"] == "no"
        assert payload["code"] == (ConfigError.code if how == "refused" else "RuntimeError")
