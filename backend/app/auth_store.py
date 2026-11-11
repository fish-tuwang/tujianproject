"""Persistent credentials and one current session per operator-created account."""
from contextlib import contextmanager
import hashlib
import hmac
import os
from pathlib import Path
import re
import secrets
import sqlite3
import threading
import time

PASSWORD_WORK = threading.BoundedSemaphore(2)

class AuthError(Exception):
    def __init__(self, code, message, status=401, retry_after=None):
        super().__init__(message)
        self.code, self.message, self.status, self.retry_after = code, message, status, retry_after


def username_key(value):
    value = value.strip().casefold()
    if not re.fullmatch(r'[\w.@-]{2,64}', value):
        raise AuthError('INVALID_USERNAME', '用户名须为2–64个字母、数字或 . _ @ -', 400)
    return value


def hash_password(password):
    if not 15 <= len(password) <= 128:
        raise AuthError('INVALID_PASSWORD', '新密码长度须为15–128个字符', 400)
    try:
        raw = password.encode('utf-8')
    except UnicodeError:
        raise AuthError('INVALID_PASSWORD', '密码包含无效字符', 400) from None
    salt = secrets.token_bytes(16)
    with PASSWORD_WORK:
        digest = hashlib.scrypt(raw, salt=salt, n=32768, r=8, p=3, maxmem=67108864)
    return 'scrypt$32768$8$3$' + salt.hex() + '$' + digest.hex()


def verify_password(password, encoded):
    try:
        algorithm, n, r, p, salt, expected = encoded.split('$')
        if (algorithm, n, r, p) != ('scrypt', '32768', '8', '3'):
            return False
        salt, expected = bytes.fromhex(salt), bytes.fromhex(expected)
        if len(salt) != 16 or len(expected) != 64 or len(password) > 128:
            return False
        with PASSWORD_WORK:
            actual = hashlib.scrypt(password.encode('utf-8'), salt=salt, n=32768, r=8, p=3, maxmem=67108864)
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError, UnicodeError, AttributeError):
        return False


def session_digest(token):
    if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', token):
        return None
    return hashlib.sha256(token.encode('ascii')).hexdigest()


