"""Transfer a turma (class) from one teacher to another — students, registry, and related data."""

import io
import zipfile

from auth import normalize_teacher_name
from csv_export import csv_text
from csv_import import LESSON_FIELDS, STUDENT_FIELDS
from teacher_classes import (
    class_display_from_student_rows,
    count_students_in_turma,
    find_class,
    list_for_teacher,
    move_class_between_teachers,
)


def _teacher_key(teacher_name):
    return normalize_teacher_name(teacher_name).casefold()


def list_teachers_from_students(students):
    """Distinct teacher display names on student rows."""
    names = {
        normalize_teacher_name(row.get('teacher', ''))
        for row in students
        if (row.get('teacher') or '').strip()
    }
    return sorted(n for n in names if n)


def turmas_for_teacher(registry, students, teacher_name):
    """
    Turmas linked to a teacher (dashboard registry + student rows).
    Returns sorted list of dicts: turma, turma_display, student_count.
    """
    key = _teacher_key(teacher_name)
    if not key:
        return []

    by_code = {}
    for row in list_for_teacher(registry, teacher_name):
        code = (row.get('turma') or '').strip()
        if code:
            by_code[code] = row.get('turma_display') or code

    for row in students:
        if _teacher_key(row.get('teacher', '')) != key:
            continue
        code = (row.get('turma') or '').strip()
        if not code:
            continue
        if code not in by_code:
            by_code[code] = class_display_from_student_rows(
                [r for r in students if (r.get('turma') or '').strip() == code],
                code,
            )

    out = []
    for code in sorted(by_code, key=lambda c: by_code[c].casefold()):
        out.append({
            'turma': code,
            'turma_display': by_code[code],
            'student_count': count_students_in_turma(students, teacher_name, code),
        })
    return out


def preview_transfer(students, lessons, extra_sessions, registry, from_teacher, to_teacher, turma):
    """Summarize what a transfer would affect. Returns (summary_dict, error)."""
    from_name = normalize_teacher_name(from_teacher)
    to_name = normalize_teacher_name(to_teacher)
    code = (turma or '').strip()

    if not from_name or not to_name:
        return None, 'Selecione o professor de origem e de destino.'
    if not code:
        return None, 'Selecione a turma.'
    if from_name.casefold() == to_name.casefold():
        return None, 'Origem e destino devem ser professores diferentes.'

    student_count = count_students_in_turma(students, from_name, code)
    lesson_count = sum(
        1 for row in lessons if (row.get('turma') or '').strip() == code
    )
    extra_count = sum(
        1 for row in extra_sessions
        if _teacher_key(row.get('teacher', '')) == from_name.casefold()
        and (row.get('turma') or '').strip() == code
    )

    found = find_class(registry, from_name, code)
    class_display = (found or {}).get('turma_display') or code.replace('_', ' ')
    if not found and student_count:
        sample = [
            r for r in students
            if _teacher_key(r.get('teacher', '')) == from_name.casefold()
            and (r.get('turma') or '').strip() == code
        ]
        if sample:
            class_display = class_display_from_student_rows(sample, code)

    dest_has_turma = code in {
        r['turma'] for r in list_for_teacher(registry, to_name)
    }
    if dest_has_turma:
        return None, (
            f'O professor "{to_name}" já possui a turma "{code}". '
            'Escolha outro destino.'
        )

    if student_count == 0 and lesson_count == 0:
        return None, 'Nenhum aluno ou aula encontrado para esta turma e professor.'

    return {
        'from_teacher': from_name,
        'to_teacher': to_name,
        'turma': code,
        'turma_display': class_display,
        'student_count': student_count,
        'lesson_count': lesson_count,
        'extra_session_count': extra_count,
    }, None


def apply_transfer(students, lessons, extra_sessions, registry, from_teacher, to_teacher, turma):
    """
    Transfer turma ownership in place.
    Returns (summary_dict, error_message).
    """
    summary, err = preview_transfer(
        students, lessons, extra_sessions, registry,
        from_teacher, to_teacher, turma,
    )
    if err:
        return None, err

    from_name = summary['from_teacher']
    to_name = summary['to_teacher']
    code = summary['turma']
    from_key = from_name.casefold()

    class_row, reg_err = move_class_between_teachers(registry, from_name, to_name, code)
    if reg_err:
        return None, reg_err

    students_updated = 0
    for row in students:
        if _teacher_key(row.get('teacher', '')) != from_key:
            continue
        if (row.get('turma') or '').strip() != code:
            continue
        row['teacher'] = to_name
        if class_row:
            display = (class_row.get('turma_display') or '').strip()
            horario = (class_row.get('horario') or '').strip()
            if display:
                row['turma_display'] = display
            if horario:
                row['horario'] = horario
        students_updated += 1

    extra_updated = 0
    for row in extra_sessions:
        if _teacher_key(row.get('teacher', '')) != from_key:
            continue
        if (row.get('turma') or '').strip() != code:
            continue
        row['teacher'] = to_name
        extra_updated += 1

    return {
        **summary,
        'students_updated': students_updated,
        'extra_sessions_updated': extra_updated,
        'registry_moved': class_row is not None,
    }, None


def _rows_for_export(students, lessons, from_teacher, to_teacher, turma):
    """Student and lesson rows prepared for CSV export (teacher column updated)."""
    from_name = normalize_teacher_name(from_teacher)
    to_name = normalize_teacher_name(to_teacher)
    code = (turma or '').strip()
    from_key = from_name.casefold()

    export_students = []
    for row in students:
        if _teacher_key(row.get('teacher', '')) != from_key:
            continue
        if (row.get('turma') or '').strip() != code:
            continue
        copy = {field: (row.get(field) or '') for field in STUDENT_FIELDS}
        copy['teacher'] = to_name
        export_students.append(copy)

    export_lessons = [
        {field: (row.get(field) or '') for field in LESSON_FIELDS}
        for row in lessons
        if (row.get('turma') or '').strip() == code
    ]
    return export_students, export_lessons


def build_transfer_export_zip(students, lessons, registry, from_teacher, to_teacher, turma):
    """
    Build a ZIP with students.csv and lessons.csv for manual import.
    Returns (bytes, filename, error).
    """
    summary, err = preview_transfer(
        students, lessons, [], registry,
        from_teacher, to_teacher, turma,
    )
    if err:
        return None, None, err

    export_students, export_lessons = _rows_for_export(
        students, lessons, from_teacher, to_teacher, turma,
    )
    if not export_students and not export_lessons:
        return None, None, 'Nada para exportar nesta turma.'

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for name, fields, rows in (
            ('students.csv', STUDENT_FIELDS, export_students),
            ('lessons.csv', LESSON_FIELDS, export_lessons),
        ):
            if not rows:
                continue
            zf.writestr(name, csv_text(fields, rows).encode('utf-8'))

        readme = (
            f'Transferência de turma: {summary["turma_display"]} ({summary["turma"]})\n'
            f'De: {summary["from_teacher"]}\n'
            f'Para: {summary["to_teacher"]}\n\n'
            f'Alunos: {len(export_students)}\n'
            f'Aulas: {len(export_lessons)}\n\n'
            'Importe students.csv e lessons.csv pelo Upload CSV do professor destino.\n'
            'Após importar, remova os dados do professor de origem se ainda existirem.\n'
        )
        zf.writestr('LEIA-ME.txt', readme.encode('utf-8'))

    safe_code = summary['turma'].replace('/', '_')
    filename = f'transfer_{safe_code}_{summary["to_teacher"]}.zip'
    buf.seek(0)
    return buf.getvalue(), filename, None
