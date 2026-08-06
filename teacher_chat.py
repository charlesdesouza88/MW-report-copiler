"""Shared teacher/admin chat room with optional bug reports."""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from auth import ROLE_ADMIN, ROLE_SUPERADMIN, ROLE_TEACHER, has_full_data_access

logger = logging.getLogger(__name__)

ROOM_ID = 'teachers'
ROOM_TITLE = 'Chat'

KIND_CHAT = 'chat'
KIND_BUG = 'bug'
BUG_OPEN = 'open'
BUG_RESOLVED = 'resolved'

ALLOWED_ROLES = frozenset({ROLE_TEACHER, ROLE_ADMIN, ROLE_SUPERADMIN})
_MAX_BODY_LEN = 2000
_WS_RE = re.compile(r'\s+')


def can_access_chat(user):
    return bool(user and user.get('role') in ALLOWED_ROLES and user.get('active', True))


def can_resolve_bugs(user):
    return bool(user and has_full_data_access(user.get('role', '')))


def author_display_name(user):
    if not user:
        return 'Usuário'
    name = (user.get('teacher_name') or '').strip()
    if name:
        return name
    email = (user.get('email') or '').strip()
    if email and '@' in email:
        return email.split('@', 1)[0]
    return email or 'Usuário'


def _utc_now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def _new_id():
    return uuid.uuid4().hex


def normalize_message(row):
    if not isinstance(row, dict):
        return None
    msg_id = (row.get('id') or '').strip()
    body = (row.get('body') or '').strip()
    if not msg_id or not body:
        return None
    kind = (row.get('kind') or KIND_CHAT).strip()
    if kind not in (KIND_CHAT, KIND_BUG):
        kind = KIND_CHAT
    bug_status = (row.get('bug_status') or '').strip()
    if kind == KIND_BUG:
        if bug_status not in (BUG_OPEN, BUG_RESOLVED):
            bug_status = BUG_OPEN
    else:
        bug_status = ''
    parent_id = (row.get('parent_id') or '').strip()
    created = (row.get('created_at') or '').strip() or _utc_now_iso()
    try:
        author_user_id = int(row.get('author_user_id') or 0)
    except (TypeError, ValueError):
        author_user_id = 0
    return {
        'id': msg_id,
        'room_id': (row.get('room_id') or ROOM_ID).strip() or ROOM_ID,
        'author_user_id': author_user_id,
        'author_name': (row.get('author_name') or '').strip() or 'Usuário',
        'author_role': (row.get('author_role') or '').strip(),
        'body': body[:_MAX_BODY_LEN],
        'created_at': created,
        'parent_id': parent_id,
        'kind': kind,
        'bug_status': bug_status,
    }


def load_messages(path):
    if not path or not Path(path).exists():
        return []
    try:
        raw = json.loads(Path(path).read_text(encoding='utf-8'))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning('Could not read chat messages %s: %s', path, exc)
        return []
    if not isinstance(raw, list):
        return []
    out = []
    for row in raw:
        msg = normalize_message(row)
        if msg:
            out.append(msg)
    return out


def save_messages(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    clean = []
    for row in rows or []:
        msg = normalize_message(row)
        if msg:
            clean.append(msg)
    payload = json.dumps(clean, ensure_ascii=False, indent=2)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix='.teacher_chat_', suffix='.tmp',
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


def build_message(user, body, *, kind=KIND_CHAT, parent_id=''):
    text = _WS_RE.sub(' ', (body or '').strip())
    if not text:
        return None, 'Escreva uma mensagem.'
    if len(text) > _MAX_BODY_LEN:
        return None, f'Mensagem muito longa (máx. {_MAX_BODY_LEN} caracteres).'
    if not can_access_chat(user):
        return None, 'Sem permissão para usar o chat.'

    kind = KIND_BUG if kind == KIND_BUG else KIND_CHAT
    parent = (parent_id or '').strip()
    msg = {
        'id': _new_id(),
        'room_id': ROOM_ID,
        'author_user_id': int(user.get('id') or 0),
        'author_name': author_display_name(user),
        'author_role': (user.get('role') or '').strip(),
        'body': text,
        'created_at': _utc_now_iso(),
        'parent_id': parent,
        'kind': kind,
        'bug_status': BUG_OPEN if kind == KIND_BUG else '',
    }
    return msg, None


def append_message(rows, user, body, *, kind=KIND_CHAT, parent_id=''):
    """Append a new message onto rows in place. Returns (message, error)."""
    if rows is None:
        raise ValueError('rows list is required')
    parent = (parent_id or '').strip()
    if parent and not find_message(rows, parent):
        return None, 'Mensagem original não encontrada.'
    msg, err = build_message(user, body, kind=kind, parent_id=parent)
    if err:
        return None, err
    rows.append(msg)
    return msg, None


def find_message(rows, message_id):
    want = (message_id or '').strip()
    if not want:
        return None
    for row in rows or []:
        msg = normalize_message(row)
        if msg and msg['id'] == want:
            return msg
    return None


def resolve_bug(rows, message_id, user):
    """Mark a bug message resolved in place. Returns (updated_message, error)."""
    if not can_resolve_bugs(user):
        return None, 'Apenas administradores podem resolver bugs.'
    want = (message_id or '').strip()
    if not want:
        return None, 'Mensagem não informada.'
    if rows is None:
        raise ValueError('rows list is required')
    for i, row in enumerate(rows):
        msg = normalize_message(row)
        if not msg or msg['id'] != want:
            continue
        if msg['kind'] != KIND_BUG:
            return None, 'Só é possível resolver mensagens do tipo bug.'
        if msg['bug_status'] == BUG_RESOLVED:
            rows[i] = msg
            return msg, None
        msg['bug_status'] = BUG_RESOLVED
        rows[i] = msg
        return msg, None
    return None, 'Bug não encontrado.'


def messages_after(rows, after_id='', after_created_at=''):
    """Return messages strictly after a cursor (for polling)."""
    indexed = []
    for i, row in enumerate(rows or []):
        msg = normalize_message(row)
        if msg:
            indexed.append((i, msg))
    # Stable chronological order: created_at, then original insert position.
    indexed.sort(key=lambda item: (item[1]['created_at'], item[0]))
    messages = [msg for _i, msg in indexed]
    after_id = (after_id or '').strip()
    after_created = (after_created_at or '').strip()
    if after_id:
        for i, msg in enumerate(messages):
            if msg['id'] == after_id:
                return messages[i + 1:]
        return []
    if after_created:
        return [m for m in messages if m['created_at'] > after_created]
    return messages


def thread_tree(rows):
    """Group messages: roots chronologically, each with nested replies."""
    messages = [normalize_message(r) for r in (rows or [])]
    messages = [m for m in messages if m]
    by_id = {m['id']: m for m in messages}
    roots = []
    children = {}
    for msg in messages:
        parent = msg.get('parent_id') or ''
        if parent and parent in by_id:
            children.setdefault(parent, []).append(msg)
        else:
            roots.append(msg)
    for root in roots:
        root['replies'] = children.get(root['id'], [])
    return roots


def open_bug_count(rows):
    total = 0
    for row in rows or []:
        msg = normalize_message(row)
        if msg and msg['kind'] == KIND_BUG and msg['bug_status'] == BUG_OPEN:
            total += 1
    return total
