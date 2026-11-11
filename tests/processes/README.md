# Process tests

A test goes here when it starts more than one process on one project, store, index or
data folder. The unit tier stays free of processes, and this tier is where the
claim of a lock, a version or a file is tried by real competitors.

The tests start their children with `spawn`, the only method Windows has, so the
same code runs on Linux and on Windows. `test_windows_kernel.py` holds the cases that
only a real kernel decides, such as a rename over an open file, a lock whose holder
was killed and a worker tree that must die with its worker. The assertion that
depends on the kernel is written once per platform.

The folders follow the packages they exercise (`data/`, `results/`, `server/`).
`tests/conftest.py` tags each test `processes` by its path and gives it 300 seconds.
The push job plays the tier on Linux, and the weekly job plays it on Linux, macOS
and `windows-latest`.

Run it with `pytest tests/processes -q`.
