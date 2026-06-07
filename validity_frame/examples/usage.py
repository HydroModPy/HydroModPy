"""Small usage examples for the `validity_frame` package.

Run after installing the package locally (editable):

    pip install -e validity_frame
    python validity_frame/examples/usage.py

This script shows direct use of `ValidityFrame` and the automatic loader
based on entry points.
"""

from types import SimpleNamespace

from validity_frame import ValidityFrame, create_validity_frame


def direct_examples() -> None:
    print("--- Direct examples ---")
    vf = ValidityFrame(tolerant=False)

    state_missing = SimpleNamespace(data={"a": 1})
    state_ok = SimpleNamespace(run_id="run-1", data={"a": 1})
    steps = ("step1",)

    try:
        vf.verify(state_missing, steps)
        print("state_missing: verification passed (unexpected)")
    except Exception as exc:
        print("state_missing: verification failed as expected:", exc)

    try:
        vf.verify(state_ok, steps)
        print("state_ok: verification passed")
    except Exception as exc:
        print("state_ok: verification failed (unexpected):", exc)


def wrapper_example() -> None:
    print("--- Automatic loading example ---")
    vf = create_validity_frame(tolerant=True)
    state = SimpleNamespace(run_id="example", data={"a": 1})
    steps = ("step1",)
    vf.verify(state, steps)
    print("create_validity_frame() loaded the default frame successfully")


if __name__ == "__main__":
    direct_examples()
    wrapper_example()
