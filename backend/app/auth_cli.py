"""Operator-only account provisioning; never accepts a password in argv."""
import argparse
import getpass
import json
import os
from pathlib import Path
import secrets
import sys

from .audit import audit, configure_audit
from .auth_store import AuthError, AuthStore
from .config import ROOT, Settings


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ['create-user', 'reset-password']:
        command = commands.add_parser(name)
        command.add_argument('username')
        command.add_argument('--generate', action='store_true')
        command.add_argument('--output-file')
    commands.add_parser('list-users')
    commands.add_parser('disable-user').add_argument('username')
    args = parser.parse_args(argv)
    settings = Settings()
    store = AuthStore(settings.auth_path, settings.auth_session_seconds)
    directory = Path(settings.artifact_dir)
    configure_audit((directory if directory.is_absolute() else ROOT / directory).parent / 'logs', channels={'auth'})
    if args.command == 'list-users':
        print(json.dumps({'users': store.list_users()}, ensure_ascii=False))
        return 0
    if args.command == 'disable-user':
        store.disable_user(args.username)
        audit('account_disabled', channel='auth', username=args.username, actor=getpass.getuser())
        print(json.dumps({'status': 'pass', 'username': args.username}))
        return 0
    if args.generate and not args.output_file:
        parser.error('--generate requires --output-file; passwords are never printed')
    output, descriptor, created_output, completed_output = None, None, False, False
    try:
        if args.generate:
            output = Path(args.output_file)
            output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            descriptor = os.open(output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            created_output = True
            password = secrets.token_urlsafe(18)
        else:
            password = getpass.getpass('New password: ')
            if password != getpass.getpass('Confirm password: '):
                raise AuthError('PASSWORD_MISMATCH', '两次输入的密码不一致', 400)
        operation = store.create_user if args.command == 'create-user' else store.reset_password
        username = operation(args.username, password)
        if descriptor is not None:
            with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
                descriptor = None
                json.dump({'username': username, 'password': password, 'must_change_password': True}, stream, ensure_ascii=False)
                stream.write('\n')
            completed_output = True
        audit('account_created' if args.command == 'create-user' else 'account_password_reset', channel='auth', username=username, actor=getpass.getuser())
        print(json.dumps({'status': 'pass', 'username': username, 'credentials_file': str(output) if output else None}))
        return 0
    except BaseException:
        if descriptor is not None:
            os.close(descriptor)
        if created_output and not completed_output:
            output.unlink(missing_ok=True)
        raise


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (AuthError, OSError) as error:
        print(json.dumps({'status': 'fail', 'code': getattr(error, 'code', type(error).__name__), 'message': str(error) if isinstance(error, AuthError) else '请检查私有输出文件和目录权限'}), file=sys.stderr)
        sys.exit(1)
