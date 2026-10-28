"""Local MyWords development supervisor for Termux (not a boot service).

One process starts Flask, watches source changes, fetches only the selected
public main branch from GitHub, fast-forwards a clean checkout, and restarts Flask.
It cannot change production or delete the local SQLite study database.
"""
from pathlib import Path
import json
import os
import re
import subprocess
import sys
import time

APP_DIR = Path(__file__).resolve().parent
REPO = APP_DIR
BRANCH = 'main'
REMOTE = re.compile(
    r'^(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)'
    r'Dmitry-dev-pet/mywords-local(?:\.git)?/?$', re.IGNORECASE
)
POLL_SECONDS = 60
LOCAL_POLL_SECONDS = 2


def git(repo, *args, timeout=45):
    env = os.environ.copy()
    env['GIT_TERMINAL_PROMPT'] = '0'
    return subprocess.run(['git', *args], cwd=repo, text=True,
                          capture_output=True, stdin=subprocess.DEVNULL,
                          timeout=timeout, env=env, check=False)


def ci_passed(sha):
    """Require the exact GitHub Actions quality gate on the candidate commit."""
    if not re.fullmatch(r"[a-f0-9]{40}", sha):
        return False
    try:
        response = subprocess.run([
            'gh', 'api',
            f'repos/Dmitry-dev-pet/mywords-local/commits/{sha}/check-runs?per_page=100'
        ], cwd=REPO, text=True, capture_output=True,
           stdin=subprocess.DEVNULL, timeout=20, check=False)
        if response.returncode != 0:
            return False
        entries = json.loads(response.stdout).get('check_runs', [])
        return any(
            c.get('name') == 'mywords-ci-gate'
            and c.get('head_sha') == sha
            and c.get('app', {}).get('slug') == 'github-actions'
            and c.get('status') == 'completed'
            and c.get('conclusion') == 'success'
            for c in entries
        )
    except (OSError, ValueError, TypeError, AttributeError, subprocess.TimeoutExpired):
        return False


def sync_once(repo=REPO, *, allow_local_remote=False, ci_check=None):
    """Only fast-forward a clean checkout on the pinned owner-controlled branch."""
    try:
        active = git(repo, 'branch', '--show-current')
        remote = git(repo, 'remote', 'get-url', 'origin')
        if active.returncode or active.stdout.strip() != BRANCH:
            print('[MyWords] Not on the development branch; automatic updates paused.', flush=True)
            return False
        if remote.returncode or not (REMOTE.fullmatch(remote.stdout.strip()) or allow_local_remote):
            print('[MyWords] Unexpected Git remote; automatic updates paused.', flush=True)
            return False
        # npm may generate an untracked package-lock.json during setup. This is
        # not an edit to tracked source code. A fast-forward merge itself still
        # refuses to overwrite colliding untracked files, so leave those intact.
        status = git(repo, 'status', '--porcelain', '--untracked-files=no')
        if status.returncode or status.stdout.strip():
            print('[MyWords] Tracked local Git changes detected; keeping files intact.', flush=True)
            return False
        fetched = git(repo, 'fetch', '--quiet', '--no-tags', 'origin', f'refs/heads/{BRANCH}')
        if fetched.returncode:
            print('[MyWords] GitHub unavailable; running the existing local version.', flush=True)
            return False
        before, after = git(repo, 'rev-parse', 'HEAD'), git(repo, 'rev-parse', 'FETCH_HEAD')
        if before.returncode or after.returncode or not after.stdout.strip():
            return False
        if before.stdout.strip() == after.stdout.strip():
            return False
        # Never install unverified GitHub commits. Local Git fixture tests can
        # inject a predicate; the real Termux branch checks GitHub Actions.
        approved = (ci_check(after.stdout.strip()) if ci_check is not None
                    else (allow_local_remote or ci_passed(after.stdout.strip())))
        if not approved:
            print('[MyWords] Candidate has no successful CI gate; keeping current version.', flush=True)
            return False
        merged = git(repo, 'merge', '--ff-only', 'FETCH_HEAD')
        if merged.returncode:
            print('[MyWords] Fast-forward failed; no local files were overwritten.', flush=True)
            return False
        print('[MyWords] GitHub update applied; restarting the local server.', flush=True)
        return True
    except (OSError, subprocess.TimeoutExpired):
        print('[MyWords] Sync timed out/unavailable; local server keeps running.', flush=True)
        return False


def source_signature(app=APP_DIR):
    """Ignore databases, virtualenv, downloaded Vue runtime and user content."""
    files = [*app.glob('*.py'), *app.glob('web/*.js'),
             *app.glob('web/*.html'), *app.glob('web/*.css'), *app.glob('web/*.mjs')]
    result = []
    for path in files:
        try:
            stat = path.stat()
            result.append((path.name, stat.st_size, stat.st_mtime_ns))
        except OSError:
            continue
    return tuple(sorted(result))


def start_server(app=APP_DIR):
    python = app / '.venv' / 'bin' / 'python'
    if not python.is_file():
        raise SystemExit('Run bash setup.sh first to install the local Flask environment.')
    env = os.environ.copy()
    env['PYTHONUNBUFFERED'] = '1'
    print('[MyWords] Serving http://127.0.0.1:8791/  (Ctrl+C stops both processes)', flush=True)
    return subprocess.Popen([str(python), '-u', 'server.py'], cwd=app, env=env)


def stop_server(process):
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=6)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3)


def main():
    process = start_server()
    stamp = source_signature()
    launcher_mtime = Path(__file__).stat().st_mtime_ns
    next_fetch = time.monotonic()   # Check remote on first start, then once/minute.
    next_local = time.monotonic()
    try:
        while True:
            if process.poll() is not None:
                print(f'[MyWords] Flask stopped (exit {process.returncode}); supervisor exiting.', flush=True)
                return process.returncode or 1
            now = time.monotonic()
            changed = False
            if now >= next_fetch:
                next_fetch = time.monotonic() + POLL_SECONDS
                changed = sync_once()
            if now >= next_local or changed:
                next_local = time.monotonic() + LOCAL_POLL_SECONDS
                fresh = source_signature()
                changed = changed or fresh != stamp
                stamp = fresh
            if changed:
                stop_server(process)
                # If the updater itself changed, start the newly fetched version.
                new_mtime = Path(__file__).stat().st_mtime_ns
                if new_mtime != launcher_mtime:
                    os.execv(sys.executable, [sys.executable, str(Path(__file__).resolve())])
                process = start_server()
            time.sleep(1)
    except KeyboardInterrupt:
        print('\n[MyWords] Development session stopped.', flush=True)
        return 0
    finally:
        stop_server(process)


if __name__ == '__main__':
    sys.exit(main())
