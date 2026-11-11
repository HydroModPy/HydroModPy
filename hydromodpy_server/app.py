"""Routes of the server: the verbs, the upload of a file and the jobs of the runs."""

from __future__ import annotations

import dataclasses
import hashlib
import inspect
import json
import math
import multiprocessing
import os
import re
import sys
import threading
import traceback
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import date
from enum import Enum
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, BinaryIO
from urllib.parse import unquote

import hydromodpy as hmp
from hydromodpy.core.exceptions import ConfigError, HydroModPyError
from hydromodpy.core.runtime.bounds import Bounds
from hydromodpy.core.runtime.image import image_of
from hydromodpy.core.state.names import check_name
from hydromodpy.project.environment import Environment
from hydromodpy.project.request import REQUEST_SCHEMA, RunRequest

IN_A_CHILD = frozenset({"run", "calibrate", "spinup", "replay"})
IN_A_THREAD = frozenset(
    {"check", "stop", "status", "trash", "compare", "show", "export", "publish"}
)
OF_AN_ORGANISATION = frozenset({"example", "doctor"})
SET_BY_THE_SERVER = ("base", "workspace", "environment", "headless")
PATHS_IN_THE_PROJECT = ("out", "folder", "file", "save", "to")
OPEN_REFUSED = "open returns a live object: read it over HTTP with status or show"
MAX_BODY = 16 << 20
CHUNK = 1 << 20


