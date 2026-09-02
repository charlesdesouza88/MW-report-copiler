import csv
import io
import zipfile

from class_transfer import (
    apply_transfer,
    build_transfer_export_zip,
    preview_transfer,
    turmas_for_teacher,
)
from teacher_classes import add_class, move_class_between_teachers


def _seed_class(data, teacher, turma, display, weekdays=None):
    add_class(
        data,
        teacher,
        turma_display=display,
        class_weekdays=weekdays or ['Terça-feira', 'Quinta-feira'],
        class_time_start='19:00',
        class_time_end='20:00',
        turma=turma,
    )


def _sample_students():
    return [
        {
            'teacher': 'Chuck',
            'turma': 'MASTER',
            'turma_display': 'Masters',
            'nivel': 'Adults Book 4',
            'horario': 'Terça-feira e Quinta-feira 19:00 - 20:00',
            'student_name': 'Jane Doe',
        },
        {
            'teacher': 'Chuck',
            'turma': 'MASTER',
            'turma_display': 'Masters',
            'nivel': 'Adults Book 4',
            'horario': 'Terça-feira e Quinta-feira 19:00 - 20:00',
            'student_name': 'John Smith',
        },
        {
            'teacher': 'Ana',
            'turma': 'KIDS',
            'turma_display': 'Kids 1',
            'nivel': 'KIDS 1',
            'horario': 'Mon 10:00',
            'student_name': 'Kid One',
        },
    ]


def _sample_lessons():
    return [
        {'turma': 'MASTER', 'aula_num': '1', 'date': '01/01/2026', 'licao_conteudo': 'L1'},
        {'turma': 'MASTER', 'aula_num': '2', 'date': '03/01/2026', 'licao_conteudo': 'L2'},
        {'turma': 'KIDS', 'aula_num': '1', 'date': '02/01/2026', 'licao_conteudo': 'K1'},
    ]


def test_turmas_for_teacher_combines_registry_and_students():
    registry = {}
    _seed_class(registry, 'Chuck', 'MASTER', 'Masters')
    students = _sample_students()
    options = turmas_for_teacher(registry, students, 'Chuck')
    codes = {o['turma'] for o in options}
    assert codes == {'MASTER'}
    master = next(o for o in options if o['turma'] == 'MASTER')
    assert master['student_count'] == 2
    assert master['turma_display'] == 'Masters'


def test_move_class_between_teachers_registry(tmp_path):
    from teacher_classes import list_for_teacher, load_registry, move_class_between_teachers, save_registry

    path = tmp_path / 'teacher_classes.json'
    data = {}
    _seed_class(data, 'Chuck', 'MASTER', 'Masters')
    save_registry(path, data)

    row, err = move_class_between_teachers(data, 'Chuck', 'Paula', 'MASTER')
    assert err is None
    assert row['turma'] == 'MASTER'
    save_registry(path, data)

    assert list_for_teacher(load_registry(path), 'Chuck') == []
    assert len(list_for_teacher(load_registry(path), 'Paula')) == 1


def test_move_class_blocked_when_dest_has_turma():
    registry = {}
    _seed_class(registry, 'Chuck', 'MASTER', 'Masters')
    _seed_class(registry, 'Paula', 'MASTER', 'Masters copy')
    _, err = move_class_between_teachers(registry, 'Chuck', 'Paula', 'MASTER')
    assert err is not None
    assert 'já possui' in err


def test_apply_transfer_updates_students_and_extra_sessions():
    registry = {}
    _seed_class(registry, 'Chuck', 'MASTER', 'Masters')
    students = _sample_students()
    lessons = _sample_lessons()
    extra = [
        {'teacher': 'Chuck', 'turma': 'MASTER', 'student_name': 'Jane Doe', 'date': '05/01/2026'},
    ]

    summary, err = apply_transfer(
        students, lessons, extra, registry, 'Chuck', 'Paula', 'MASTER',
    )
    assert err is None
    assert summary['students_updated'] == 2
    assert summary['extra_sessions_updated'] == 1

    chuck_master = [
        s for s in students
        if s['teacher'] == 'Chuck' and s['turma'] == 'MASTER'
    ]
    assert chuck_master == []

    paula_master = [s for s in students if s['teacher'] == 'Paula' and s['turma'] == 'MASTER']
    assert len(paula_master) == 2
    assert extra[0]['teacher'] == 'Paula'
    assert len(turmas_for_teacher(registry, [], 'Paula')) == 1


def test_preview_rejects_same_teacher():
    registry = {}
    students = _sample_students()
    _, err = preview_transfer(students, [], [], registry, 'Chuck', 'Chuck', 'MASTER')
    assert err is not None


def test_build_transfer_export_zip():
    registry = {}
    _seed_class(registry, 'Chuck', 'MASTER', 'Masters')
    students = _sample_students()
    lessons = _sample_lessons()

    payload, filename, err = build_transfer_export_zip(
        students, lessons, registry, 'Chuck', 'Paula', 'MASTER',
    )
    assert err is None
    assert filename.endswith('.zip')

    zf = zipfile.ZipFile(io.BytesIO(payload))
    names = set(zf.namelist())
    assert 'students.csv' in names
    assert 'lessons.csv' in names
    assert 'LEIA-ME.txt' in names

    students_csv = zf.read('students.csv').decode('utf-8')
    assert 'Paula' in students_csv
    assert 'Chuck' not in students_csv.split('teacher')[1] or 'Paula' in students_csv
    lessons_csv = zf.read('lessons.csv').decode('utf-8')
    assert 'MASTER' in lessons_csv
    assert lessons_csv.count('MASTER') >= 2


def test_build_transfer_export_zip_neutralizes_spreadsheet_formulas():
    registry = {}
    _seed_class(registry, 'Chuck', 'MASTER', 'Masters')
    students = _sample_students()
    students[0]['student_name'] = '=2+2'
    lessons = _sample_lessons()
    lessons[0]['licao_conteudo'] = '+SUM(A1:A2)'

    payload, _, err = build_transfer_export_zip(
        students, lessons, registry, 'Chuck', 'Paula', 'MASTER',
    )

    assert err is None
    zf = zipfile.ZipFile(io.BytesIO(payload))
    student_rows = list(csv.DictReader(io.StringIO(zf.read('students.csv').decode('utf-8'))))
    lesson_rows = list(csv.DictReader(io.StringIO(zf.read('lessons.csv').decode('utf-8'))))
    assert student_rows[0]['student_name'] == "'=2+2"
    assert lesson_rows[0]['licao_conteudo'] == "'+SUM(A1:A2)"
