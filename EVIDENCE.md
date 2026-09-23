# Evidence format (synthetic illustration only)

This abbreviated JSON is **invented format documentation, not an execution receipt**:

```json
{
  "run_id": "SYNTHETIC-EXAMPLE",
  "status": "FAIL",
  "scenarios": {
    "A_baseline": {"status": "PASS"},
    "B_drift": {"status": "EXPECTED_REJECTION", "returncode": 3, "sqlstate": "P0001"},
    "C_rollback": {"status": "FAIL", "error": "synthetic comparison mismatch"},
    "D_correction": {"status": "NOT_EXECUTED"}
  }
}
```

Actual runs include all six inventory entries, exact before/after observations, cleanup,
source and executable identities and private paths. Interpret expected SQL rejection only
alongside its command diagnostic and equal before/after observations. The source mismatch
uses exit 2 and no database mutation rather than SQLSTATE. `pg_ctl status` exit 3 after
shutdown is lifecycle evidence, not an SQL rejection. A journal records command and
scenario starts/finishes; a missing finish is incomplete evidence, not an implicit PASS.