class AuthStore:
    def __init__(self, path, session_seconds=43200, clock=time.time):
        self.path, self.session_seconds, self.clock = Path(path), session_seconds, clock
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path.parent.chmod(0o700)
        descriptor = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(descriptor)
        self.path.chmod(0o600)
        with self.connection() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS accounts (
                    username TEXT PRIMARY KEY, password_hash TEXT NOT NULL,
                    active_session_hash TEXT UNIQUE, session_expires_at INTEGER,
                    must_change_password INTEGER NOT NULL DEFAULT 1,
                    disabled INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS login_limits (
                    bucket TEXT PRIMARY KEY, attempts INTEGER NOT NULL, expires_at INTEGER NOT NULL
                );
            ''')
        self.dummy_hash = hash_password('unavailable-account-verification-only')

    @contextmanager
    def connection(self, write=False):
        db = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            if write:
                db.execute('BEGIN IMMEDIATE')
            yield db
            if write:
                db.commit()
        except BaseException:
            if write:
                db.rollback()
            raise
        finally:
            db.close()

    def create_user(self, username, password, must_change=True):
        username, encoded = username_key(username), hash_password(password)
        try:
            with self.connection(True) as db:
                db.execute('INSERT INTO accounts(username,password_hash,must_change_password,created_at) VALUES(?,?,?,?)',
                           (username, encoded, int(must_change), int(self.clock())))
        except sqlite3.IntegrityError:
            raise AuthError('ACCOUNT_EXISTS', '账号已存在', 409) from None
        return username

    def list_users(self):
        with self.connection() as db:
            return [dict(row) for row in db.execute('SELECT username,disabled,must_change_password,created_at FROM accounts ORDER BY username')]

    def _buckets(self, username, client_ip):
        return [('ip:' + client_ip[:128], 5, 300), ('user:' + username, 20, 900)]

    def _reserve_attempt(self, username, client_ip):
        now = int(self.clock())
        with self.connection(True) as db:
            db.execute('DELETE FROM login_limits WHERE expires_at<=?', (now,))
            for bucket, limit, duration in self._buckets(username, client_ip):
                row = db.execute('SELECT attempts,expires_at FROM login_limits WHERE bucket=?', (bucket,)).fetchone()
                if row and row['attempts'] >= limit:
                    raise AuthError('LOGIN_RATE_LIMITED', '登录尝试过多，请稍后再试', 429, max(1, row['expires_at'] - now))
                db.execute('INSERT INTO login_limits(bucket,attempts,expires_at) VALUES(?,1,?) ON CONFLICT(bucket) DO UPDATE SET attempts=attempts+1',
                           (bucket, now + duration))

    def _profile(self, row):
        return {'auth_enabled': True, 'username': row['username'],
                'must_change_password': bool(row['must_change_password']), 'expires_at': row['session_expires_at']}

    def login(self, username, password, client_ip):
        username = username.strip().casefold()
        self._reserve_attempt(username, client_ip)
        with self.connection() as db:
            row = db.execute('SELECT * FROM accounts WHERE username=?', (username,)).fetchone()
        encoded = row['password_hash'] if row and not row['disabled'] else self.dummy_hash
        verified = verify_password(password, encoded)
        if not verified or not row or row['disabled']:
            raise AuthError('INVALID_CREDENTIALS', '账号或密码错误')
        token = secrets.token_urlsafe(32)
        with self.connection(True) as db:
            current = db.execute('SELECT * FROM accounts WHERE username=?', (username,)).fetchone()
            if not current or current['disabled'] or current['password_hash'] != encoded:
                raise AuthError('INVALID_CREDENTIALS', '账号或密码错误')
            expires = int(self.clock()) + self.session_seconds
            db.execute('UPDATE accounts SET active_session_hash=?,session_expires_at=? WHERE username=?', (session_digest(token), expires, username))
            for bucket, _, _ in self._buckets(username, client_ip):
                db.execute('DELETE FROM login_limits WHERE bucket=?', (bucket,))
            profile = self._profile(current)
            profile['expires_at'] = expires
        return token, profile

    def authenticate(self, token):
        digest = session_digest(token)
        if not digest:
            return None
        with self.connection() as db:
            row = db.execute('SELECT * FROM accounts WHERE active_session_hash=? AND disabled=0 AND session_expires_at>?', (digest, int(self.clock()))).fetchone()
        return self._profile(row) if row else None

    def logout(self, token):
        digest = session_digest(token)
        if digest:
            with self.connection(True) as db:
                db.execute('UPDATE accounts SET active_session_hash=NULL,session_expires_at=NULL WHERE active_session_hash=?', (digest,))

    def change_password(self, token, current_password, new_password):
        digest = session_digest(token)
        with self.connection() as db:
            row = db.execute('SELECT * FROM accounts WHERE active_session_hash=? AND disabled=0 AND session_expires_at>?', (digest, int(self.clock()))).fetchone()
        if not row:
            raise AuthError('AUTH_REQUIRED', '登录已失效，请重新登录')
        if not verify_password(current_password, row['password_hash']):
            raise AuthError('INVALID_CURRENT_PASSWORD', '当前密码错误', 403)
        if current_password == new_password:
            raise AuthError('PASSWORD_UNCHANGED', '请设置与临时或当前密码不同的新密码', 400)
        encoded, replacement = hash_password(new_password), secrets.token_urlsafe(32)
        expires = int(self.clock()) + self.session_seconds
        with self.connection(True) as db:
            result = db.execute('UPDATE accounts SET password_hash=?,active_session_hash=?,session_expires_at=?,must_change_password=0 WHERE username=? AND active_session_hash=? AND password_hash=? AND disabled=0 AND session_expires_at>?',
                                (encoded, session_digest(replacement), expires, row['username'], digest, row['password_hash'], int(self.clock())))
            if result.rowcount != 1:
                raise AuthError('AUTH_REQUIRED', '登录已失效，请重新登录')
        return replacement, {'auth_enabled': True, 'username': row['username'], 'must_change_password': False, 'expires_at': expires}

    def reset_password(self, username, password):
        username, encoded = username_key(username), hash_password(password)
        with self.connection(True) as db:
            changed = db.execute('UPDATE accounts SET password_hash=?,active_session_hash=NULL,session_expires_at=NULL,must_change_password=1 WHERE username=?', (encoded, username))
            if changed.rowcount != 1:
                raise AuthError('ACCOUNT_NOT_FOUND', '账号不存在', 404)
            db.execute('DELETE FROM login_limits')
        return username

    def disable_user(self, username):
        with self.connection(True) as db:
            result = db.execute('UPDATE accounts SET disabled=1,active_session_hash=NULL,session_expires_at=NULL WHERE username=?', (username_key(username),))
            if result.rowcount != 1:
                raise AuthError('ACCOUNT_NOT_FOUND', '账号不存在', 404)
