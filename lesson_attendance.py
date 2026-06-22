"""Per-student attendance for logged lessons (present / absent / tardy)."""

import re

ATTENDANCE_CHOICES = ('present', 'absent', 'tardy')

ATTENDANCE_LABELS = {
    'present': 'Presente',
    'absent': 'Ausente',
    'tardy': 'Atrasado',
}

ATTENDANCE_FIELDS = ['turma', 'aula_num', 'student_name', 'status']

_STATUS_ALIASES = {
    'presente': 'present',
    'p': 'present',
    'ausente': 'absent',
    'a': 'absent',
    'atrasado': 'tardy',
    'atraso': 'tardy',
}


def normalize_attendance_status(value):
    raw = (value or '').strip().lower()
    if raw in ATTENDANCE_CHOICES:
        return raw
    return _STATUS_ALIASES.get(raw, 'present')


def attendance_label(status):
    return ATTENDANCE_LABELS.get(status, status or '')


def _turma_key(turma):
    return (turma or '').strip().upper()


def _aula_key(aula_num):
    return str(aula_num or '').strip()


def records_for_lesson(rows, turma, aula_num):
    turma_key = _turma_key(turma)
    aula = _aula_key(aula_num)
    return [
        row for row in rows
        if _turma_key(row.get('turma')) == turma_key
        and _aula_key(row.get('aula_num')) == aula
    ]


def attendance_map_for_lesson(rows, turma, aula_num):
    return {
        (row.get('student_name') or '').strip(): normalize_attendance_status(row.get('status'))
        for row in records_for_lesson(rows, turma, aula_num)
        if (row.get('student_name') or '').strip()
    }


def replace_lesson_attendance(all_rows, turma, aula_num, entries):
    turma_key = _turma_key(turma)
    aula = _aula_key(aula_num)
    kept = [
        row for row in all_rows
        if not (
            _turma_key(row.get('turma')) == turma_key
            and _aula_key(row.get('aula_num')) == aula
        )
    ]
    new_rows = []
    for entry in entries:
        name = (entry.get('student_name') or '').strip()
        if not name:
            continue
        new_rows.append({
            'turma': turma_key,
            'aula_num': aula,
            'student_name': name,
            'status': normalize_attendance_status(entry.get('status')),
        })
    return kept + new_rows


def _sort_aula_nums(nums):
    def key(num):
        text = str(num).strip()
        try:
            return (0, int(float(text)))
        except (TypeError, ValueError):
            return (1, text.casefold())

    return sorted({str(num).strip() for num in nums if str(num).strip()}, key=key)


def _lesson_keys_for_month(lessons, month_key):
    from report_periods import lesson_in_month

    keys = set()
    for lesson in lessons or []:
        if not lesson_in_month(lesson, month_key):
            continue
        turma = _turma_key(lesson.get('turma'))
        aula = _aula_key(lesson.get('aula_num'))
        if turma and aula:
            keys.add((turma, aula))
    return keys


def _attendance_rows_for_month(lessons, attendance_rows, month_key):
    if not month_key:
        return []
    lesson_keys = _lesson_keys_for_month(lessons, month_key)
    if not lesson_keys:
        return []
    return [
        row for row in attendance_rows or []
        if (
            _turma_key(row.get('turma')),
            _aula_key(row.get('aula_num')),
        ) in lesson_keys
    ]


def recompute_faltas_from_attendance(students, lessons, attendance_rows, month_key):
    """Rebuild missed_aulas/faltas from saved lesson attendance for one review month."""
    month_rows = _attendance_rows_for_month(lessons, attendance_rows, month_key)
    if not month_rows:
        return students

    missed = {}
    for row in month_rows:
        if normalize_attendance_status(row.get('status')) != 'absent':
            continue
        name = (row.get('student_name') or '').strip()
        if not name:
            continue
        key = (_turma_key(row.get('turma')), name)
        missed.setdefault(key, set()).add(_aula_key(row.get('aula_num')))

    updated = []
    for student in students:
        row = dict(student)
        key = (_turma_key(row.get('turma')), (row.get('student_name') or '').strip())
        nums = _sort_aula_nums(missed.get(key, set()))
        row['missed_aulas'] = ','.join(nums)
        row['faltas'] = str(len(nums))
        updated.append(row)
    return updated


def apply_attendance_to_students(students, turma, aula_num, attendance_by_name):
    """Update missed_aulas and faltas when a lesson is saved."""
    turma_key = _turma_key(turma)
    aula = _aula_key(aula_num)
    if not aula:
        return students

    updated = []
    for student in students:
        row = dict(student)
        if _turma_key(row.get('turma')) != turma_key:
            updated.append(row)
            continue
        name = (row.get('student_name') or '').strip()
        status = normalize_attendance_status(attendance_by_name.get(name, 'present'))
        nums = [
            num.strip()
            for num in (row.get('missed_aulas') or '').split(',')
            if num.strip()
        ]
        if status == 'absent':
            if aula not in nums:
                nums.append(aula)
        else:
            nums = [num for num in nums if num != aula]
        row['missed_aulas'] = ','.join(nums)
        row['faltas'] = str(len(nums))
        updated.append(row)
    return updated


def parse_attendance_form(form):
    try:
        count = int(form.get('attendance_count') or 0)
    except (TypeError, ValueError):
        count = 0
    entries = []
    for index in range(count):
        name = (form.get(f'attendance_student_{index}') or '').strip()
        if not name:
            continue
        status = form.get(f'attendance_status_{index}') or 'present'
        entries.append({'student_name': name, 'status': status})
    return entries


def students_for_turma(all_students, turma):
    turma_key = _turma_key(turma)
    return sorted(
        [
            row for row in all_students
            if _turma_key(row.get('turma')) == turma_key
        ],
        key=lambda row: (row.get('student_name') or '').casefold(),
    )


def students_by_turma(all_students, turmas):
    return {
        _turma_key(turma): [
            {'student_name': (row.get('student_name') or '').strip()}
            for row in students_for_turma(all_students, turma)
        ]
        for turma in turmas
        if turma
    }


def attendance_field_key(name):
    key = re.sub(r'[^A-Za-z0-9]+', '_', (name or '').strip()).strip('_')
    return key[:64] or 'student'
