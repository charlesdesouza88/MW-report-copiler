#!/usr/bin/env python3
"""Back up production data reachable over HTTP before a deploy.

Pulls the superadmin-visible students.csv, lessons.csv, and the full report
archive from a running Mister Wiz instance into a timestamped folder, and
records the storage mode reported by /health/db.

Usage:
    MW_URL=https://your-app.up.railway.app \
    MW_EMAIL=admin@example.com \
    MW_PASSWORD='...' \
    python scripts/backup_prod.py [--out DIR]

Credentials come from the environment (MW_EMAIL/MW_PASSWORD, falling back to
SUPERADMIN_EMAIL/SUPERADMIN_PASSWORD) and are never written to disk.

IMPORTANT — this covers only what the app exposes over HTTP:
  - students.csv, lessons.csv (superadmin view = all rows)
  - generated report HTML (mister_wiz_reports.zip)
It does NOT cover:
  - the Postgres database as a whole (use `railway run pg_dump`)
  - student_snapshots.json (trend history) and teacher_classes.json, which are
    file-only with no download route (copy them off the Railway volume).
See the printed summary for the exact follow-up commands.
"""

import argparse
import http.cookiejar
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path


def _csrf_from_html(html):
    match = re.search(r'name="csrf_token"\s+value="([^"]+)"', html)
    return match.group(1) if match else ''


def _opener():
    jar = http.cookiejar.CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def _get(opener, url):
    with opener.open(url, timeout=60) as resp:
        return resp.status, resp.read(), dict(resp.headers)


def _login(opener, base, email, password):
    _, body, _ = _get(opener, f'{base}/login')
    token = _csrf_from_html(body.decode('utf-8', errors='replace'))
    data = urllib.parse.urlencode({
        'email': email, 'password': password, 'csrf_token': token,
    }).encode()
    req = urllib.request.Request(f'{base}/login', data=data, method='POST')
    try:
        resp = opener.open(req, timeout=60)
    except urllib.error.HTTPError as exc:
        resp = exc
    code = getattr(resp, 'status', getattr(resp, 'code', 0))
    if code not in (200, 302):
        raise SystemExit(f'Login failed (HTTP {code}). Check MW_EMAIL/MW_PASSWORD and MW_URL.')


def _save(opener, base, path, dest, label):
    try:
        status, body, _ = _get(opener, f'{base}{path}')
    except urllib.error.HTTPError as exc:
        print(f'  ! {label}: HTTP {exc.code} — skipped')
        return None
    dest.write_bytes(body)
    print(f'  ✓ {label}: {len(body):,} bytes → {dest.name}')
    return len(body)


def main():
    parser = argparse.ArgumentParser(description='Back up Mister Wiz prod data over HTTP')
    parser.add_argument('--url', default=os.environ.get('MW_URL', '').rstrip('/'),
                        help='Base URL of the running app (or set MW_URL)')
    parser.add_argument('--out', type=Path, default=Path('backups'),
                        help='Backup root directory (default: ./backups)')
    args = parser.parse_args()

    base = args.url.rstrip('/')
    email = (os.environ.get('MW_EMAIL') or os.environ.get('SUPERADMIN_EMAIL') or '').strip()
    password = os.environ.get('MW_PASSWORD') or os.environ.get('SUPERADMIN_PASSWORD') or ''
    if not base:
        raise SystemExit('Set --url or MW_URL to the production URL.')
    if not email or not password:
        raise SystemExit('Set MW_EMAIL/MW_PASSWORD (or SUPERADMIN_EMAIL/SUPERADMIN_PASSWORD).')

    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    dest_dir = args.out / stamp
    dest_dir.mkdir(parents=True, exist_ok=True)
    print(f'Backing up {base} → {dest_dir}/')

    opener = _opener()

    # Storage mode (no auth) — records whether Postgres is the source of truth.
    db_status = {}
    try:
        _, body, _ = _get(opener, f'{base}/health/db')
        db_status = json.loads(body.decode('utf-8', errors='replace'))
        print(f'  · storage: {db_status.get("mode", "unknown")} '
              f'(connected={db_status.get("connected")})')
    except Exception as exc:
        print(f'  · storage: could not read /health/db ({exc})')

    _login(opener, base, email, password)

    manifest = {
        'timestamp': stamp,
        'source_url': base,
        'db_status': db_status,
        'files': {},
    }
    for path, fname, label in (
        ('/upload/download/students', 'students.csv', 'students'),
        ('/upload/download/lessons', 'lessons.csv', 'lessons'),
        ('/reports/download-all', 'mister_wiz_reports.zip', 'reports'),
    ):
        size = _save(opener, base, path, dest_dir / fname, label)
        manifest['files'][fname] = size

    (dest_dir / 'manifest.json').write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')

    print(f'\nHTTP-reachable backup written to {dest_dir}/')
    print('NOT covered by this backup — do these on the Railway side:')
    if db_status.get('mode') == 'postgresql':
        print('  • Full DB dump:  railway run pg_dump "$DATABASE_URL" > '
              f'{dest_dir}/prod.sql')
    print('  • File-only stores (trend history + class map), from a Railway shell:')
    print('      railway run sh -c \'cat $DATA_DIR/student_snapshots.json\' > '
          f'{dest_dir}/student_snapshots.json')
    print('      railway run sh -c \'cat $DATA_DIR/teacher_classes.json\' > '
          f'{dest_dir}/teacher_classes.json')


if __name__ == '__main__':
    main()
