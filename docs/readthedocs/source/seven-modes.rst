Seven ways to drive HydroModPy
==============================

HydroModPy exposes a single :class:`~hydromodpy.Project` façade and seven
supported usage modes. Every mode feeds the same pipeline - only the
construction layer differs.

Mode 1 - CLI TOML
-----------------

Full TOML driven by ``hmp run``::

    hmp run run_transient_nwt.toml

Mode 2 - Frontend (JSON)
------------------------

JSON payloads validated by Pydantic::

    project = hmp.Project.from_json(payload)
    project.run()

Mode 3 - TOML + Python orchestration
-------------------------------------

A TOML owns the model state; Python orchestrates multiple runs::

    project = hmp.Project("project.toml")
    for sy in [0.01, 0.05, 0.3]:
        project.run(Sy=sy, name=f"sy_{sy}")

Mode 4 - Full Python
--------------------

No TOML. Pydantic configs built inline with factory methods::

    cfg = hmp.Config(
        workspace=WorkspaceConfig(project_root=HERE),
        geographic=hmp.Geographic.from_outlet(x=..., y=..., dem=...),
        domain=hmp.Domain.with_thickness(30.0),
        flow=hmp.Flow.homogeneous(K=5e-5, Sy=0.05),
        simulation=hmp.Sim.transient(time=("2000-01-01", "2002-12-31", "1 month"), flow="modflownwt"),
    )
    hmp.Project(cfg).run()

Mode 5 - Step-by-step
---------------------

Atomic run verbs for debug and inspection::

    sim_id = project.prepare(K=5e-5)
    project.execute(sim_id)
    project.ingest(sim_id)
    project.render(sim_id)
    project.cleanup(sim_id)

Mode 6 - Cellular notebook
--------------------------

Lazy construction lets notebooks reload only the phase that changed::

    project = hmp.Project.lazy(cfg)
    project.build_geographic()  # slow, once
    project.load_data()         # slow, once
    for size in [30, 50, 100, 200, 500]:
        project.cfg.mesh_catchment.cell_size = size
        project.build_mesh()    # fast, per size

Mode 7 - Primitive objects
--------------------------

Use the underlying primitives without a :class:`Project`:
:class:`CatchmentDelineation`, :class:`Domain`, :class:`HydroMesh`,
:class:`Flow`, data managers.
