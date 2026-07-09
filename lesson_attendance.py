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


def students_with_attendance_in_month(lessons, attendance_rows, month_key):
    """Return (student keys with any attendance row, rows) for a review month."""
    month_rows = _attendance_rows_for_month(lessons, attendance_rows, month_key)
    tracked = set()
    for row in month_rows:
        name = (row.get('student_name') or '').strip()
        if not name:
            continue
        tracked.add((_turma_key(row.get('turma')), name))
    return tracked, month_rows


def recompute_faltas_from_attendance(students, lessons, attendance_rows, month_key):
    """Rebuild missed_aulas/faltas from saved lesson attendance for one review month.

    Attendance rows override manual missed_aulas only for lessons that were logged.
    Unlogged lessons keep any manual missed_aulas values.
    """
    tracked, month_rows = students_with_attendance_in_month(
        lessons, attendance_rows, month_key,
    )
    if not month_rows:
        return students

    lesson_keys = _lesson_keys_for_month(lessons, month_key)
    attendance_by_student = {}
    for row in month_rows:
        name = (row.get('student_name') or '').strip()
        if not name:
            continue
        key = (_turma_key(row.get('turma')), name)
        aula = _aula_key(row.get('aula_num'))
        if not aula:
            continue
        attendance_by_student.setdefault(key, {})[aula] = normalize_attendance_status(
            row.get('status'),
        )

    updated = []
    for student in students:
        row = dict(student)
        turma_key = _turma_key(row.get('turma'))
        name = (row.get('student_name') or '').strip()
        key = (turma_key, name)
        if key not in tracked:
            updated.append(row)
            continue

        result = {
            num.strip()
            for num in (row.get('missed_aulas') or '').split(',')
            if num.strip()
        }
        student_attendance = attendance_by_student.get(key, {})
        for lesson_turma, aula in lesson_keys:
            if lesson_turma != turma_key:
                continue
            if aula not in student_attendance:
                continue
            if student_attendance[aula] == 'absent':
                result.add(aula)
            else:
                result.discard(aula)

        nums = _sort_aula_nums(result)
        row['missed_aulas'] = ','.join(nums)
        try:
            stored_faltas = max(0, int((student.get('faltas') or '0').strip() or 0))
        except (TypeError, ValueError):
            stored_faltas = 0
        row['faltas'] = str(max(stored_faltas, len(nums)))
        updated.append(row)
    return updated


def reconcile_presence_after_lesson_removed(students, lessons, attendance_rows, month_key,
                                            turma, aula_num):
    """Refresh monthly faltas for one turma after a lesson row was deleted."""
    aula = _aula_key(aula_num)
    turma_key = _turma_key(turma)
    if not month_key or not aula or not turma_key:
        return students

    recomputed = {
        (
            _turma_key(row.get('turma')),
            (row.get('student_name') or '').strip(),
        ): row
        for row in recompute_faltas_from_attendance(
            students, lessons, attendance_rows, month_key,
        )
    }

    updated = []
    for student in students:
        name = (student.get('student_name') or '').strip()
        key = (_turma_key(student.get('turma')), name)
        if key[0] != turma_key:
            updated.append(student)
            continue
        row = dict(recomputed.get(key, student))
        nums = {
            num.strip()
            for num in (row.get('missed_aulas') or '').split(',')
            if num.strip()
        }
        nums.discard(aula)
        nums = _sort_aula_nums(nums)
        row['missed_aulas'] = ','.join(nums)
        try:
            stored_faltas = max(0, int((row.get('faltas') or '0').strip() or 0))
        except (TypeError, ValueError):
            stored_faltas = 0
        row['faltas'] = str(max(stored_faltas, len(nums)))
        updated.append(row)
    return updated


def remove_attendance_for_student(rows, turma, student_name):
    turma_key = _turma_key(turma)
    name = (student_name or '').strip()
    if not turma_key or not name:
        return list(rows or [])
    return [
        row for row in rows or []
        if not (
            _turma_key(row.get('turma')) == turma_key
            and (row.get('student_name') or '').strip() == name
        )
    ]


def remove_attendance_for_lesson(rows, turma, aula_num):
    turma_key = _turma_key(turma)
    aula = _aula_key(aula_num)
    if not turma_key or not aula:
        return list(rows or [])
    return [
        row for row in rows or []
        if not (
            _turma_key(row.get('turma')) == turma_key
            and _aula_key(row.get('aula_num')) == aula
        )
    ]


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
