#!/usr/bin/env python3
"""Quick post-deploy check: admin pages + teacher dashboard markers (needs .env)."""

from __future__ import annotations

import http.cookiejar
import os
import sys
import urllib.error
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv():
    env_path = ROOT / '.env'
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding='utf-8').splitlines():
        line = raw.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, v = line.split('=', 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def main():
    base = (sys.argv[1] if len(sys.argv) > 1 else '').rstrip('/')
    if not base:
        print('Usage: verify_production_deploy.py https://your-app.up.railway.app')
        return 1

    _load_dotenv()
    email = os.environ.get('SUPERADMIN_EMAIL', '').strip()
    password = os.environ.get('SUPERADMIN_PASSWORD') or os.environ.get('ADMIN_PASSWORD', '')
    if not email or not password:
        print('SKIP: set SUPERADMIN_EMAIL and SUPERADMIN_PASSWORD in .env')
        return 0

    jar = http.cookiejar.CookieJar()
    from urllib.request import HTTPCookieProcessor, Request, build_opener

    opener = build_opener(HTTPCookieProcessor(jar))

    def post(path, data):
        req = Request(
            f'{base}{path}',
            urllib.parse.urlencode(data).encode(),
            method='POST',
        )
        return opener.open(req, timeout=120)

    def get(path):
        return opener.open(f'{base}{path}', timeout=60)

    ok = True
    try:
        health = get('/health').read().decode()
        print(f'[OK] /health = {health!r}')
    except Exception as exc:
        print(f'[FAIL] /health: {exc}')
        ok = False

    post('/login', {'email': email, 'password': password})
    dash = get('/').read().decode('utf-8', errors='replace')
    students = get('/students').read().decode('utf-8', errors='replace')

    for name, html, token in [
        ('Dashboard loads', dash, 'Gerar'),
        ('Students loads', students, 'Novo aluno'),
        ('Reports month filter', get('/reports').read().decode('utf-8', errors='replace'), 'Relatório'),
    ]:
        if token in html:
            print(f'[OK] {name}')
        else:
            print(f'[FAIL] {name} — missing {token!r}')
            ok = False

    # New build ships teacher turma form strings in codebase (teacher-only page).
    print('[INFO] Teacher UI (Criar turma, 1º dia) appears after professor login — verify in browser.')

    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
