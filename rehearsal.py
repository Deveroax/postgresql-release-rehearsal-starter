#!/usr/bin/env python3
"""A disposable-only, source-bound PostgreSQL teaching rehearsal."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

NAMES = ('A_baseline', 'B_drift', 'C_rollback', 'D_correction', 'E_source_rejection', 'cleanup')
TOOLS = ('initdb', 'pg_ctl', 'psql', 'pg_controldata', 'postgres')


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def manifest(root):
    root = Path(root)
    result = {}
    for p in sorted(root.rglob('*')):
        require(not p.is_symlink(), 'source symlink rejected')
        if p.is_file():
            result[str(p.relative_to(root))] = {'size': p.stat().st_size, 'sha256': digest(p)}
    return result


def verify_sources(root, expected):
    require(manifest(root) == expected, 'SOURCE_IDENTITY_MISMATCH')


def isolated_env(home, scratch, bindir):
    # Allowlist: no ambient PG*, service, password, locale, or loader variables.
    return {'PATH': str(bindir) + os.pathsep + '/usr/bin:/bin',
            'HOME': str(home), 'LC_ALL': 'C', 'TMPDIR': str(scratch),
            'PGPASSFILE': os.devnull, 'PGSERVICEFILE': os.devnull,
            'PGSYSCONFDIR': str(home)}


def connection_args(psql, socket, port):
    return [str(psql), '-X', '-w', '-q', '-A', '-t',
            '-v', 'ON_ERROR_STOP=1', '-v', 'VERBOSITY=verbose',
            '-h', str(socket), '-p', str(port), '-d', 'postgres', '-U', 'rehearsal_owner']


def negative_ok(result, state, diagnostic, before, after):
    # psql 3 = script error with ON_ERROR_STOP; connection errors are not evidence.
    return (result['returncode'] == 3
            and re.search(r'ERROR:\s+' + re.escape(state) + r':\s+' + re.escape(diagnostic),
                          result['stderr']) is not None
            and before == after)


def inventory():
    return {name: {'status': 'NOT_EXECUTED'} for name in NAMES}


def check_marker(expected, observed, offline_id, binaries):
    require(expected == observed, 'cleanup marker mismatch')
    require(expected['system_identifier'] == offline_id, 'cleanup system identifier mismatch')
    require(expected['binaries'] == binaries, 'cleanup binary identity mismatch')


class Rehearsal:
    def __init__(self, source, expected, bindir, scratch, evidence):
        self.source, self.expected = source, expected
        self.bindir, self.scratch, self.evidence = bindir, scratch, evidence
        self.results = inventory()
        self.errors = []
        self.root = None
        self.marker = None
        self.timed_out = False
        self.seq = 0
        self.run_id = uuid.uuid4().hex
        self.binaries = {}
        self.env = isolated_env('/nonexistent', scratch, bindir)

    def event(self, kind, **fields):
        self.seq += 1
        try:
            with (self.evidence / 'journal.jsonl').open('a') as f:
                f.write(json.dumps({'sequence': self.seq, 'kind': kind, **fields}) + '\n')
                f.flush()
                os.fsync(f.fileno())
        except OSError as exc:
            self.errors.append('evidence I/O: ' + str(exc))

    def command(self, argv, sql=None):
        argv = list(map(str, argv))
        self.event('command_start', argv=argv, sql=sql,
                   sql_sha256=hashlib.sha256(sql.encode()).hexdigest() if sql else None)
        start = time.monotonic()
        try:
            p = subprocess.run(argv, input=sql, text=True, capture_output=True,
                               env=self.env, cwd=str(self.root or self.source), timeout=45)
            result = {'argv': argv, 'returncode': p.returncode,
                      'stdout': p.stdout, 'stderr': p.stderr}
        except subprocess.TimeoutExpired:
            self.timed_out = True
            self.event('command_timeout', argv=argv)
            raise RuntimeError('command timeout; retain cluster for identity-bound recovery')
        self.event('command_finish', elapsed=time.monotonic()-start, **result)
        return result

    def good(self, argv, sql=None):
        result = self.command(argv, sql)
        require(result['returncode'] == 0, 'unexpected command failure: ' + json.dumps(result))
        return result['stdout'].strip()

    def sql(self, text, negative=False):
        argv = connection_args(self.bindir / 'psql', self.root / 's', self.port)
        # A script on stdin, not -c, makes ON_ERROR_STOP exit status 3 unambiguous.
        result = self.command(argv, text)
        if negative:
            return result
        require(result['returncode'] == 0, 'unexpected SQL failure: ' + json.dumps(result))
        return result['stdout'].strip()

    def fixture(self, name):
        verify_sources(self.source, self.expected)
        return (self.source / 'fixtures' / name).read_text()

    def migration(self, name):
        verify_sources(self.source, self.expected)
        self.sql('BEGIN;\n' + (self.source / 'migrations' / name).read_text() + '\nCOMMIT;')

    def observe(self):
        return json.loads(self.sql(self.fixture('observe.sql')))

    def scenario(self, name, body):
        self.event('scenario_start', name=name)
        start = time.monotonic()
        try:
            value = body()
            self.results[name] = value or {'status': 'PASS'}
        except Exception as exc:
            self.results[name] = {'status': 'FAIL', 'error': str(exc)}
            raise
        finally:
            self.event('scenario_finish', name=name, elapsed=time.monotonic()-start,
                       result=self.results[name])

    def discover(self):
        versions = []
        for name in TOOLS:
            p = self.bindir / name
            require(p.is_file() and os.access(p, os.X_OK), 'missing executable: ' + str(p))
            version = self.good([p, '--version'])
            match = re.search(r'\(PostgreSQL\) (\d+\.\d+)', version)
            require(match is not None, 'unrecognized PostgreSQL version')
            versions.append(match.group(1))
            self.binaries[name] = {'path': str(p), 'sha256': digest(p), 'version': version}
        require(len(set(versions)) == 1, 'toolchain versions differ')
        require(versions[0].split('.')[0] == '18', 'this starter admits PostgreSQL 18 only')

    def binary_now(self):
        return {n: {**v, 'sha256': digest(v['path'])} for n, v in self.binaries.items()}

    def offline(self):
        text = self.good([self.bindir / 'pg_controldata', self.root / 'd'])
        found = re.search(r'^Database system identifier:\s+(\d+)$', text, re.M)
        require(found is not None, 'missing offline system identifier')
        return found.group(1), text

    def live(self):
        return json.loads(self.sql("SELECT json_build_object('system_identifier', system_identifier::text, "
            "'data', current_setting('data_directory'), 'socket', current_setting('unix_socket_directories'), "
            "'port', current_setting('port'), 'listen', current_setting('listen_addresses'), "
            "'version', current_setting('server_version')) FROM pg_control_system();"))

    def validate_live(self):
        value = self.live()
        for key in ('system_identifier', 'data', 'socket', 'port'):
            require(value[key] == self.marker[key], 'live cluster identity mismatch: ' + key)
        require(value['listen'] == '', 'TCP listening not disabled')
        expected = re.search(r'\(PostgreSQL\) (\d+\.\d+)', self.binaries['postgres']['version']).group(1)
        require(value['version'].split()[0] == expected, 'live server version differs')
        return value

    def start(self):
        self.root = Path(tempfile.mkdtemp(prefix='pgr-', dir=self.scratch)).resolve()
        (self.root / 's').mkdir(mode=0o700)
        (self.root / 'home').mkdir(mode=0o700)
        require(len(os.fsencode(str(self.root / 's' / '.s.PGSQL.6543'))) < 100,
                'scratch socket path too long')
        self.port = 6543  # Unique socket directory, no TCP listener; no external port discovery.
        self.env = isolated_env(self.root / 'home', self.scratch, self.bindir)
        self.marker = {'run_id': self.run_id, 'root': str(self.root),
                       'root_inode': self.root.stat().st_ino, 'root_device': self.root.stat().st_dev,
                       'data': str(self.root / 'd'), 'socket': str(self.root / 's'),
                       'port': str(self.port), 'binaries': self.binaries,
                       'source_manifest': self.expected, 'system_identifier': None}
        self.save_marker()
        self.good([self.bindir / 'initdb', '-D', self.root / 'd', '-U', 'rehearsal_owner',
                   '--auth-local=trust', '--auth-host=reject', '--no-locale', '--encoding=UTF8'])
        self.marker['system_identifier'] = self.offline()[0]
        self.save_marker()
        # Config paths come only from our own mkdtemp. PostgreSQL string escaping is explicit.
        quote = lambda x: "'" + str(x).replace("'", "''") + "'"
        (self.root / 'd' / 'postgresql.conf').write_text(
            "listen_addresses = ''\nport = 6543\nunix_socket_permissions = 0700\n"
            "unix_socket_directories = " + quote(self.root / 's') + "\n")
        self.good([self.bindir / 'pg_ctl', '-D', self.root / 'd', '-l', self.root / 'server.log',
                   '-p', self.bindir / 'postgres', '-w', '-t', '20', 'start'])
        self.event('cluster_live', identity=self.validate_live(), marker=self.marker,
                   postmaster_pid=(self.root / 'd' / 'postmaster.pid').read_text().splitlines()[0])

    def save_marker(self):
        tmp = self.root / 'marker.new'
        tmp.write_text(json.dumps(self.marker, indent=2) + '\n')
        tmp.replace(self.root / 'marker.json')
        self.event('marker', marker=self.marker)

    def source_rejection(self):
        # Real CLI admission test in a separate copy, without touching the candidate.
        with tempfile.TemporaryDirectory(prefix='pgt-', dir=self.scratch) as tmp:
            root = Path(tmp)
            copy = root / 'candidate'
            shutil.copytree(self.source, copy)
            mf = root / 'manifest.json'
            mf.write_text(json.dumps(manifest(copy)))
            with (copy / 'migrations' / '001_baseline.sql').open('a') as f:
                f.write('\n-- deliberate source mismatch\n')
            child_evidence = root / 'rejected-evidence'
            before = sorted(p.name for p in self.scratch.iterdir())
            result = self.command([sys.executable, '-E', '-B', str(copy / 'rehearsal.py'), 'run',
                '--manifest', mf, '--bin-dir', self.bindir, '--scratch-root', self.scratch,
                '--evidence', child_evidence])
            after = sorted(p.name for p in self.scratch.iterdir())
            require(result['returncode'] == 2 and result['stderr'].strip() == 'SOURCE_IDENTITY_MISMATCH',
                    'wrong source rejection')
            require(not child_evidence.exists() and before == after, 'source rejection had side effects')
            return {'status': 'EXPECTED_REJECTION', 'returncode': 2,
                    'diagnostic': result['stderr'].strip(), 'cluster_allocated': False,
                    'evidence_directory_created': False, 'scratch_membership_unchanged': True}

    def baseline(self):
        self.migration('001_baseline.sql')
        self.sql(self.fixture('assert.sql'))
        state = self.observe()
        require(state['rows'] == [[1, 'pencil', 3], [2, 'notebook', 5]], 'baseline rows differ')
        expected_constraints = [
            ['items_id_not_null', 'n', True, 'NOT NULL id'],
            ['items_label_not_null', 'n', True, 'NOT NULL label'],
            ['items_pkey', 'p', True, 'PRIMARY KEY (id)'],
            ['items_qty_nonnegative', 'c', True, 'CHECK ((qty >= 0))'],
            ['items_qty_not_null', 'n', True, 'NOT NULL qty']]
        require(state['probe'] is None and state['constraints'] == expected_constraints,
                'baseline catalog differs')
        require(state['columns'] == [['id', 'integer', True], ['label', 'text', True],
                                     ['qty', 'integer', True]], 'baseline columns differ')
        self.baseline_state = state
        return {'status': 'PASS', 'observed': state}

    def drift(self):
        self.sql('BEGIN;\n' + self.fixture('drift.sql') + '\nCOMMIT;')
        before = self.observe()
        expected_drift = {**self.baseline_state, 'constraints': [
            row for row in self.baseline_state['constraints'] if row[0] != 'items_qty_nonnegative']}
        require(before == expected_drift, 'drift did not remove exactly the intended constraint')
        result = self.sql('BEGIN;\n' + self.fixture('assert.sql') + '\nCOMMIT;', negative=True)
        after = self.observe()
        require(negative_ok(result, 'P0001', 'REHEARSAL_DRIFT: items_qty_nonnegative missing or changed',
                            before, after), 'drift rejected for wrong reason or changed state')
        return {'status': 'EXPECTED_REJECTION', 'returncode': result['returncode'],
                'sqlstate': 'P0001', 'before': before, 'after': after}

    def rollback(self):
        before = self.observe()
        result = self.sql('BEGIN;\n' + self.fixture('negative_prefix.sql') + '\n'
                          + self.fixture('assert.sql') + '\nCOMMIT;', negative=True)
        after = self.observe()
        require(negative_ok(result, 'P0001', 'REHEARSAL_DRIFT: items_qty_nonnegative missing or changed',
                            before, after), 'negative transaction or rollback proof failed')
        return {'status': 'EXPECTED_REJECTION', 'returncode': result['returncode'], 'sqlstate': 'P0001',
                'before': before, 'after': after, 'row_and_ddl_rollback': True}

    def correction(self):
        self.migration('002_restore_quantity_check.sql')
        self.sql(self.fixture('assert.sql'))
        restored = self.observe()
        require(restored == self.baseline_state, 'correction changed data or failed catalog restoration')
        self.sql("BEGIN; INSERT INTO rehearsal.items VALUES (3, 'eraser', 0); COMMIT;")
        before = self.observe()
        require(before['rows'] == self.baseline_state['rows'] + [[3, 'eraser', 0]], 'valid insert failed')
        bad = self.sql("BEGIN; UPDATE rehearsal.items SET label='transient' WHERE id=1; "
                       "INSERT INTO rehearsal.items VALUES (4, 'invalid', -1); COMMIT;", negative=True)
        after = self.observe()
        message = 'new row for relation "items" violates check constraint "items_qty_nonnegative"'
        require(negative_ok(bad, '23514', message, before, after), 'invalid input rejection/rollback failed')
        verify_sources(self.source, self.expected)
        return {'status': 'PASS', 'restored': restored, 'valid_insert': True,
                'invalid_insert': {'status': 'EXPECTED_REJECTION', 'sqlstate': '23514',
                                   'returncode': bad['returncode'], 'before': before, 'after': after},
                'earlier_migration_unchanged': True}

    def cleanup(self):
        require(not self.timed_out, 'timeout: residue retained; do not infer startup or shutdown state')
        require(self.root is not None and self.marker is not None, 'no bound cluster to clean')
        require(not self.root.is_symlink() and self.root.parent == self.scratch, 'cleanup path mismatch')
        st = self.root.stat()
        require((st.st_ino, st.st_dev) == (self.marker['root_inode'], self.marker['root_device']),
                'cleanup root identity mismatch')
        for name in ('d', 's', 'marker.json'):
            require(not (self.root / name).is_symlink(), 'cleanup symlink rejected')
        observed = json.loads((self.root / 'marker.json').read_text())
        # Marker equality checked BEFORE any command, including offline inspection.
        require(observed == self.marker, 'cleanup marker mismatch')
        require(self.binary_now() == self.marker['binaries'], 'cleanup binary identity mismatch')
        check_marker(self.marker, observed, self.offline()[0], self.binary_now())
        status = self.command([self.bindir / 'pg_ctl', '-D', self.root / 'd', 'status'])
        if status['returncode'] == 0:
            live = self.validate_live()
            self.event('cleanup_identity', identity=live)
            self.good([self.bindir / 'pg_ctl', '-D', self.root / 'd', '-m', 'fast', '-w', '-t', '20', 'stop'])
        else:
            require(status['returncode'] == 3, 'unknown cluster process status')
        status = self.command([self.bindir / 'pg_ctl', '-D', self.root / 'd', 'status'])
        require(status['returncode'] == 3, 'cluster not stopped')
        require(not (self.root / 'd' / 'postmaster.pid').exists(), 'postmaster PID still present')
        require(not list((self.root / 's').iterdir()), 'socket residue retained')
        offline_id, text = self.offline()
        check_marker(self.marker, json.loads((self.root / 'marker.json').read_text()), offline_id, self.binary_now())
        require(re.search(r'^Database cluster state:\s+shut down$', text, re.M), 'cluster not cleanly shut down')
        log = self.root / 'server.log'
        # Retention failure leaves stopped files in place; never loses the only server log.
        if log.exists():
            shutil.copyfile(log, self.evidence / 'server.log')
        root = str(self.root)
        shutil.rmtree(self.root)
        require(not Path(root).exists(), 'cluster directory removal failed')
        return {'status': 'PASS', 'stopped': True, 'removed': True, 'root': root,
                'system_identifier': offline_id, 'status_returncode': 3}

    def run(self):
        self.event('run_plan', run_id=self.run_id, source_manifest=self.expected,
                   scenario_inventory=list(NAMES), scratch_root=str(self.scratch), bin_dir=str(self.bindir))
        try:
            verify_sources(self.source, self.expected)
            self.discover()
            self.event('toolchain', binaries=self.binaries)
            self.scenario('E_source_rejection', self.source_rejection)
            self.start()
            for name, body in [('A_baseline', self.baseline), ('B_drift', self.drift),
                               ('C_rollback', self.rollback), ('D_correction', self.correction)]:
                self.scenario(name, body)
        except Exception as exc:
            self.errors.append(str(exc))
        finally:
            if self.root is not None:
                try:
                    self.scenario('cleanup', self.cleanup)
                except Exception as exc:
                    self.errors.append(str(exc))
            try:
                verify_sources(self.source, self.expected)
            except Exception as exc:
                self.errors.append(str(exc))
        passed = not self.errors and all(v['status'] in ('PASS', 'EXPECTED_REJECTION') for v in self.results.values())
        result = {'run_id': self.run_id, 'status': 'PASS' if passed else 'FAIL',
                  'scenarios': self.results, 'errors': self.errors, 'binaries': self.binaries,
                  'marker': self.marker, 'residue': str(self.root) if self.root and self.root.exists() else None}
        self.event('run_finish', result=result)
        if self.errors:
            result['status'] = 'FAIL'
        (self.evidence / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps({'status': result['status'], 'evidence': str(self.evidence), 'residue': result['residue']}))
        return 0 if result['status'] == 'PASS' else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    m = sub.add_parser('manifest')
    m.add_argument('--output', required=True, type=Path)
    r = sub.add_parser('run')
    r.add_argument('--manifest', required=True, type=Path)
    r.add_argument('--bin-dir', required=True, type=Path)
    r.add_argument('--scratch-root', required=True, type=Path)
    r.add_argument('--evidence', required=True, type=Path)
    args = parser.parse_args()
    source = Path(__file__).resolve().parent
    if args.action == 'manifest':
        output = args.output.resolve()
        require(source not in output.parents, 'manifest must be outside source')
        with output.open('x') as f:
            json.dump(manifest(source), f, indent=2)
            f.write('\n')
        return 0
    expected = json.loads(args.manifest.read_text())
    try:
        verify_sources(source, expected)
    except RuntimeError:
        print('SOURCE_IDENTITY_MISMATCH', file=sys.stderr)
        return 2  # Before toolchain commands, evidence creation, initdb or cluster allocation.
    scratch = args.scratch_root.resolve(strict=True)
    require(scratch.is_dir(), 'scratch root must already exist')
    require(scratch != source and source not in scratch.parents, 'scratch cannot be inside candidate')
    evidence = args.evidence.resolve()
    require(source not in evidence.parents and evidence != source, 'private evidence cannot be inside candidate')
    require(evidence != scratch and scratch not in evidence.parents, 'durable evidence cannot be inside scratch')
    os.umask(0o077)
    evidence.mkdir(mode=0o700, parents=False, exist_ok=False)
    return Rehearsal(source, expected, args.bin_dir.resolve(strict=True), scratch, evidence).run()


if __name__ == '__main__':
    sys.exit(main())
