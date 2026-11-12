"""Publish this project with a private operation trail and recoverable rollback."""
import argparse
import getpass
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.request
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.app.audit import audit, configure_audit

ROOT = Path('/opt/dual-catalog')
PROJECTS = [('.env.demo', 'dual-catalog-demo'), ('.env', 'dual-catalog')]


def compose(env, project):
    return ['docker', 'compose', '--env-file', str(ROOT / env), '-f', str(ROOT / 'app/compose.production.yaml'), '-p', project]


def plugins():
    existing = set(subprocess.run(['docker', 'ps', '-a', '--format', '{{.Names}}'], capture_output=True, text=True, check=True).stdout.splitlines())
    return {name: subprocess.run(['docker', 'inspect', '--format', '{{.Id}}', name], capture_output=True, text=True, check=True).stdout.strip() for name in ['fish-search', 'qq-summary-bot', 'nginx'] if name in existing}


def health():
    result = {}
    for port in [8092, 8093]:
        for attempt in range(50):
            try:
                with urllib.request.urlopen(f'http://127.0.0.1:{port}/health/ready', timeout=3) as response:
                    value = json.load(response)
                if value.get('status') == 'ready' and value.get('revision') == '0005_gunpla':
                    result[str(port)] = value
                    break
            except OSError:
                pass
            time.sleep(.5)
        else:
            raise RuntimeError('readiness failed')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True)
    parser.add_argument('--reason', required=True)
    parser.add_argument('--migrate', action='store_true')
    parser.add_argument('--import-gunpla')
    args = parser.parse_args()
    if bool(args.import_gunpla) != args.migrate:
        parser.error('--migrate requires --import-gunpla, and imports require --migrate')
    if not re.fullmatch(r'dual-catalog:[0-9]+\.[0-9]+\.[0-9]+', args.image):
        parser.error('only a versioned dual-catalog image is allowed')
    if not 1 <= len(args.reason) <= 300:
        parser.error('reason must contain 1 to 300 characters')
    configure_audit(ROOT / 'data/artifacts/logs', channels={'deploy'})
    context = {'operation_id': uuid4().hex, 'actor': getpass.getuser(), 'actor_ip': (os.environ.get('SSH_CONNECTION', '').split() or [None])[0], 'image': args.image}

    def emit(event, **fields):
        audit(event, channel='deploy', **context, **fields)

    def stage(name, command, **kwargs):
        emit('deployment_step_started', step=name)
        try:
            result = subprocess.run(command, check=True, **kwargs)
        except subprocess.CalledProcessError as error:
            emit('deployment_step_failed', step=name, exit_code=error.returncode)
            raise
        emit('deployment_step_finished', step=name, exit_code=result.returncode)
        return result

    def start_services(prefix):
        for env, project in PROJECTS:
            services = ['api'] if project.endswith('demo') else ['--scale', 'worker=2', 'api', 'worker', 'scheduler']
            stage(prefix + '_' + project, compose(env, project) + ['up', '-d'] + services)
        return health()

    old = {env: (ROOT / env).read_text() for env, _ in PROJECTS}
    private_mode = (ROOT / 'tls/gates').is_dir() or any('AUTH_ENABLED=true' in content for content in old.values())
    previous = {env: next((line.split('=', 1)[1] for line in value.splitlines() if line.startswith('APP_IMAGE=')), 'unknown') for env, value in old.items()}
    before = plugins()
    paths = ['Dockerfile.release', 'backend/app/audit.py', 'backend/app/repository.py', 'backend/app/sync/service.py', 'backend/app/worker.py', 'deploy/preview-nginx.conf', 'backend/app/auth_store.py', 'backend/app/auth.py', 'backend/app/auth_cli.py', 'backend/app/gunpla.py', 'backend/app/sources/gunpla.py', 'backend/migrations/versions/0005_gunpla.py']
    hashes = {name: hashlib.sha256((ROOT / 'app' / name).read_bytes()).hexdigest() for name in paths}
    emit('deployment_started', previous_images=previous, reason=args.reason, source_sha256=hashes)
    try:
        if private_mode:
            from scripts.prepare_auth import set_gate
            set_gate('closed')
            emit('private_gate_closed')
        stage('stop_cache_warmer', compose('.env', 'dual-catalog') + ['stop', 'cache-warmer'])
        build_log = ROOT / ('build-' + args.image.split(':')[1] + '.log')
        with build_log.open('w') as output:
            stage('build_image', ['docker', 'build', '--no-cache', '-f', str(ROOT / 'app/Dockerfile.release'), '-t', args.image, str(ROOT / 'app')], stdout=output, stderr=subprocess.STDOUT)
        build_log.chmod(0o600)
        label = stage('check_image', ['docker', 'image', 'inspect', '--format', '{{index .Config.Labels "org.opencontainers.image.version"}}', args.image], capture_output=True, text=True).stdout.strip()
        if label != args.image.split(':')[1]:
            raise RuntimeError('image version mismatch')
        if private_mode:
            stage('test_private_image', ['docker', 'run', '--rm', '--network', 'none', '--memory', '384m', '--pids-limit', '128', '-e', 'PYTHONDONTWRITEBYTECODE=1', '--entrypoint', 'python', args.image, '-m', 'pytest', '-q', '-p', 'no:cacheprovider'])
        if args.migrate:
            from scripts.gunpla_ops import backup_and_freeze, container, install_timer, account_fingerprints
            for env, project in PROJECTS:
                stage('stop_writes_' + project, compose(env, project) + ['stop', 'api'] + ([] if project.endswith('demo') else ['worker', 'scheduler', 'cache-warmer']))
            frozen = backup_and_freeze(ROOT, args.image, args.import_gunpla)
            accounts_before = account_fingerprints(ROOT, args.image)
            emit('migration_backup_finished', directory=str(frozen.parent))
            for env, project in PROJECTS:
                stage('migrate_' + project, container(ROOT, env, args.image, ['-m', 'backend.app.worker', 'init-db']))
            stage('import_gunpla', container(ROOT, '.env', args.image, ['-m', 'scripts.sync_gunpla', '--import-file', '/app/gunpla-import.json'], mounts=['-v', str(frozen) + ':/app/gunpla-import.json:ro']))
            stage('warm_gunpla_first_screen', container(ROOT, '.env', args.image, ['-m', 'scripts.sync_gunpla', '--warm-start']))
            if accounts_before != account_fingerprints(ROOT, args.image):
                raise RuntimeError('existing project accounts changed during migration')
            emit('migration_accounts_preserved', fingerprints=accounts_before)
        for env, _ in PROJECTS:
            path = ROOT / env
            path.write_text('\n'.join('APP_IMAGE=' + args.image if line.startswith('APP_IMAGE=') else line for line in old[env].splitlines()) + '\n')
            path.chmod(0o600)
        emit('deployment_configuration_updated', files=['.env', '.env.demo'], keys=['APP_IMAGE'])
        ready = start_services('publish')
        stage('start_cache_warmer', compose('.env', 'dual-catalog') + ['up', '-d', 'cache-warmer'])
        if before != plugins():
            raise RuntimeError('unrelated plugin container changed')
        if args.migrate:
            install_timer(ROOT)
        if private_mode:
            set_gate('open')
            emit('private_gate_opened')
        emit('deployment_finished', health=ready, plugins_unchanged=True, database_migration=args.migrate, data_import=args.migrate)
        report = {'status': 'pass', 'image': args.image, 'operation_id': context['operation_id'], 'health': ready, 'plugins_unchanged': True, 'database_migration': args.migrate, 'data_import': args.migrate}
        (ROOT / 'data/artifacts/acceptance/logging-deployment.json').write_text(json.dumps(report, indent=2))
        print(json.dumps(report), flush=True)
    except Exception as error:
        emit('deployment_failed', error_type=type(error).__name__)
        if args.migrate:
            from scripts.prepare_auth import set_gate
            set_gate('closed')
            emit('migration_recovery_required', automatic_legacy_rollback=False)
            raise
        for env, _ in PROJECTS:
            path = ROOT / env
            path.write_text(old[env])
            path.chmod(0o600)
        emit('rollback_started', restore_images=previous)
        try:
            ready = start_services('rollback')
            stage('rollback_cache_warmer', compose('.env', 'dual-catalog') + ['up', '-d', 'cache-warmer'])
            emit('rollback_finished', health=ready, plugins_unchanged=before == plugins())
        except Exception as rollback_error:
            emit('rollback_failed', error_type=type(rollback_error).__name__)
            raise
        raise


if __name__ == '__main__':
    main()
