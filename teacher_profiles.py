"""Teacher/admin public profile: bio, contacts, and photo."""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from auth import has_full_data_access, normalize_email

logger = logging.getLogger(__name__)

_MAX_BIO = 1000
_MAX_FIELD = 120
_MAX_PHOTO_BYTES = 700_000  # ~700KB raw upload
_WS_RE = re.compile(r'\s+')

_PHOTO_MAGIC = (
    (b'\xff\xd8\xff', 'image/jpeg', 'jpg'),
    (b'\x89PNG\r\n\x1a\n', 'image/png', 'png'),
    (b'RIFF', 'image/webp', 'webp'),  # need WEBP at offset 8
)


def empty_profile(user_id):
    return {
        'user_id': int(user_id),
        'bio': '',
        'phone': '',
        'whatsapp': '',
        'contact_email': '',
        'specialty': '',
        'photo_mime': '',
        'photo_base64': '',
        'updated_at': '',
    }


def normalize_profile(row, user_id=None):
    if not isinstance(row, dict):
        return None
    try:
        uid = int(row.get('user_id') if row.get('user_id') is not None else user_id or 0)
    except (TypeError, ValueError):
        return None
    if uid <= 0:
        return None
    photo_b64 = (row.get('photo_base64') or '').strip()
    photo_mime = (row.get('photo_mime') or '').strip()
    if photo_b64 and photo_mime not in ('image/jpeg', 'image/png', 'image/webp'):
        photo_mime = 'image/jpeg'
    return {
        'user_id': uid,
        'bio': (row.get('bio') or '').strip()[:_MAX_BIO],
        'phone': (row.get('phone') or '').strip()[:_MAX_FIELD],
        'whatsapp': (row.get('whatsapp') or '').strip()[:_MAX_FIELD],
        'contact_email': normalize_email(row.get('contact_email') or '')[:_MAX_FIELD],
        'specialty': (row.get('specialty') or '').strip()[:_MAX_FIELD],
        'photo_mime': photo_mime if photo_b64 else '',
        'photo_base64': photo_b64 if photo_mime else '',
        'updated_at': (row.get('updated_at') or '').strip(),
    }


def load_profiles(path):
    if not path or not Path(path).exists():
        return []
    try:
        raw = json.loads(Path(path).read_text(encoding='utf-8'))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning('Could not read teacher profiles %s: %s', path, exc)
        return []
    if not isinstance(raw, list):
        return []
    out = []
    for row in raw:
        profile = normalize_profile(row)
        if profile:
            out.append(profile)
    return out


def save_profiles(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    clean = []
    for row in rows or []:
        profile = normalize_profile(row)
        if profile:
            clean.append(profile)
    payload = json.dumps(clean, ensure_ascii=False, indent=2)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix='.teacher_profiles_', suffix='.tmp',
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


def find_profile(rows, user_id):
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return None
    for row in rows or []:
        profile = normalize_profile(row)
        if profile and profile['user_id'] == uid:
            return profile
    return None


def get_or_empty(rows, user_id):
    found = find_profile(rows, user_id)
    if found:
        return found
    return empty_profile(user_id)


def can_edit_profile(actor, target_user_id):
    if not actor:
        return False
    try:
        target_id = int(target_user_id)
    except (TypeError, ValueError):
        return False
    if int(actor.get('id') or 0) == target_id:
        return True
    return has_full_data_access(actor.get('role', ''))


def can_view_profile(actor, target_user):
    """Logged-in staff can view active teacher/admin profiles."""
    if not actor or not target_user:
        return False
    if not target_user.get('active', True):
        return has_full_data_access(actor.get('role', ''))
    return True


def detect_image(data):
    """Return (mime, ext) or (None, None)."""
    if not data or len(data) < 12:
        return None, None
    if data.startswith(b'\xff\xd8\xff'):
        return 'image/jpeg', 'jpg'
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png', 'png'
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return 'image/webp', 'webp'
    return None, None


def encode_photo(file_bytes):
    """Validate and encode photo. Returns (mime, base64, error)."""
    if not file_bytes:
        return '', '', None
    if len(file_bytes) > _MAX_PHOTO_BYTES:
        return '', '', (
            f'Foto muito grande (máx. {_MAX_PHOTO_BYTES // 1000} KB). '
            'Comprima a imagem e tente de novo.'
        )
    mime, _ext = detect_image(file_bytes)
    if not mime:
        return '', '', 'Envie uma imagem JPG, PNG ou WebP.'
    encoded = base64.b64encode(file_bytes).decode('ascii')
    return mime, encoded, None


def photo_data_url(profile):
    profile = normalize_profile(profile) if profile else None
    if not profile or not profile.get('photo_base64') or not profile.get('photo_mime'):
        return ''
    return f"data:{profile['photo_mime']};base64,{profile['photo_base64']}"


def upsert_profile(
    rows,
    user_id,
    *,
    bio='',
    phone='',
    whatsapp='',
    contact_email='',
    specialty='',
    photo_mime=None,
    photo_base64=None,
    clear_photo=False,
):
    """Update or insert profile in place. Returns (profile, error)."""
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return None, 'Usuário inválido.'
    if rows is None:
        raise ValueError('rows list is required')

    bio_text = _WS_RE.sub(' ', (bio or '').strip())
    if len(bio_text) > _MAX_BIO:
        return None, f'Bio muito longa (máx. {_MAX_BIO} caracteres).'

    contact = normalize_email(contact_email)
    if contact_email and not contact:
        return None, 'E-mail de contato inválido.'
    if contact and '@' not in contact:
        return None, 'E-mail de contato inválido.'

    current = find_profile(rows, uid) or empty_profile(uid)
    updated = {
        'user_id': uid,
        'bio': bio_text[:_MAX_BIO],
        'phone': (phone or '').strip()[:_MAX_FIELD],
        'whatsapp': (whatsapp or '').strip()[:_MAX_FIELD],
        'contact_email': contact[:_MAX_FIELD],
        'specialty': (specialty or '').strip()[:_MAX_FIELD],
        'photo_mime': current.get('photo_mime') or '',
        'photo_base64': current.get('photo_base64') or '',
        'updated_at': datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z'),
    }

    if clear_photo:
        updated['photo_mime'] = ''
        updated['photo_base64'] = ''
    elif photo_base64 is not None and photo_mime is not None:
        if photo_base64 and photo_mime:
            updated['photo_mime'] = photo_mime
            updated['photo_base64'] = photo_base64
        elif not photo_base64:
            updated['photo_mime'] = ''
            updated['photo_base64'] = ''

    for i, row in enumerate(rows):
        existing = normalize_profile(row)
        if existing and existing['user_id'] == uid:
            rows[i] = updated
            return updated, None
    rows.append(updated)
    return updated, None
