"""Deterministic unit tests; cleanup danger paths are MOCKED, not live PostgreSQL."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import rehearsal as r


class SafetyTests(unittest.TestCase):
    def temp(self):
        # Caller must select the approved scratch root; never use system temp implicitly.
        self.assertIn('REHEARSAL_TEST_SCRATCH', os.environ)
        t = tempfile.TemporaryDirectory(prefix='pgu-', dir=os.environ['REHEARSAL_TEST_SCRATCH'])
        self.addCleanup(t.cleanup)
        return Path(t.name)

    def test_source_mismatch_and_membership(self):
        root = self.temp()
        (root / '001.sql').write_text('SELECT 1;')
        expected = r.manifest(root)
        r.verify_sources(root, expected)
        (root / '001.sql').write_text('SELECT 2;')
        with self.assertRaisesRegex(RuntimeError, 'SOURCE_IDENTITY_MISMATCH'):
            r.verify_sources(root, expected)
        (root / '001.sql').write_text('SELECT 1;')
        (root / 'extra.sql').write_text('SELECT 3;')
        with self.assertRaisesRegex(RuntimeError, 'SOURCE_IDENTITY_MISMATCH'):
            r.verify_sources(root, expected)

    def test_symlink_source_refused(self):
        root = self.temp()
        (root / 'a').write_text('synthetic')
        (root / 'b').symlink_to(root / 'a')
        with self.assertRaisesRegex(RuntimeError, 'symlink'):
            r.manifest(root)

    def test_isolated_connection_and_environment(self):
        with patch.dict(os.environ, {'PGHOST': 'external.invalid', 'PGPORT': '9999',
                                    'PGDATABASE': 'private', 'PGSERVICE': 'ambient',
                                    'PGPASSWORD': 'synthetic-not-a-secret', 'PGOPTIONS': '-c search_path=wrong',
                                    'PGPASSFILE': '/ambient/file'}):
            env = r.isolated_env('/new/home', '/approved/scratch', '/tools')
        self.assertEqual(set(k for k in env if k.startswith('PG')),
                         {'PGPASSFILE', 'PGSERVICEFILE', 'PGSYSCONFDIR'})
        self.assertEqual(env['PGPASSFILE'], os.devnull)
        self.assertEqual(env['PGSERVICEFILE'], os.devnull)
        self.assertEqual(env['PGSYSCONFDIR'], '/new/home')
        argv = r.connection_args('/tools/psql', '/new/socket', 6543)
        for flag, value in [('-h', '/new/socket'), ('-p', '6543'), ('-U', 'rehearsal_owner'), ('-d', 'postgres')]:
            self.assertEqual(argv[argv.index(flag)+1], value)
        for value in ('-X', '-w', 'ON_ERROR_STOP=1', 'VERBOSITY=verbose'):
            self.assertIn(value, argv)

    def test_negative_classification_requires_error_and_rollback(self):
        good = {'returncode': 3, 'stderr': 'ERROR:  P0001: REHEARSAL_DRIFT: exact\n'}
        self.assertTrue(r.negative_ok(good, 'P0001', 'REHEARSAL_DRIFT: exact', {'a': 1}, {'a': 1}))
        for result in ({'returncode': 2, 'stderr': good['stderr']},
                       {'returncode': 0, 'stderr': good['stderr']},
                       {'returncode': 3, 'stderr': 'ERROR:  42601: syntax error'},
                       {'returncode': 3, 'stderr': 'connection refused'}):
            self.assertFalse(r.negative_ok(result, 'P0001', 'REHEARSAL_DRIFT: exact', 1, 1))
        self.assertFalse(r.negative_ok(good, 'P0001', 'REHEARSAL_DRIFT: exact', 1, 2))

    def harness(self):
        root = self.temp()
        source, evidence = root / 'source', root / 'evidence'
        source.mkdir(); evidence.mkdir()
        return r.Rehearsal(source, {}, root / 'tools', root, evidence)

    def test_evidence_statuses_distinct(self):
        h = self.harness()
        self.assertTrue(all(v['status'] == 'NOT_EXECUTED' for v in h.results.values()))
        h.scenario('A_baseline', lambda: {'status': 'PASS'})
        h.scenario('B_drift', lambda: {'status': 'EXPECTED_REJECTION'})
        def fail():
            raise RuntimeError('synthetic failure')
        with self.assertRaises(RuntimeError):
            h.scenario('C_rollback', fail)
        statuses = {v['status'] for v in h.results.values()}
        self.assertEqual(statuses, {'PASS', 'EXPECTED_REJECTION', 'FAIL', 'NOT_EXECUTED'})
        records = [json.loads(line) for line in (h.evidence / 'journal.jsonl').read_text().splitlines()]
        self.assertEqual([x['kind'] for x in records], ['scenario_start', 'scenario_finish'] * 3)

    def test_cleanup_marker_mismatch_no_command_no_delete_MOCKED(self):
        h = self.harness()
        h.root = h.scratch / 'owned'; h.root.mkdir()
        (h.root / 'd').mkdir(); (h.root / 's').mkdir()
        h.marker = {'root_inode': h.root.stat().st_ino, 'root_device': h.root.stat().st_dev,
                    'run_id': 'original'}
        (h.root / 'marker.json').write_text(json.dumps({**h.marker, 'run_id': 'different'}))
        with patch.object(h, 'command') as command, patch('rehearsal.shutil.rmtree') as remove:
            with self.assertRaisesRegex(RuntimeError, 'marker mismatch'):
                h.cleanup()
            command.assert_not_called(); remove.assert_not_called()
        self.assertTrue(h.root.exists())

    def test_cleanup_system_and_binary_mismatch_MOCKED(self):
        expected = {'system_identifier': '123', 'binaries': {'psql': 'hash'}}
        for sid, binaries in [('999', expected['binaries']), ('123', {'psql': 'changed'})]:
            with patch('rehearsal.subprocess.run') as command, patch('rehearsal.shutil.rmtree') as remove:
                with self.assertRaises(RuntimeError):
                    r.check_marker(expected, dict(expected), sid, binaries)
                command.assert_not_called(); remove.assert_not_called()

    def test_pg18_baseline_includes_not_null_catalog_entries(self):
        h = self.harness()
        observed = {
            'rows': [[1, 'pencil', 3], [2, 'notebook', 5]],
            'constraints': [
                ['items_id_not_null', 'n', True, 'NOT NULL id'],
                ['items_label_not_null', 'n', True, 'NOT NULL label'],
                ['items_pkey', 'p', True, 'PRIMARY KEY (id)'],
                ['items_qty_nonnegative', 'c', True, 'CHECK ((qty >= 0))'],
                ['items_qty_not_null', 'n', True, 'NOT NULL qty']],
            'columns': [['id', 'integer', True], ['label', 'text', True], ['qty', 'integer', True]],
            'probe': None}
        with patch.object(h, 'migration'), patch.object(h, 'fixture', return_value=''), \
             patch.object(h, 'sql'), patch.object(h, 'observe', return_value=observed):
            self.assertEqual(h.baseline()['status'], 'PASS')

    def test_timeout_cleanup_retains_paths_MOCKED(self):
        h = self.harness(); h.timed_out = True
        with patch.object(h, 'command') as command, patch('rehearsal.shutil.rmtree') as remove:
            with self.assertRaisesRegex(RuntimeError, 'timeout'):
                h.cleanup()
            command.assert_not_called(); remove.assert_not_called()

    def test_post_start_evidence_failure_still_reaches_cleanup_MOCKED(self):
        h = self.harness()
        def start():
            h.root = h.scratch / 'simulated-cluster'
            h.root.mkdir()
            h.event('simulated_start')
            raise RuntimeError('synthetic post-start failure')
        with patch.object(h, 'discover'), patch.object(h, 'source_rejection', return_value={'status': 'EXPECTED_REJECTION'}), \
             patch.object(h, 'start', side_effect=start), \
             patch.object(h, 'cleanup', return_value={'status': 'PASS'}) as cleanup, \
             patch('pathlib.Path.open', side_effect=OSError('synthetic journal storage failure')):
            # Final receipt cannot be written either, but cleanup must already have happened.
            with self.assertRaises(OSError):
                h.run()
            cleanup.assert_called_once()
        self.assertTrue(h.errors)


if __name__ == '__main__':
    unittest.main()
