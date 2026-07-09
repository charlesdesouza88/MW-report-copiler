"""Per-month student review scores (separate from roster profile)."""

import json
from pathlib import Path

from report_periods import previous_calendar_month, student_snapshot_id

ROSTER_FIELDS = (
    'teacher', 'turma', 'turma_display', 'nivel', 'horario', 'student_name',
)

MONTHLY_REVIEW_FIELDS = (
    'participacao', 'comportamento', 'speaking', 'listening', 'foco',
    'writing', 'reading', 'gramatica', 'trabalho_equipe', 'organizacao',
    'pontualidade', 'respeito_regras', 'faltas', 'missed_aulas', 'aula_extra',
    'feedback_participacao', 'feedback_foco', 'feedback_trabalho_equipe',
    'recomendacoes', 'observacao',
)

# Presence resets each month — never copy from a previous month's review.
PRESENCE_FIELDS = frozenset({'faltas', 'missed_aulas', 'aula_extra'})

DEFAULT_MONTHLY_VALUES = {
    'participacao': '3',
    'comportamento': '3',
    'speaking': '3',
    'listening': '3',
    'foco': '3',
    'writing': '3',
    'reading': '3',
    'gramatica': '3',
    'trabalho_equipe': '3',
    'organizacao': '3',
    'pontualidade': '3',
    'respeito_regras': '3',
    'faltas': '0',
    'missed_aulas': '',
    'aula_extra': '',
    'feedback_participacao': '',
    'feedback_foco': '',
    'feedback_trabalho_equipe': '',
    'recomendacoes': '',
    'observacao': '',
}


def review_key(turma, student_name, month_key):
    sid = student_snapshot_id(turma, student_name)
    return f'{(turma or "").strip()}|{sid}|{(month_key or "").strip()}'


def split_student_row(row):
    """Split a full student dict into roster profile and monthly review fields."""
    profile = {field: (row.get(field) or '').strip() for field in ROSTER_FIELDS}
    monthly = {field: (row.get(field) or '').strip() for field in MONTHLY_REVIEW_FIELDS}
    return profile, monthly


def extract_monthly_fields(row):
    return {field: (row.get(field) or '').strip() for field in MONTHLY_REVIEW_FIELDS}


def extract_roster_fields(row):
    return {field: (row.get(field) or '').strip() for field in ROSTER_FIELDS}


def merge_student_for_month(roster_row, store, month_key):
    """Return a full student dict for display/edit/generate for the given month."""
    turma = (roster_row.get('turma') or '').strip()
    name = (roster_row.get('student_name') or '').strip()
    merged = dict(roster_row)
    for field in MONTHLY_REVIEW_FIELDS:
        merged[field] = ''

    if not month_key or not turma or not name:
        legacy = extract_monthly_fields(roster_row)
        merged.update(legacy)
        return merged

    key = review_key(turma, name, month_key)
    if key in store:
        merged.update({k: store[key].get(k, '') for k in MONTHLY_REVIEW_FIELDS})
        return merged

    prev = previous_calendar_month(month_key)
    if prev:
        prev_key = review_key(turma, name, prev)
        if prev_key in store:
            prev_row = store[prev_key]
            for field in MONTHLY_REVIEW_FIELDS:
                if field in PRESENCE_FIELDS:
                    merged[field] = DEFAULT_MONTHLY_VALUES[field]
                else:
                    merged[field] = prev_row.get(field, '')
            return merged

    legacy = extract_monthly_fields(roster_row)
    if any(legacy.values()):
        merged.update(legacy)
    else:
        merged.update(DEFAULT_MONTHLY_VALUES)
    return merged


def merge_roster_for_month(roster_rows, store, month_key):
    return [merge_student_for_month(row, store, month_key) for row in roster_rows]


def monthly_row_from_student(student, month_key):
    turma = (student.get('turma') or '').strip()
    name = (student.get('student_name') or '').strip()
    if not month_key or not turma or not name:
        return None
    monthly = extract_monthly_fields(student)
    sid = student_snapshot_id(turma, name)
    return {
        'report_month': month_key,
        'turma': turma,
        'student_id': sid,
        'student_name': name,
        **monthly,
    }


def upsert_monthly_review(store, student, month_key):
    """Update in-memory store dict; returns the row written."""
    row = monthly_row_from_student(student, month_key)
    if not row:
        return None
    key = review_key(row['turma'], row['student_name'], month_key)
    store[key] = {k: row.get(k, '') for k in ('report_month', 'turma', 'student_id', *MONTHLY_REVIEW_FIELDS)}
    return store[key]


def store_from_rows(rows):
    out = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        month = (row.get('report_month') or '').strip()
        turma = (row.get('turma') or '').strip()
        sid = (row.get('student_id') or '').strip()
        name = (row.get('student_name') or '').strip()
        if not sid and name:
            sid = student_snapshot_id(turma, name)
        if not month or not turma or not sid:
            continue
        key = f'{turma}|{sid}|{month}'
        out[key] = {
            'report_month': month,
            'turma': turma,
            'student_id': sid,
            **{field: (row.get(field) or '').strip() for field in MONTHLY_REVIEW_FIELDS},
        }
    return out


def rows_from_store(store):
    return list(store.values())


def remove_reviews_for_student(store, turma, student_name):
    turma = (turma or '').strip()
    name = (student_name or '').strip()
    if not turma or not name or not store:
        return False
    sid = student_snapshot_id(turma, name)
    prefix = f'{turma}|{sid}|'
    keys = [key for key in list(store) if key.startswith(prefix)]
    for key in keys:
        del store[key]
    return bool(keys)


def load_monthly_reviews(path):
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding='utf-8'))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(raw, list):
        return {}
    return store_from_rows(raw)


def save_monthly_reviews(path, store):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(rows_from_store(store), ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8',
    )


def migrate_roster_scores_to_month(roster_rows, store, month_key):
    """One-time seed: copy legacy roster score fields into monthly store for month_key."""
    if not month_key:
        return False
    changed = False
    for row in roster_rows:
        turma = (row.get('turma') or '').strip()
        name = (row.get('student_name') or '').strip()
        if not turma or not name:
            continue
        key = review_key(turma, name, month_key)
        if key in store:
            continue
        legacy = extract_monthly_fields(row)
        if not any(legacy.values()):
            continue
        sid = student_snapshot_id(turma, name)
        store[key] = {
            'report_month': month_key,
            'turma': turma,
            'student_id': sid,
            **legacy,
        }
        changed = True
    return changed


def session_in_month(row, month_key):
    from form_ui import storage_date_to_iso

    iso = storage_date_to_iso((row or {}).get('date', ''))
    if not iso or len(iso) < 7:
        return False
    return iso[:7] == month_key


def apply_upload_row(roster_row, monthly_store, month_key):
    """Split uploaded full row into roster profile + monthly review upsert."""
    profile, monthly = split_student_row(roster_row)
    merged_upload = {**profile, **monthly}
    upsert_monthly_review(monthly_store, merged_upload, month_key)
    return profile
