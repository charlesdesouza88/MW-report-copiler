"""Reporting periods (months), snapshots, and month-over-month trends."""

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

from form_ui import storage_date_to_iso

_MONTH_KEY = re.compile(r'^\d{4}-\d{2}$')
_REPORT_MONTH_IN_NAME = re.compile(r'_(\d{4}-\d{2})_report\.html$')
_CLASS_MONTH_IN_NAME = re.compile(r'_(\d{4}-\d{2})_class_diagnostic\.html$')


def parse_lesson_month(date_str):
    """Return YYYY-MM for a lesson date in DD/MM or DD/MM/YYYY storage format."""
    iso = storage_date_to_iso(date_str)
    if not iso or len(iso) < 7:
        return None
    return iso[:7]


def available_report_months(lessons):
    months = set()
    for lesson in lessons:
        month = parse_lesson_month(lesson.get('date', ''))
        if month:
            months.add(month)
    return sorted(months)


def default_report_month(lessons):
    months = available_report_months(lessons)
    if not months:
        return datetime.now().strftime('%Y-%m')
    current = datetime.now().strftime('%Y-%m')
    if current in months:
        return current
    past_or_current = [month for month in months if month <= current]
    if past_or_current:
        return past_or_current[-1]
    return months[0]


def previous_calendar_month(month_key):
    if not _MONTH_KEY.match(month_key or ''):
        return None
    year, month = int(month_key[:4]), int(month_key[5:7])
    if month == 1:
        return f'{year - 1:04d}-12'
    return f'{year:04d}-{month - 1:02d}'


def lesson_in_month(lesson, month_key):
    return parse_lesson_month(lesson.get('date', '')) == month_key


def filter_lessons_by_month(lessons, month_key):
    if not month_key:
        return lessons
    return [lesson for lesson in lessons if lesson_in_month(lesson, month_key)]


def report_month_from_filename(filename):
    name = Path(filename).name
    match = _REPORT_MONTH_IN_NAME.search(name)
    if match:
        return match.group(1)
    match = _CLASS_MONTH_IN_NAME.search(name)
    if match:
        return match.group(1)
    return None


def month_label(month_key):
    if not month_key or not _MONTH_KEY.match(month_key):
        return month_key or ''
    year, month = month_key[:4], int(month_key[5:7])
    names = (
        '', 'Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho',
        'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro',
    )
    if 1 <= month <= 12:
        return f'{names[month]} {year}'
    return month_key


# Academic semesters (Mister Wiz / typical BR school year):
#   S1 = Feb–Jun (+ Jul break counted with S1)
#   S2 = Aug–Dec (+ Jan counted with previous year's S2)
_SEMESTER_KEY = re.compile(r'^(\d{4})-S([12])$')


def parse_semester_id(semester_id):
    """Return (year, half) for YYYY-S1 / YYYY-S2, or None."""
    match = _SEMESTER_KEY.match((semester_id or '').strip())
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def make_semester_id(year, half):
    return f'{int(year):04d}-S{int(half)}'


def semester_for_month(month_key):
    """
    Map YYYY-MM to semester_id.
    Feb–Jul → S1; Aug–Dec → S2; January → previous year's S2.
    """
    if not month_key or not _MONTH_KEY.match(month_key):
        return None
    year, month = int(month_key[:4]), int(month_key[5:7])
    if month == 1:
        return make_semester_id(year - 1, 2)
    if 2 <= month <= 7:
        return make_semester_id(year, 1)
    return make_semester_id(year, 2)


def semester_for_date(date_str):
    return semester_for_month(parse_lesson_month(date_str))


def current_semester(now=None):
    now = now or datetime.now()
    return semester_for_month(now.strftime('%Y-%m'))


def months_in_semester(semester_id):
    """Return YYYY-MM keys that belong to this semester (inclusive calendar months)."""
    parsed = parse_semester_id(semester_id)
    if not parsed:
        return []
    year, half = parsed
    if half == 1:
        return [f'{year:04d}-{m:02d}' for m in range(2, 8)]  # Feb–Jul
    # S2: Aug–Dec of year, plus January of next year
    months = [f'{year:04d}-{m:02d}' for m in range(8, 13)]
    months.append(f'{year + 1:04d}-01')
    return months


def month_in_semester(month_key, semester_id):
    return semester_for_month(month_key) == (semester_id or '').strip()


def filter_months_by_semester(months, semester_id):
    if not semester_id:
        return list(months)
    return [m for m in months if month_in_semester(m, semester_id)]


def filter_rows_by_semester_date(rows, semester_id, date_field='date'):
    """Filter rows whose date falls in semester; keep rows with missing/unparsed dates."""
    if not semester_id:
        return list(rows)
    out = []
    for row in rows:
        sid = semester_for_date(row.get(date_field, ''))
        if sid is None or sid == semester_id:
            out.append(row)
    return out


def filter_lessons_by_semester(lessons, semester_id):
    """Filter lessons by semester; keep undated lessons so drafts stay visible."""
    return filter_rows_by_semester_date(lessons, semester_id, date_field='date')


def available_semesters(lessons, *, include_current=True, now=None):
    """Semesters present in lesson dates, plus the current semester when requested."""
    found = set()
    for lesson in lessons or []:
        sid = semester_for_date(lesson.get('date', ''))
        if sid:
            found.add(sid)
    if include_current:
        found.add(current_semester(now=now))
    return sorted(found)


