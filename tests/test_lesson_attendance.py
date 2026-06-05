from lesson_attendance import (
    ATTENDANCE_CHOICES,
    apply_attendance_to_students,
    attendance_map_for_lesson,
    normalize_attendance_status,
    parse_attendance_form,
    replace_lesson_attendance,
    students_for_turma,
)


class DummyForm(dict):
    def get(self, key, default=None):
        return dict.get(self, key, default)


def test_normalize_attendance_status():
    assert normalize_attendance_status('present') == 'present'
    assert normalize_attendance_status('Ausente') == 'absent'
    assert normalize_attendance_status('Atrasado') == 'tardy'
    assert normalize_attendance_status('') == 'present'


def test_replace_lesson_attendance():
    existing = [
        {'turma': 'STAR', 'aula_num': '1', 'student_name': 'Ana', 'status': 'present'},
        {'turma': 'STAR', 'aula_num': '2', 'student_name': 'Ana', 'status': 'absent'},
    ]
    entries = [
        {'student_name': 'Ana', 'status': 'absent'},
        {'student_name': 'Bob', 'status': 'tardy'},
    ]
    rows = replace_lesson_attendance(existing, 'STAR', '2', entries)
    assert len(rows) == 3
    star_two = [row for row in rows if row['aula_num'] == '2' and row['turma'] == 'STAR']
    assert len(star_two) == 2
    assert attendance_map_for_lesson(rows, 'STAR', '2') == {
        'Ana': 'absent',
        'Bob': 'tardy',
    }


def test_apply_attendance_to_students():
    students = [
        {
            'turma': 'STAR',
            'student_name': 'Ana',
            'faltas': '0',
            'missed_aulas': '',
        },
        {
            'turma': 'STAR',
            'student_name': 'Bob',
            'faltas': '1',
            'missed_aulas': '1',
        },
    ]
    updated = apply_attendance_to_students(
        students,
        'STAR',
        '2',
        {'Ana': 'absent', 'Bob': 'present'},
    )
    ana = updated[0]
    bob = updated[1]
    assert ana['missed_aulas'] == '2'
    assert ana['faltas'] == '1'
    assert bob['missed_aulas'] == '1'
    assert bob['faltas'] == '1'


def test_apply_attendance_tardy_counts_as_present():
    students = [{
        'turma': 'STAR',
        'student_name': 'Ana',
        'faltas': '1',
        'missed_aulas': '1',
    }]
    updated = apply_attendance_to_students(
        students,
        'STAR',
        '1',
        {'Ana': 'tardy'},
    )
    assert updated[0]['missed_aulas'] == ''
    assert updated[0]['faltas'] == '0'


def test_parse_attendance_form():
    form = DummyForm({
        'attendance_count': '2',
        'attendance_student_0': 'Ana',
        'attendance_status_0': 'absent',
        'attendance_student_1': 'Bob',
        'attendance_status_1': 'present',
    })
    entries = parse_attendance_form(form)
    assert entries == [
        {'student_name': 'Ana', 'status': 'absent'},
        {'student_name': 'Bob', 'status': 'present'},
    ]


def test_students_for_turma_sorted():
    students = [
        {'turma': 'star', 'student_name': 'Zoe'},
        {'turma': 'STAR', 'student_name': 'Ana'},
        {'turma': 'COMET', 'student_name': 'Bob'},
    ]
    rows = students_for_turma(students, 'STAR')
    assert [row['student_name'] for row in rows] == ['Ana', 'Zoe']


def test_attendance_choices():
    assert ATTENDANCE_CHOICES == ('present', 'absent', 'tardy')
