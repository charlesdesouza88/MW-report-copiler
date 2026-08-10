"""Append-only login history for platform users."""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlencode
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

_HISTORY_CAP = 100
_SAO_PAULO = ZoneInfo('America/Sao_Paulo')
_DIGITS_RE = re.compile(r'\D+')


def _utc_now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def _new_id():
    return uuid.uuid4().hex


def normalize_event(row):
    if not isinstance(row, dict):
        return None
    event_id = (row.get('id') or '').strip()
    if not event_id:
        return None
    try:
        user_id = int(row.get('user_id') or 0)
    except (TypeError, ValueError):
        user_id = 0
    if user_id <= 0:
        return None
    logged_at = (row.get('logged_at') or '').strip() or _utc_now_iso()
    return {
        'id': event_id,
        'user_id': user_id,
        'email': (row.get('email') or '').strip(),
        'role': (row.get('role') or '').strip(),
        'teacher_name': (row.get('teacher_name') or '').strip(),
        'logged_at': logged_at,
    }


def load_events(path):
    if not path or not Path(path).exists():
        return []
    try:
        raw = json.loads(Path(path).read_text(encoding='utf-8'))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning('Could not read login events %s: %s', path, exc)
        return []
    if not isinstance(raw, list):
        return []
    out = []
    for row in raw:
        event = normalize_event(row)
        if event:
            out.append(event)
    return out


def save_events(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    clean = []
    for row in rows or []:
        event = normalize_event(row)
        if event:
            clean.append(event)
    payload = json.dumps(clean, ensure_ascii=False, indent=2)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix='.login_events_', suffix='.tmp',
    )
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def build_event(user):
    if not user:
        return None
    try:
        user_id = int(user.get('id') or 0)
    except (TypeError, ValueError):
        user_id = 0
    if user_id <= 0:
        return None
    return {
        'id': _new_id(),
        'user_id': user_id,
        'email': (user.get('email') or '').strip(),
        'role': (user.get('role') or '').strip(),
        'teacher_name': (user.get('teacher_name') or '').strip(),
        'logged_at': _utc_now_iso(),
    }


def append_login(rows, user):
    """Append a login event onto rows in place. Returns the event or None."""
    if rows is None:
        raise ValueError('rows list is required')
    event = build_event(user)
    if not event:
        return None
    rows.append(event)
    return event


def events_newest_first(rows, *, limit=_HISTORY_CAP):
    indexed = []
    for i, row in enumerate(rows or []):
        event = normalize_event(row)
        if event:
            indexed.append((i, event))
    indexed.sort(key=lambda item: (item[1]['logged_at'], item[0]), reverse=True)
    events = [event for _i, event in indexed]
    if limit is not None:
        return events[:limit]
    return events


def events_for_user(rows, user_id, *, limit=_HISTORY_CAP):
    try:
        want = int(user_id)
    except (TypeError, ValueError):
        return []
    matched = [
        e for e in events_newest_first(rows, limit=None)
        if e['user_id'] == want
    ]
    if limit is not None:
        return matched[:limit]
    return matched


def last_login_by_user_id(rows):
    """Map user_id -> newest login event."""
    latest = {}
    for event in events_newest_first(rows, limit=None):
        uid = event['user_id']
        if uid not in latest:
            latest[uid] = event
    return latest


def format_logged_at(logged_at, *, empty='Nunca'):
    """Format UTC ISO timestamp for Brazil display."""
    raw = (logged_at or '').strip()
    if not raw:
        return empty
    text = raw.replace('Z', '+00:00')
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return raw
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    local = dt.astimezone(_SAO_PAULO)
    return local.strftime('%d/%m/%Y %H:%M')


def whatsapp_digits(raw_phone):
    """Normalize a WhatsApp number to international digits (BR default 55)."""
    digits = _DIGITS_RE.sub('', raw_phone or '')
    if not digits:
        return ''
    if digits.startswith('00'):
        digits = digits[2:]
    if len(digits) in (10, 11) and not digits.startswith('55'):
        digits = '55' + digits
    return digits


def mailto_href(email, *, subject='', body=''):
    email = (email or '').strip()
    if not email or '@' not in email:
        return ''
    params = {}
    if subject:
        params['subject'] = subject
    if body:
        params['body'] = body
    query = urlencode(params, quote_via=quote) if params else ''
    return f'mailto:{email}?{query}' if query else f'mailto:{email}'


def whatsapp_href(phone, *, text=''):
    digits = whatsapp_digits(phone)
    if not digits:
        return ''
    if text:
        return f'https://wa.me/{digits}?{urlencode({"text": text}, quote_via=quote)}'
    return f'https://wa.me/{digits}'


def contact_email_for_user(user, profile=None):
    profile = profile or {}
    contact = (profile.get('contact_email') or '').strip()
    if contact:
        return contact
    return (user.get('email') or '').strip()