def semester_label(semester_id):
    parsed = parse_semester_id(semester_id)
    if not parsed:
        return semester_id or ''
    year, half = parsed
    return f'{half}º semestre {year}'


def default_semester(lessons, now=None):
    """Prefer current semester when it has data; else latest past semester with data."""
    now = now or datetime.now()
    current = current_semester(now=now)
    with_data = sorted({
        sid
        for lesson in (lessons or [])
        for sid in [semester_for_date(lesson.get('date', ''))]
        if sid
    })
    if current in with_data:
        return current
    past_with_data = [sid for sid in with_data if sid <= current]
    if past_with_data:
        return past_with_data[-1]
    if with_data:
        return with_data[0]
    return current


def student_composite_score(ctx):
    from compiler import round_half_up

    return round_half_up(
        (ctx['dev_overall'] + ctx['part_overall'] + ctx['comp_overall'] + ctx['pres_score']) / 4
    )


def _as_int_score(value, default=0):
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def student_snapshot_id(turma, student_name):
    """Stable pseudonym for snapshot storage (no PII in student_snapshots.json)."""
    raw = f'{(turma or "").strip()}|{(student_name or "").strip()}'.casefold()
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]


def compute_month_trend(current_score, report_month, snapshots, turma, student_name):
    """Compare composite score to the previous calendar month's snapshot."""
    prev_month = previous_calendar_month(report_month)
    if not prev_month:
        return _trend('first', None, current_score)

    sid = student_snapshot_id(turma, student_name)
    key = _snapshot_key(turma, sid, prev_month)
    prior = snapshots.get(key)
    if not prior:
        return _trend('first', None, current_score)

    raw_prior = prior.get('composite_score')
    if raw_prior is None:
        return _trend('first', None, current_score)
    prior_score = _as_int_score(raw_prior, 0)
    delta = _as_int_score(current_score) - prior_score
    if delta > 0:
        return _trend('improved', delta, current_score, prior_score)
    if delta < 0:
        return _trend('declined', delta, current_score, prior_score)
    return _trend('stable', 0, current_score, prior_score)


def _trend(direction, delta, current_score, prior_score=None):
    labels = {
        'improved': 'Melhorou',
        'declined': 'Piorou',
        'stable': 'Estável',
        'first': 'Primeiro período',
    }
    symbols = {
        'improved': '▲',
        'declined': '▼',
        'stable': '→',
        'first': '—',
    }
    return dict(
        direction=direction,
        delta=delta,
        label=labels[direction],
        symbol=symbols[direction],
        current_score=current_score,
        prior_score=prior_score,
    )


def _snapshot_key(turma, student_id, month_key):
    return f'{turma}|{student_id}|{month_key}'


def prior_month_snapshot(snapshots, turma, student_name, report_month):
    """Return the previous calendar month's snapshot row, if any."""
    prev_month = previous_calendar_month(report_month)
    if not prev_month or not snapshots:
        return None
    sid = student_snapshot_id(turma, student_name)
    return snapshots.get(_snapshot_key(turma, sid, prev_month))


def load_snapshots(path):
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding='utf-8'))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(raw, list):
        return {}
    out = {}
    for row in raw:
        if not isinstance(row, dict):
            continue
        if row.get('is_test'):
            continue
        month = (row.get('report_month') or '').strip()
        turma = (row.get('turma') or '').strip()
        sid = (row.get('student_id') or '').strip()
        if not sid:
            legacy_name = (row.get('student_name') or '').strip()
            if legacy_name:
                sid = student_snapshot_id(turma, legacy_name)
        if not month or not turma or not sid:
            continue
        out[_snapshot_key(turma, sid, month)] = row
    return out


def save_snapshots(path, snapshot_rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(snapshot_rows, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )


def upsert_month_snapshots(path, report_month, students, lessons, build_ctx):
    """Persist composite scores for each student for this reporting month."""
    store = load_snapshots(path)
    for student in students:
        turma = student.get('turma', '').strip()
        name = student.get('student_name', '').strip()
        if not turma or not name:
            continue
        ctx = build_ctx(student, lessons, report_month=report_month)
        composite = student_composite_score(ctx)
        sid = student_snapshot_id(turma, name)
        store[_snapshot_key(turma, sid, report_month)] = {
            'report_month': report_month,
            'turma': turma,
            'student_id': sid,
            'composite_score': composite,
            'dev_overall': ctx['dev_overall'],
            'part_overall': ctx['part_overall'],
            'comp_overall': ctx['comp_overall'],
            'pres_score': ctx['pres_score'],
        }
    save_snapshots(path, list(store.values()))


def individual_report_filename(turma, student_name, report_month=None):
    from report_names import student_report_filename

    return student_report_filename(turma, student_name, report_month)


def class_diagnostic_filename(turma, report_month=None):
    from report_names import class_diagnostic_filename as class_diagnostic_name

    return class_diagnostic_name(turma, report_month)


def filter_report_files_by_month(files, month_key):
    if not month_key:
        return list(files)
    filtered = []
    for path in files:
        file_month = report_month_from_filename(path.name)
        if file_month == month_key:
            filtered.append(path)
    return filtered
