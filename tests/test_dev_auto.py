"""Offline Git fixture tests for the temporary Termux updater."""
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dev_auto import BRANCH, source_signature, sync_once, ci_passed


def run(*args):
    subprocess.run(args, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


class AutoUpdaterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.remote, self.author, self.tablet = (root / name for name in ('remote.git', 'author', 'tablet'))
        run('git', 'init', '-q', '--bare', str(self.remote))
        run('git', 'init', '-q', '-b', BRANCH, str(self.author))
        for name, value in [('user.name', 'Test'), ('user.email', 'test@example.invalid')]:
            run('git', '-C', str(self.author), 'config', name, value)
        (self.author / 'study.py').write_text('first\n')
        run('git', '-C', str(self.author), 'add', '.')
        run('git', '-C', str(self.author), 'commit', '-qm', 'initial')
        run('git', '-C', str(self.author), 'remote', 'add', 'origin', str(self.remote))
        run('git', '-C', str(self.author), 'push', '-q', '-u', 'origin', BRANCH)
        run('git', 'clone', '-q', '--branch', BRANCH, str(self.remote), str(self.tablet))

    def tearDown(self):
        self.tmp.cleanup()

    def push(self, text):
        (self.author / 'study.py').write_text(text)
        run('git', '-C', str(self.author), 'add', 'study.py')
        run('git', '-C', str(self.author), 'commit', '-qm', 'update')
        run('git', '-C', str(self.author), 'push', '-q', 'origin', BRANCH)

    def test_safe_fast_forward_and_idempotence(self):
        self.assertFalse(sync_once(self.tablet, allow_local_remote=True))
        self.push('second\n')
        self.assertTrue(sync_once(self.tablet, allow_local_remote=True))
        self.assertEqual((self.tablet / 'study.py').read_text(), 'second\n')
        self.assertFalse(sync_once(self.tablet, allow_local_remote=True))

    def test_dirty_checkout_is_not_overwritten(self):
        self.push('second\n')
        (self.tablet / 'study.py').write_text('LOCAL EDIT\n')
        self.assertFalse(sync_once(self.tablet, allow_local_remote=True))
        self.assertEqual((self.tablet / 'study.py').read_text(), 'LOCAL EDIT\n')

    def test_untracked_npm_file_does_not_block_fast_forward(self):
        self.push('second\n')
        generated = self.tablet / 'package-lock.json'
        generated.write_text('generated locally')
        self.assertTrue(sync_once(self.tablet, allow_local_remote=True))
        self.assertEqual((self.tablet / 'study.py').read_text(), 'second\n')
        self.assertEqual(generated.read_text(), 'generated locally')

    def test_colliding_untracked_file_is_not_overwritten(self):
        (self.author / 'collision.txt').write_text('remote contents')
        run('git', '-C', str(self.author), 'add', 'collision.txt')
        run('git', '-C', str(self.author), 'commit', '-qm', 'add collision')
        run('git', '-C', str(self.author), 'push', '-q', 'origin', BRANCH)
        collision = self.tablet / 'collision.txt'
        collision.write_text('MY LOCAL CONTENT')
        self.assertFalse(sync_once(self.tablet, allow_local_remote=True))
        self.assertEqual(collision.read_text(), 'MY LOCAL CONTENT')

    def test_ci_gate_blocks_unverified_commit_and_accepts_green(self):
        self.push('second\n')
        self.assertFalse(sync_once(self.tablet, allow_local_remote=True,
                                   ci_check=lambda sha: False))
        self.assertEqual((self.tablet / 'study.py').read_text(), 'first\n')
        self.assertTrue(sync_once(self.tablet, allow_local_remote=True,
                                  ci_check=lambda sha: True))
        self.assertEqual((self.tablet / 'study.py').read_text(), 'second\n')

    @patch('dev_auto.subprocess.run')
    def test_ci_check_requires_exact_successful_github_actions_commit(self, execute):
        sha = 'a' * 40
        result = execute.return_value
        result.returncode = 0
        def check(app='github-actions', status='completed', conclusion='success', ref=sha):
            return {'name': 'mywords-ci-gate', 'head_sha': ref,
                    'app': {'slug': app}, 'status': status, 'conclusion': conclusion}
        for entry, expected in [
            (check(), True), (check(status='in_progress'), False),
            (check(conclusion='failure'), False),
            (check(ref='b'*40), False),
            (check(app='other-app'), False),
        ]:
            result.stdout = json.dumps({'check_runs': [entry]})
            self.assertEqual(ci_passed(sha), expected)
        result.returncode = 403
        self.assertFalse(ci_passed(sha))

    def test_wrong_branch_refused(self):
        run('git', '-C', str(self.tablet), 'switch', '-qc', 'another-branch')
        self.push('second\n')
        self.assertFalse(sync_once(self.tablet, allow_local_remote=True))
        self.assertEqual((self.tablet / 'study.py').read_text(), 'first\n')

    def test_unexpected_origin_refused(self):
        self.push('second\n')
        self.assertFalse(sync_once(self.tablet))
        self.assertEqual((self.tablet / 'study.py').read_text(), 'first\n')

    def test_source_fingerprint_ignores_databases_and_vendor(self):
        with tempfile.TemporaryDirectory() as folder:
            app=Path(folder)
            (app / 'web').mkdir()
            (app / 'web/vendor').mkdir()
            (app / 'server.py').write_text('print(1)\n')
            before=source_signature(app)
            (app / 'local.sqlite3').write_text('data')
            (app / 'web/vendor/vue.js').write_text('library')
            self.assertEqual(before, source_signature(app))
            (app / 'web/app.js').write_text('console.log(2)')
            self.assertNotEqual(before, source_signature(app))


if __name__ == '__main__':
    unittest.main()