class Refused(Exception):
    """A request the server does not take. The status is the first argument."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


@dataclass
class Job:
    """One verb played in its own process, and what it said once it ended."""

    org: str
    project: str
    process: Any
    pipe: Any
    said: dict[str, Any] | None = None


@dataclass
class Settings:
    """The state of one server: where the spaces are, what a call may reach, its jobs."""

    root: Path
    credentials_dir: Path | None = None
    bounds: Bounds = field(default_factory=Bounds)
    jobs: dict[str, Job] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self) -> None:
        self.root = Path(self.root).resolve()

    def place(self, org: str, project: str | None = None) -> tuple[Path, Environment]:
        """Return the folder a route names, a space or a project, and the environment of its calls.

        The server creates neither, so an absent one is a route that does not exist.
        The only root a call may write under is that folder.
        """
        names = (org,) if project is None else (org, project)
        for name in names:
            try:
                check_name(name, what="project")
            except ConfigError as exc:
                raise Refused(404, f"{name!r} is not a name this server serves") from exc
        space = self.root / org
        if not space.is_dir():
            raise Refused(404, f"no space for the organisation {org}")
        target = space if project is None else space / "projects" / project
        if not target.is_dir():
            raise Refused(404, f"no project {project} in the space of {org}")
        credentials = None
        if self.credentials_dir is not None:
            file = self.credentials_dir / f"{org}.toml"
            credentials = file if file.is_file() else None
        bounds = replace(self.bounds, allowed_roots=(target,))
        return target, Environment(credentials=credentials, bounds=bounds)

    def start(
        self,
        org: str,
        project: str,
        verb: str,
        arguments: dict[str, Any],
        place: Path,
        target: Any = None,
    ) -> dict[str, Any]:
        """Play a verb in its own process, and return the job that tells how it goes."""
        context = multiprocessing.get_context("spawn")
        ours, theirs = context.Pipe(duplex=False)
        process = context.Process(target=target or child, args=(verb, arguments, place, theirs))
        process.start()
        theirs.close()
        job = uuid.uuid4().hex
        with self.lock:
            self.jobs[job] = Job(org, project, process, ours)
        return {"job": job, "pid": process.pid}

    def read_job(self, org: str, project: str, job: str) -> dict[str, Any]:
        """Return the state of a job of this project: running, done, refused, failed or died."""
        with self.lock:
            found = self.jobs.get(job)
            if found is None or (found.org, found.project) != (org, project):
                raise Refused(404, f"no job {job} in this project")
            if found.said is not None:
                return found.said
            # The process is read before the pipe: once it is gone, what it said is in the pipe.
            alive = found.process.is_alive()
            if found.pipe.poll():
                try:
                    state, payload = found.pipe.recv()
                except EOFError:
                    found.process.join(1)
                    found.said = {"state": "died", "exitcode": found.process.exitcode}
                else:
                    found.said = {
                        "state": state,
                        "result" if state == "done" else "refusal": payload,
                    }
            elif not alive:
                found.said = {"state": "died", "exitcode": found.process.exitcode}
            return found.said or {"state": "running", "pid": found.process.pid}

    def stop_jobs(self) -> None:
        """End the processes still running, with a signal a run answers by stopping cleanly."""
        with self.lock:
            running = [job.process for job in self.jobs.values() if job.process.is_alive()]
        for process in running:
            process.terminate()
        for process in running:
            process.join(10)
            if process.is_alive():
                process.kill()

    def store(self, project: Path, raw_name: str, stream: BinaryIO, size: int) -> dict[str, Any]:
        """Write *size* bytes of *stream* under ``inputs/`` of *project*, and say where.

        The bytes pass through ``<root>/.inbox/``, on the same file system as the
        projects, so the last step is one rename. The name starts with the first
        eight digits of the sha256: the same bytes under the same name give the same
        file, other bytes under it are refused.
        """
        name = upload_name(raw_name)
        inbox = self.root / ".inbox"
        inbox.mkdir(exist_ok=True)
        part, digest, left = inbox / f"{uuid.uuid4().hex}.part", hashlib.sha256(), size
        try:
            with part.open("wb") as out:
                while left:
                    block = stream.read(min(CHUNK, left))
                    if not block:
                        raise Refused(400, f"the body stopped {left} bytes short of its length")
                    digest.update(block)
                    out.write(block)
                    left -= len(block)
            sha = digest.hexdigest()
            target = project / "inputs" / f"{sha[:8]}_{name}"
            if target.exists():
                if _sha256_of(target) != sha:
                    raise Refused(409, f"inputs/{target.name} already holds other bytes")
            else:
                target.parent.mkdir(exist_ok=True)
                os.replace(part, target)
        finally:
            part.unlink(missing_ok=True)
        return {"path": f"inputs/{target.name}", "sha256": sha, "bytes": size}


def upload_name(raw: str) -> str:
    """Return the name a file is kept under: lower case, a stem of ``[a-z0-9_-]``, an extension."""
    stem, dot, extension = raw.lower().partition(".")
    stem = re.sub(r"[^a-z0-9_-]", "_", stem)[:80]
    if not stem:
        raise Refused(400, f"{raw!r} gives no file name")
    extension = re.sub(r"[^a-z0-9.]", "_", extension)[:12].rstrip(".")
    return f"{stem}.{extension}" if dot and extension else stem


def _sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(CHUNK):
            digest.update(block)
    return digest.hexdigest()


def jsonable(value: Any, root: Path | None = None) -> Any:
    """Return *value* as JSON data, or raise ``TypeError`` for a type that does not cross.

    A path below *root*, as a path or as a text, is written relative to it.
    """
    if isinstance(value, Enum):
        return jsonable(value.value, root)
    if isinstance(value, str):
        return _relative(Path(value), root) if _is_below(value, root) else value
    if value is None or isinstance(value, (int, float, bool)):
        return None if isinstance(value, float) and not math.isfinite(value) else value
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, os.PathLike):
        return _relative(Path(value), root)
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "to_json"):  # a pandas table or series, whose to_dict has another shape
        return json.loads(value.to_json(orient="split", date_format="iso"))
    if hasattr(value, "to_dict"):
        return jsonable(value.to_dict(), root)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: jsonable(getattr(value, f.name), root) for f in dataclasses.fields(value)}
    if isinstance(value, Mapping):
        return {str(key): jsonable(item, root) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [jsonable(item, root) for item in value]
    if type(value).__module__ == "numpy" and hasattr(value, "item"):
        return jsonable(value.item(), root)
    raise TypeError(f"a {type(value).__name__} does not cross the wire")


def _is_below(text: str, root: Path | None) -> bool:
    """Say whether a text is the absolute path of *root* or of something below it."""
    if root is None:
        return False
    prefix = root.as_posix()
    return text == prefix or text.startswith(prefix.rstrip("/") + "/")


def _relative(path: Path, root: Path | None) -> str:
    if root is not None:
        for candidate, base in ((path, root), (path.resolve(), root.resolve())):
            if candidate.is_relative_to(base):
                return candidate.relative_to(base).as_posix()
    return path.as_posix()


def _outside(text: str) -> bool:
    """Say whether a path text is absolute, reads a home folder, or climbs with ``..``."""
    windows = PureWindowsPath(text)
    return (
        "\0" in text
        or text.startswith("~")
        or PurePosixPath(text).is_absolute()
        or bool(windows.drive or windows.root)
        or ".." in re.split(r"[\\/]", text)
    )


def _under(place: Path, argument: str, value: Any) -> str:
    """Return the absolute path of a path argument below *place*, or refuse it."""
    refusal = Refused(400, f"{argument} names a path outside the project")
    if not isinstance(value, str) or _outside(value):
        raise refusal
    resolved = (place / value).resolve()
    if not resolved.is_relative_to(place.resolve()):
        raise refusal
    return str(resolved)


def _confined(verb: str, arguments: dict[str, Any], place: Path) -> None:
    """Refuse or make absolute every argument that names a path, so none leaves the project."""
    for name in ("ref", "refs"):
        if arguments.get(name) is None:
            continue
        texts = arguments[name] if name == "refs" else [arguments[name]]
        if not isinstance(texts, list) or not all(isinstance(t, str) for t in texts):
            raise Refused(400, f"{name} is {'a list of texts' if name == 'refs' else 'a text'}")
        for text in texts:
            if _outside(text):
                raise Refused(400, f"{name} names a path outside the project")
    for name in PATHS_IN_THE_PROJECT:
        if arguments.get(name) is not None:
            arguments[name] = _under(place, name, arguments[name])
    source = arguments.get("source")
    if isinstance(source, Mapping):
        if verb != "check" and source.get("schema") == REQUEST_SCHEMA:
            try:
                arguments["source"] = RunRequest.model_validate(dict(source))
            except ValueError as exc:
                raise Refused(400, f"the run request is refused: {exc}") from exc
    elif isinstance(source, str):
        if not source.lstrip().startswith("{"):
            arguments["source"] = _under(place, "source", source)
    elif source is not None:
        raise Refused(400, "source is a document, a run request or a path in the project")


def arguments_of(
    verb: str, body: Mapping[str, Any], place: Path, environment: Environment
) -> dict[str, Any]:
    """Return the keyword arguments of a call: the body, checked, plus what the server fills.

    The server fills ``base`` and ``workspace`` with *place* (the project of a
    project route, the space of an organisation route), ``environment`` with the
    one of the route and ``headless`` with ``True``, for each the verb takes. The
    body names none of them.
    """
    taken = [name for name in SET_BY_THE_SERVER if name in body]
    if taken:
        raise Refused(400, f"{', '.join(taken)} are set by the server, not by the request")
    arguments = dict(body)
    if verb == "show":
        what = arguments.get("what", "summary")
        if what == "field":
            raise Refused(400, "a field crosses as a file: use export")
        if what == "figure" and not arguments.get("save"):
            raise Refused(400, "a figure crosses as a file: give save")
    if verb == "example" and arguments.get("add") and environment.bounds.allowed_hosts is not None:
        raise Refused(
            400,
            "example add fetches outside the hosts this server allows: "
            "install it on the server with hmp example",
        )
    if verb not in OF_AN_ORGANISATION:
        _confined(verb, arguments, place)
    signature = inspect.signature(getattr(hmp, verb))
    given = {"base": place, "workspace": place, "environment": environment, "headless": True}
    arguments.update({name: value for name, value in given.items() if name in signature.parameters})
    try:
        signature.bind(**arguments)
    except TypeError as exc:
        raise Refused(400, f"{verb}: {exc}") from exc
    return arguments


def call(verb: str, body: Mapping[str, Any], place: Path, environment: Environment) -> Any:
    """Play one verb on a body, with the arguments the server sets."""
    return getattr(hmp, verb)(**arguments_of(verb, body, place, environment))


def child(verb: str, arguments: dict[str, Any], place: Path, pipe: Any) -> None:
    """Target of a job process: play the verb, send what came back, a refusal or a fault."""
    try:
        message = ("done", jsonable(getattr(hmp, verb)(**arguments), place))
    except Exception as exc:  # noqa: BLE001 - the parent reads every end
        message = ("refused" if isinstance(exc, HydroModPyError) else "failed", refusal(exc))
    pipe.send(message)


def refusal(exc: BaseException) -> dict[str, Any]:
    """Return the body of an error: its code, its sentence, and the diagnostics it carries."""
    said: dict[str, Any] = {
        "code": getattr(exc, "code", type(exc).__name__),
        "message": str(exc),
    }
    if getattr(exc, "diagnostics", ()):
        said["diagnostics"] = jsonable(exc.diagnostics)
    return said


class Handler(BaseHTTPRequestHandler):
    """The routes, all under ``/v1``. ``Refused`` is a 4xx, a library refusal 422, a fault 500."""

    server_version = "hydromodpy-server"
    settings: Settings

    def do_GET(self) -> None:  # noqa: N802
        self.respond(self.get)

    def do_POST(self) -> None:  # noqa: N802
        self.respond(self.post)

    def do_PUT(self) -> None:  # noqa: N802
        self.respond(self.put)

    def respond(self, route: Any) -> None:
        try:
            status, payload = route(parts_of(self.path))
        except Refused as exc:
            status, payload = exc.status, {"message": str(exc)}
        except HydroModPyError as exc:
            status, payload = 422, refusal(exc)
        except Exception as exc:  # noqa: BLE001 - a fault of the library is said, not hidden
            traceback.print_exc(file=sys.stderr)
            status, payload = 500, refusal(exc)
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def get(self, parts: list[str]) -> tuple[int, Any]:
        if parts == ["v1", "health"]:
            return 200, {"version": hmp.__version__, "image": image_of()}
        if parts == ["v1", "schema", "request"]:
            return 200, RunRequest.model_json_schema()
        if len(parts) == 5 and parts[0] == "v1" and parts[3] == "jobs":
            self.settings.place(parts[1], parts[2])
            return 200, self.settings.read_job(parts[1], parts[2], parts[4])
        raise Refused(404, f"no route {self.path}")

    def post(self, parts: list[str]) -> tuple[int, Any]:
        if parts[:1] != ["v1"] or len(parts) not in (3, 4):
            raise Refused(404, f"no route {self.path}")
        org, verb = parts[1], parts[-1]
        project = parts[2] if len(parts) == 4 else None
        if project is not None and verb == "open":
            raise Refused(400, OPEN_REFUSED)
        if verb not in (OF_AN_ORGANISATION if project is None else IN_A_CHILD | IN_A_THREAD):
            raise Refused(404, f"no route {self.path}")
        place, environment = self.settings.place(org, project)
        arguments = arguments_of(verb, self.body(), place, environment)
        if verb in IN_A_CHILD:
            return 202, self.settings.start(org, project or "", verb, arguments, place)
        return 200, jsonable(getattr(hmp, verb)(**arguments), place)

    def put(self, parts: list[str]) -> tuple[int, Any]:
        if len(parts) != 5 or parts[0] != "v1" or parts[3] != "inputs":
            raise Refused(404, f"no route {self.path}")
        place, environment = self.settings.place(parts[1], parts[2])
        ceiling = environment.bounds.max_download_bytes
        length = self.headers.get("Content-Length", "")
        if not length.isdigit() or int(length) > ceiling:
            raise Refused(413, f"a file is sent with its length, at most {ceiling} bytes")
        stored = self.settings.store(place, unquote(parts[4]), self.rfile, int(length))
        return 201, stored

    def body(self) -> dict[str, Any]:
        """Return the JSON object of the body, an empty one when it has no length."""
        length = self.headers.get("Content-Length", "0")
        if self.headers.get("Transfer-Encoding") or not length.isdigit():
            raise Refused(400, "a body is sent with its Content-Length")
        if int(length) > MAX_BODY:
            raise Refused(413, f"a body is a JSON object of {MAX_BODY} bytes at most")
        data = self.rfile.read(int(length))
        try:
            body = json.loads(data or b"{}")
        except ValueError as exc:
            raise Refused(400, f"the body is not JSON: {exc}") from exc
        if not isinstance(body, dict):
            raise Refused(400, "the body is a JSON object of the arguments of the verb")
        return body

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return


def parts_of(path: str) -> list[str]:
    """Return the segments of the path of a request, without its query."""
    return path.partition("?")[0].strip("/").split("/")


def serve(settings: Settings, host: str, port: int) -> ThreadingHTTPServer:
    """Return a server bound to *settings*, not started. Port ``0`` takes a free port."""
    handler = type("BoundHandler", (Handler,), {"settings": settings})
    return ThreadingHTTPServer((host, port), handler)
