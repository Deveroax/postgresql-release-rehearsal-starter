---
name: postgresql-release-rehearsal-starter
description: "Use when rehearsing synthetic PostgreSQL drift and forward corrections."
---

# Disposable PostgreSQL rehearsal

## Use / do not use

Use this small example to learn source-bound migration checks, deliberate drift rejection,
transaction rollback and a separately numbered correction. Do not use it to migrate an
application, authorize production work, recover an unknown cluster or certify a release.
It is a local review candidate, not an installed skill or a published package.

## Prerequisites and boundary

Use Python 3.9+ standard library and a matching PostgreSQL 18 tool directory containing
`initdb`, `pg_ctl`, `psql`, `pg_controldata` and `postgres`. The exercised configuration is
PostgreSQL 18.3 (Homebrew), macOS; other versions/platforms are not certified. Use an
existing, approved, short scratch root and a new private evidence directory outside the
candidate. Never install tools or start services implicitly.

The runner accepts **no external database address, URL, data directory or credentials**.
It allocates a fresh private directory, initializes its own cluster and connects only to
that directory's Unix socket with explicit database, user and port. TCP is disabled.
Subprocess environments are allowlisted, not inherited; credential/service files are
explicitly disabled and `psql -X -w` prevents startup files and password prompting.
Local trust authentication is only for this synthetic fixture inside mode-0700 directories;
it is not a production authentication recommendation or isolation from the same OS user.

## Workflow

1. Review the small SQL fixtures and numbered migrations. Generate a SHA-256/size manifest
   **outside** the candidate before execution. Include the runner, tests and documentation,
   not only migration names. Preserve the original manifest if any file changes.
2. Admit exact path membership and bytes before allocating a cluster. Capture binary
   paths, versions and hashes; record the plan, SQL input hashes, command outcomes and
   scenario inventory in private evidence. A hash is identity evidence, not authorization.
3. Apply `001_baseline.sql` in one transaction and query rows and catalogs explicitly.
4. Drop the named quantity CHECK as synthetic drift. Require the specific assertion's
   `P0001` diagnostic, not just any nonzero command.
5. Insert a probe row and create a probe table before that assertion inside one transaction.
   Require the intended error **and identical before/after row/catalog observations**.
6. Apply `002_restore_quantity_check.sql` as a new transaction. Do not edit `001` or
   manufacture a migration-history entry. Prove restoration, preserved existing rows,
   successful valid input and `23514` invalid-input rejection with rollback comparison.
7. In a separate temporary copy, create a manifest, change a migration, and invoke the
   real CLI. Require source rejection before tool commands, evidence allocation or initdb.
8. Before shutdown, match the in-memory/disk marker, root identity, executable hashes,
   offline system identifier and live data/socket/port/server identity. Stop only the
   recorded cluster. Verify stopped status, PID absence, empty socket directory and
   clean control-file state before deleting the positively identified run directory.

## Evidence and failures

Keep `PASS`, `EXPECTED_REJECTION`, `FAIL` and `NOT_EXECUTED` distinct. Negative database
cases pass only when both the specified diagnostic and rollback checks pass. Read raw
command records as well as the summary. Keep failed-run directories and receipts; after
a source fix use a new manifest and a **fresh** cluster/evidence directory. Select the
final authoritative run explicitly by run ID and source manifest, never by newest filename.

On timeout, identity mismatch or cleanup uncertainty, retain the path and marker; report
unknown process state rather than assuming the server stopped. Do not kill by process
name, reuse an existing socket or recursively remove a guessed directory. Recovery needs
a separate identity-bound inspection; this starter deliberately has no generic cleanup CLI.

## Limits

This checks one fictional table and one named CHECK constraint—not complete catalog,
privilege, security or semantic equivalence. Deterministic mocked refusal tests are not
live crash or adversarial cleanup proofs. Source hashes do not prove historical production
bytes, protect against arbitrary hostile same-user filesystem races or establish rights.
There is no migration-history subsystem, exactly-once production guarantee, signing,
production authorization, remote service integration or automatic publishing. Independent
review remains separate from the user-confirmed origin/redistribution authority and MIT license.
