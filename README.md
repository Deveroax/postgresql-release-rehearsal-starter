# PostgreSQL release-rehearsal starter

A small synthetic PostgreSQL release-rehearsal starter using Python's
standard library, plain SQL and real PostgreSQL command-line tools.
Licensed under [MIT](LICENSE). Copyright (c) 2026 Nic Richards.
Deveroax — prepared with Hermes Agent assistance.
See [attribution](ATTRIBUTION.md) for user-confirmed origin and license coverage.

## What it demonstrates

| Scenario | Required proof |
| --- | --- |
| A — baseline | Explicit rows, columns and constraints for `rehearsal.items` |
| B — drift | Missing named CHECK produces the specific `P0001` assertion; state unchanged |
| C — rollback | Preceding insert and table creation disappear after that assertion fails |
| D — correction | New `002` restores invariant, preserves rows, accepts valid input, rejects invalid input with `23514` and rollback |
| E — source identity | A tampered temporary copy is rejected by the real CLI before any cluster allocation |
| Cleanup | Matched cluster identity, stopped server, absent PID/socket and removed run root |

E runs before database allocation; A–D each use explicit transaction/session boundaries.
An unexpected error stops dependent scenarios and leaves them `NOT_EXECUTED`. Expected
SQL errors are not success unless both the diagnostic and explicit before/after checks agree.
The fixtures represent pencils and notebooks, not copied application data. `001` remains
unchanged; `002` is a forward correction after deliberate fixture drift. There is no history
table, fake applied entry or generalized migration engine.

## Prerequisites and run

The exercised toolchain is **PostgreSQL 18.3 (Homebrew) on macOS**. The runner admits a
matching PostgreSQL 18 toolset but does not claim other minor versions were exercised.
Python 3.9+ is required. No packages are needed. Use an existing installation; all five
executables (`initdb`, `pg_ctl`, `psql`, `pg_controldata`, `postgres`) must be in one directory.
Do not run as root. No Docker or service manager is used.

From the candidate directory, choose approved existing directories (placeholders below):

```sh
PG_BIN=/absolute/path/to/postgresql/bin
SCRATCH=/absolute/path/to/approved/short/scratch
REVIEW=/absolute/path/to/private/review

REHEARSAL_TEST_SCRATCH="$SCRATCH" python3 -E -B -m unittest discover -s tests -v
python3 -E -B rehearsal.py manifest --output "$REVIEW/source-manifest.json"
python3 -E -B rehearsal.py run   --manifest "$REVIEW/source-manifest.json"   --bin-dir "$PG_BIN" --scratch-root "$SCRATCH"   --evidence "$REVIEW/run-001"
```

Create the private review directory first. The manifest and run evidence destinations must
not exist already; preserve them and use new names on rerun. Keep the entire Unix socket
pathname below 100 bytes. Scratch space must be outside the candidate. The harness
uses a unique mode-0700 `pgr-*` directory beneath it; tests use `pgu-*` and the tamper
probe uses `pgt-*`. Run Python with `-B` to avoid adding source-tree bytecode files;
new unmanifested files intentionally invalidate source admission. `-E` ignores Python
startup environment overrides. Do not edit source while a run is executing.

A successful run prints a compact JSON summary and returns 0. A source admission
mismatch returns 2 before creating run evidence. Other rehearsal failures return 1;
preflight/filesystem errors can also exit nonzero with a traceback. Preserve all failures.

## Why it cannot target an existing database

There are no host, database URL, external data-directory or password CLI options. All
connections are constructed from a newly allocated run directory. The server listens
only on that directory's Unix socket, not TCP; fixed socket suffix 6543 is safe because
each directory is unique. Host authentication is rejected. Local trust is limited to the
private synthetic cluster; the same OS user remains trusted.

Ambient PostgreSQL/loader variables are not forwarded. The harness explicitly substitutes
null credential/service files, a private HOME, `-X`, `-w`, explicit host/port/database/user,
and `ON_ERROR_STOP=1`. It never queries an ambient server to discover ports or versions.
Tool version discovery runs executables with `--version` only.

## Evidence and test classes

`tests/test_rehearsal.py` contains deterministic tests for source identity, connection
isolation, negative classification, status accounting and **mocked** dangerous cleanup
refusals/evidence-I/O failure. Those tests do not start PostgreSQL. The `run` command
executes real SQL in a new PostgreSQL cluster; its source-rejection scenario invokes a
real child CLI against a changed copy (but correctly executes no SQL in that child).

Private `journal.jsonl` records command argv, SQL text/hash, exit status, stdout/stderr,
scenario boundaries, binary identities and cluster markers. `result.json` records the
inventory and comparisons; `server.log` is copied before successful root removal.
These are actual host-specific records, not public sample data. Keep them outside this
candidate. `EVIDENCE.md` describes the format using an explicitly synthetic example.

Before removal the runner verifies marker/root/binary/offline/live identity, stops with
the recorded `pg_ctl`, checks status 3 plus PID and socket absence and clean shutdown
state, and removes only its own directory. Timeout or identity mismatch retains residue
and reports its path. No automatic recovery against arbitrary retained clusters exists.
Evidence-write errors cannot skip the finally-based cleanup attempt, but may prevent a
final receipt; in that case a nonzero process exit is not proof of shutdown.

## Unproven / out of scope

No production safety, exactly-once execution, historical migration provenance, catalog
closure, remote databases, role-security model, concurrent users, hostile same-user
races, hard process death, power loss, disk-full live recovery, Windows, or broad version
matrix is proven. Binary hashes do not attest shared libraries. The caller trusts the
reviewed runner and manifest; this is not signed authorization or malicious-code isolation.
No migration file is applied to a pre-existing server. Origin and redistribution authority are user-confirmed.
This educational starter does not authorize production database operations.
