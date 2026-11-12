Serve over HTTP
===============

The repository keeps a thin HTTP layer beside the wheel, ``hydromodpy_server/``. It calls the
verbs of the facade and nothing else, so a frontend that is not written in Python can check a
document, play a run and read its results. It uses the Python standard library only. The wheel
does not ship it: it runs from a source checkout or from the Docker image of the repository.

Start the server
----------------

.. code-block:: console

   $ python -m hydromodpy_server --root /srv/hmp --credentials-dir /etc/hmp/credentials
   serving on http://127.0.0.1:8765

``--root`` is the folder of the spaces. Each organisation has one space ``<root>/<org>``, and
each study one project ``<root>/<org>/projects/<project>``. The server creates neither, so an
operator makes them first, for example with ``hmp workspace init`` and ``hmp project new``.
``--credentials-dir`` holds one ``<org>.toml`` per organisation and must lie outside the root.
``--allow-host`` (repeated) names the hosts a call may fetch from, and
``--max-download-bytes`` bounds a download and an upload. ``--host``, ``--port`` and ``--warm``
are described by ``--help``.

The server refuses to start, with exit code 2, when the root does not exist, when the
credentials folder lies under the root, or when it runs inside the image without
``HMP_IMAGE_DIGEST``. At start it removes what an earlier upload left in ``<root>/.inbox/``
and checks a full document once, so the first ``check`` of a client is fast.

Put a proxy in front
--------------------

The server has no authentication. Put it behind a proxy that authenticates each user and lets an
organisation reach only its own path ``/v1/<org>/``. Inside one organisation, a call reads and
writes only under its project: the server passes the project as the one allowed root of the
call, and it refuses a path argument that is absolute or climbs with ``..``.

Routes
------

- ``GET /v1/health`` gives the version and, inside the image, its tag and digest.
- ``GET /v1/schema/request`` gives the JSON Schema of a run request.
- ``POST /v1/<org>/<verb>`` serves ``example`` and ``doctor``, the two verbs of a space.
- ``POST /v1/<org>/<project>/<verb>`` serves any other verb of the facade. ``check``,
  ``stop``, ``status``, ``trash``, ``compare``, ``show``, ``export`` and ``publish`` answer
  200. ``run``, ``calibrate``, ``spinup`` and ``replay`` answer 202 with a job.
- ``GET /v1/<org>/<project>/jobs/<job>`` gives the state of a job of this project.
- ``PUT /v1/<org>/<project>/inputs/<name>`` uploads a file under ``inputs/`` and answers 201.

The body of a verb is a JSON object of its keyword arguments, 16 MiB at most. The server fills
``base``, ``workspace``, ``environment`` and ``headless`` itself and refuses them in the body.
``open`` is not served, because it returns a live object: read a project with ``status`` and
``show``. ``show`` of a field is refused (use ``export``), and ``show`` of a figure needs
``save``. When the server runs with ``--allow-host``, ``example`` with ``add`` is refused,
because its download would not read the allowed hosts.

A refusal is a JSON object with ``code``, ``message`` and, when the library gives them,
``diagnostics``. The status says the family. It is 400 for a body or argument the server does
not take, 404 for an unknown route, organisation, project or job, 409 for an upload under a
name that holds other bytes, 413 for a body too long, 422 for a refusal of the library and 500
for any other fault.

Check and run
-------------

A client posts ``{"source": {...}}`` to ``/v1/<org>/<project>/check`` and a run request to
``/v1/<org>/<project>/run``. The run answers ``{"job": "4f0c...", "pid": 41207}``, and
``GET .../jobs/4f0c...`` gives ``{"state": "done", "result": {...}}``.

A run, a calibration, a spin-up and a replay each play in their own process, started by
``spawn``. The process takes the run folder and names it, and its ``RunOutcome`` comes back
through the job. A job is ``running``, then ``done`` with its ``result``, ``refused`` or
``failed`` with its ``refusal``, or ``died`` with its exit code. The server keeps its jobs for its
own life only. The run folder is the truth, so ``status`` and ``show`` still read a run after a
restart.

Upload a file
-------------

A ``PUT`` of the bytes to ``/v1/<org>/<project>/inputs/rain.csv`` answers
``{"path": "inputs/5c859d8b_rain.csv", "sha256": "...", "bytes": 25}``.

The file is written through ``<root>/.inbox/`` and renamed under ``inputs/`` as
``<sha256[:8]>_<name>``, with the name in lower case and its odd characters turned into ``_``.
The same bytes give the same answer. Other bytes under a taken name are refused with 409. A
``source = "file"`` block of a document then names ``inputs/5c859d8b_rain.csv``.

In Docker
---------

The image carries the server under ``/opt/hmp``. Start it with another entry point, a fixed
host name and the digest of the image, so each run seals the image it ran in:

.. code-block:: console

   $ docker run -d --hostname hmp-server -p 8765:8765 -v /srv/hmp:/project \
       -e HMP_IMAGE_DIGEST=sha256:<digest> \
       --entrypoint python <image> -m hydromodpy_server --root /project --host 0.0.0.0

See also
--------

- :doc:`build-a-frontend` for the schema, the check and the run request a frontend builds.
- :doc:`/get-started/install` for the Docker image.
