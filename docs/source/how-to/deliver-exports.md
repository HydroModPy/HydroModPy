# Deliver exports

An `[[export]]` block that names `deliver_to` sends the files of that block once the run is
sealed, and each copy is recorded in the run. I use it to hand a partner the files of a run
without copying them by hand, and to keep a remote copy on an FTP server.

## Name the destination

`deliver_to` takes a list of destinations. Each one is a local or UNC path, or an `ftp://`,
`ftps://` or `sftp://` address.

| Form | Example | Where the file lands |
|---|---|---|
| local folder, absolute, ending in `/` | `/data/depot/` | `.../depot/head_last.tif` |
| local file, absolute | `/data/depot/head_last.tif` | at that path |
| UNC folder, Windows | `\\server\share\depot\` | under the share |
| FTP folder | `ftp://gis.example.org/depot/` | under the remote folder |
| FTP file, with a port | `ftp://gis.example.org:2121/head_last.tif` | at that name |
| FTPS folder | `ftps://gis.example.org/depot/` | under the remote folder |
| SFTP folder | `sftp://data.example.org/depot/` | under the remote folder |

```toml
[[export]]
variables = "head"
time = "last"
file = "head_last.tif"
deliver_to = ["/data/depot/", "ftp://gis.example.org/depot/"]
```

A folder address ends with `/`. A file address names one file, so the block writes
`file = "..."`. A view that names neither `folder` nor `file` is written at the root of the
run, outside `exports/`, and is refused for delivery. Give it a `folder` or a `file`.

A destination is never created. The subfolders of the file under `exports/` are, so
`/data/depot/` must exist and be writable, and `/data/depot/sub/` is made when the file is
`sub/head.tif`. A typo stops the run before any calculation, not after the solve.

## `credentials.toml`

A remote address takes its identity from `credentials.toml`. The file sits outside every
project and every workspace, readable by its owner alone (mode 600, and a group or other
read bit is refused). Its default place is `<state home>/credentials.toml`, usually
`~/.local/state/hydromodpy/credentials.toml` on Linux, and `--credentials PATH` names another.

The file holds one `[[host]]` block per address prefix. The longest prefix that matches a
destination gives its identity, so no user name is ever written in a project file.

```toml
[[host]]
prefix = "ftp://gis.example.org/"
user = "partner"
password = "the-password"

[[host]]
prefix = "ftps://gis.example.org:2121/"
user = "partner"
password_file = "/home/me/.config/gis-password"

[[host]]
prefix = "sftp://data.example.org/"
user = "me"
key_file = "/home/me/.ssh/id_ed25519"
host_fingerprint = "SHA256:the-fingerprint-the-server-shows"
```

A prefix carries the port when the address names one, so `ftps://gis.example.org:2121/`
answers `ftps://gis.example.org:2121/depot/` and `ftps://gis.example.org/` does not. The
password is written in clear or named by `password_file`. An `sftp://` address needs the
`sftp` extra (`pip install 'hydromodpy[sftp]'`), a password or a `key_file`, and the
`host_fingerprint` the server shows. The `key_file` is an ed25519, ECDSA or RSA private key,
in OpenSSH or PEM form, without a passphrase. A clear `ftp://` sends its password in clear and warns
once per destination, so use `ftps://` when the server offers it (explicit TLS, `PROT P`).

## The check before the run

Every destination is checked before the first step. A host is public by default, and
`--allow-host HOST` names one. A call that names hosts reaches only those, which is the way to
reach a private address such as `127.0.0.1`. A local folder must exist and be writable. A
remote address needs its `[[host]]` block, and the server must answer and enter the folder. A
refusal stops the run with one sentence, and nothing has been computed.

```bash
hmp run nancon_daily.toml \
  --credentials ~/.local/state/hydromodpy/credentials.toml --allow-host 127.0.0.1
```

## Read the states

Each file of a block and each destination make one pair. The run appends a `pending` line,
pushes the file through `<name>.part`, renames it and compares its size, in at most three
attempts, 1 s then 2 s apart. A failed attempt removes its `.part`. The last line of a pair is
`delivered` or `failed`, with the sha256, the bytes and the number of attempts. A `failed`
line carries the sentence that says what went wrong. A file of `exports/` that cannot be read
gives a `failed` line with one attempt and no sha256 or bytes.

A delivery failure does not fail the run. The run stays sealed and completed, `hmp run` exits
0, and the log holds a `WARNING` for the file and its address. `hmp catalog show <run>` lists
the deliveries after the exports, and the library reads `run.deliveries`.

## Deliver again

```bash
hmp export nancon_daily --deliver --credentials ~/.local/state/hydromodpy/credentials.toml
```

It reads the sealed `config.toml` and the lines of the run, checks each destination against
the hosts and folders this call allows as the run did, and warns of a clear `ftp://` password.
A refused destination gives a `failed` line. It sends every pair whose last line is not
`delivered`, and sends again a delivered file whose bytes changed since, because a
promotion or `--regen` rewrites `exports/`. It prints one line per pair and
`Delivered 2 of 3 file(s)`, and exits 1 when a line stays `failed`, 0 otherwise. `--format
json` prints `{"deliveries": [...]}`. `--deliver` takes no variable, no `--list`, no `--regen`
and no export option, and is refused with exit code 2. The library call is
`hmp.export(run, deliver=True)`.

A run with windows delivers each window as it is sealed, so a fixed remote file keeps the
last window. A calibration delivers the run it promoted for each case, and only once the
session is `completed`. A session that stops early or promotes no run delivers nothing and
logs a `WARNING`.

## What a published copy keeps

`hmp publish` copies the run without `deliver_to`. The key is removed from `config.toml` and
`config.resolved.toml`, and `exports/index.json` never records it. A copy never delivers
anything.
