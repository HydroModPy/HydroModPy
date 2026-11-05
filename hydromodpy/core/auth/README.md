# core/auth

This folder answers one question: who is acting? It is a single small module, `__init__.py`,
and today it knows only one actor, the local user.

## Contents

- `AuthBackend` is the protocol every backend satisfies: it names the actor and says whether a read or a write is allowed.
- `LocalAuthBackend` is the backend that ships. It reads `HMP_USER`, then `USER` or `USERNAME`, then the system user, and allows every read and write.
- `get_auth_backend` picks the backend from `HMP_AUTH_BACKEND` and refuses an unknown name with a `ValueError`.

## Who imports it

Only the command line: the privacy purge in `hydromodpy/cli/_workers/privacy.py` resolves the actor here.

## Where to add what

- A new backend: a class that satisfies `AuthBackend`, then its name in the table that `get_auth_backend` reads, both in `__init__.py`.
- A rule about what a user may do: in the backend, never in the caller.

The layer rules are checked by `tests/unit/architecture/`. This folder imports only the standard library.
