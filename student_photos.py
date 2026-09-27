"""Student photos for the roster and the printed report.

Rows are keyed by ``student_snapshot_id(turma, name)`` — the same pseudonym the
snapshot store uses — so this store never holds a student's name. Moving a
student to another turma or renaming them changes the key; call
``move_photo`` alongside the roster change so the photo follows.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from report_periods import student_snapshot_id
from teacher_profiles import encode_photo  # same size limit and JPG/PNG/WebP check

logger = logging.getLogger(__name__)

_ALLOWED_MIME = ('image/jpeg', 'image/png', 'image/webp')

__all__ = [
    'encode_photo', 'find_photo', 'load_photos', 'move_photo', 'photo_data_url',
    'photo_key', 'remove_photo', 'save_photos', 'set_photo',
]


def photo_key(turma, student_name):
    return student_snapshot_id(turma, student_name)


def normalize_photo(row):
    if not isinstance(row, dict):
        return None
    key = (row.get('student_id') or '').strip()
    mime = (row.get('photo_mime') or '').strip()
    data = (row.get('photo_base64') or '').strip()
    if not key or not data or mime not in _ALLOWED_MIME:
        return None
    return {
        'student_id': key,
        'photo_mime': mime,
        'photo_base64': data,
        'updated_at': (row.get('updated_at') or '').strip(),
    }


def load_photos(path):
    if not path or not Path(path).exists():
        return []
    try:
        raw = json.loads(Path(path).read_text(encoding='utf-8'))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning('Could not read student photos %s: %s', path, exc)
        return []
    if not isinstance(raw, list):
        return []
    return [row for row in (normalize_photo(r) for r in raw) if row]


def save_photos(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    clean = [row for row in (normalize_photo(r) for r in rows or []) if row]
    payload = json.dumps(clean, ensure_ascii=False)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix='.student_photos_', suffix='.tmp')
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


def find_photo(rows, turma, student_name):
    key = photo_key(turma, student_name)
    for row in rows or []:
        photo = normalize_photo(row)
        if photo and photo['student_id'] == key:
            return photo
    return None


def set_photo(rows, turma, student_name, mime, data_b64):
    """Return rows with this student's photo replaced."""
    key = photo_key(turma, student_name)
    out = [r for r in rows or [] if (r.get('student_id') or '') != key]
    out.append({
        'student_id': key,
        'photo_mime': mime,
        'photo_base64': data_b64,
        'updated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
    })
    return out


def remove_photo(rows, turma, student_name):
    """Return (rows without this student's photo, whether one was removed)."""
    key = photo_key(turma, student_name)
    out = [r for r in rows or [] if (r.get('student_id') or '') != key]
    return out, len(out) != len(rows or [])


def move_photo(rows, old_turma, old_name, new_turma, new_name):
    """Re-key a photo after a rename or turma move. Returns (rows, moved)."""
    old_key = photo_key(old_turma, old_name)
    new_key = photo_key(new_turma, new_name)
    if old_key == new_key:
        return list(rows or []), False
    moved = False
    out = []
    for row in rows or []:
        key = row.get('student_id') or ''
        if key == new_key:
            continue  # a stale photo under the new identity loses to the moved one
        if key == old_key:
            row = {**row, 'student_id': new_key}
            moved = True
        out.append(row)
    if not moved:
        # Nothing to carry over: keep whatever the new identity already had.
        return list(rows or []), False
    return out, True


def photo_data_url(photo):
    photo = normalize_photo(photo) if photo else None
    if not photo:
        return ''
    return f"data:{photo['photo_mime']};base64,{photo['photo_base64']}"
