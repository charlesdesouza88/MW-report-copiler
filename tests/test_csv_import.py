from pathlib import Path

from csv_import import (
    apply_attendance_to_students,
    convert_teacher_folder,
    merge_lessons,
    month_sort_key_from_filename,
    normalize_student_row,
    parse_attendance_control_csv,
    parse_lesson_plan_csv,
    parse_students_csv,
    parse_teacher_student_report_csv,
    parse_upload_csv,
    student_name_matches,
    turma_from_filename,
    write_lessons_csv,
)


SAMPLE_PLAN = """\
,,,,,,
,"SPARK - KIDS 1 (Segunda e quarta, 8:00-9:30)",,,,,PRAZO: Semanal - Segunda-feira
,,DATA,LIÇÃO + CONTEÚDO,ATIVIDADE EXTRA,HABILIDADES,
,1,09/02/2026,,,,
,5,02/03/2026,Class 0,Introductions / Class rules,,
,6,04/03/2026,Lesson 1,Family names,Inteligencia Emocional,
,27,,,,,
"""


def test_parse_lesson_plan_csv_spark():
    rows, errors = parse_lesson_plan_csv(SAMPLE_PLAN)
    assert not errors
    assert len(rows) == 3
    assert rows[0]['turma'] == 'SPARK'
    assert rows[0]['aula_num'] == '1'
    assert rows[1]['licao_conteudo'] == 'Class 0'
    assert rows[2]['habilidades'] == 'Inteligência emocional'


def test_parse_students_csv_compiler_format():
    text = Path(__file__).resolve().parents[1].joinpath('data/templates/students_template.csv').read_text(
        encoding='utf-8-sig',
    )
    rows, errors = parse_students_csv(text)
    assert not errors
    assert len(rows) == 1
    assert rows[0]['student_name'] == 'Sample Learner One'


def test_merge_lessons_replaces_one_turma():
    existing = [
        {'turma': 'MASTER', 'aula_num': '1', 'date': '01/01', 'licao_conteudo': 'A', 'atividade_extra': '', 'habilidades': ''},
        {'turma': 'SPARK', 'aula_num': '1', 'date': '01/01', 'licao_conteudo': 'Old', 'atividade_extra': '', 'habilidades': ''},
    ]
    updated = [
        {'turma': 'SPARK', 'aula_num': '1', 'date': '02/02', 'licao_conteudo': 'New', 'atividade_extra': '', 'habilidades': ''},
    ]
    merged = merge_lessons(existing, updated, turma='SPARK')
    assert len(merged) == 2
    assert merged[0]['turma'] == 'MASTER'
    assert merged[1]['licao_conteudo'] == 'New'


def test_write_lessons_csv_roundtrip(tmp_path):
    rows = [{
        'turma': 'SPARK',
        'aula_num': '1',
        'date': '09/02/2026',
        'licao_conteudo': 'Lesson 1',
        'atividade_extra': 'Extra',
        'habilidades': 'Speaking',
    }]
    path = tmp_path / 'lessons.csv'
    write_lessons_csv(path, rows)
    text = path.read_text(encoding='utf-8')
    assert 'SPARK,1,09/02/2026,Lesson 1,Extra,Speaking' in text


SAMPLE_TEACHER_REPORT = """\
,,,,,,,,,,,,,
,Teacher One - COMET,,,,,,,,,,,,
,Alunos,Participação,Foco,Comportamento,Speaking,Listening,Writing,Reading,Aula extra,Materias,Atrasos,Faltas,Observação
,Sample Learner One,4,4,5,3,4,4,4,,,,,
,Sample Learner Two,2,3,5,1,1,1,1,Reforço,,,,"Synthetic observation"
,Nº de alunos: 2,,,,,,,,,,,,
"""


def test_parse_teacher_student_report_csv():
    rows, errors = parse_teacher_student_report_csv(
        SAMPLE_TEACHER_REPORT,
        'Teacher One',
        'Teacher One - Abril-COMET.csv',
    )
    assert not errors
    assert len(rows) == 2
    assert rows[0]['teacher'] == 'Teacher One'
    assert rows[0]['turma'] == 'COMET'
    assert rows[1]['aula_extra'] == 'Reforço'
    assert rows[1]['faltas'] == '0'


def test_turma_from_filename_ignores_teacher_and_month():
    assert turma_from_filename('Teacher One - Março - Rise.csv', 'Teacher One') == 'RISE'
    assert month_sort_key_from_filename('Teacher Two - Maio - Impact.csv') == 5


def test_convert_teacher_folder(tmp_path):
    teacher_dir = tmp_path / 'Teacher One'
    teacher_dir.mkdir()
    (teacher_dir / 'Teacher One - Abril-COMET.csv').write_text(SAMPLE_TEACHER_REPORT, encoding='utf-8')
    (teacher_dir / 'Teacher One - Planejamento de aula - Comet.csv').write_text(
        """,,,,,,
,"COMET - KIDS 2 (Segunda e quarta, 8:00-9:30)",,,,,PRAZO: Semanal - Segunda-feira
,,DATA,LIÇÃO + CONTEÚDO,ATIVIDADE EXTRA,HABILIDADES,
,1,09/02/2026,Aula zero,Dinâmica,,
""",
        encoding='utf-8',
    )
    students, lessons, warnings = convert_teacher_folder(teacher_dir)
    assert not warnings
    assert len(students) == 2
    assert students[0]['horario'] == 'Segunda e quarta, 8:00-9:30'
    assert lessons[0]['turma'] == 'COMET'


SAMPLE_ATTENDANCE = """\
MAY,teens 01, MAY,,,,,,,,,,
Turma,teens 01,,,,,,,,,,,
Horário,14 as 15,5,7,12,15,19,21,26,28,30,31,OBSERVAÇÕES
Mentor,TEACHER ONE,,,,,,,,,,,
,ALUNOS,,,,,,,,,,,
,SAMPLE LEARNER ONE,P,P,A,P,A,A,P,,,,
,SAMPLE L. TWO,P,A,P,P,P,P,P,,,,REVIEW UNIT MATERIAL
"""


def test_student_name_matches():
    assert student_name_matches('SAMPLE LEARNER ONE', 'Sample Learner One')
    assert student_name_matches('SAMPLE L. TWO', 'Sample Learner Two')


def test_parse_attendance_control_csv():
    lessons = [
        {'turma': 'IMPACT', 'aula_num': '22', 'date': '05/05/2026', 'licao_conteudo': '', 'atividade_extra': '', 'habilidades': ''},
        {'turma': 'IMPACT', 'aula_num': '26', 'date': '12/05/2026', 'licao_conteudo': '', 'atividade_extra': '', 'habilidades': ''},
        {'turma': 'IMPACT', 'aula_num': '28', 'date': '19/05/2026', 'licao_conteudo': '', 'atividade_extra': '', 'habilidades': ''},
    ]
    records, errors = parse_attendance_control_csv(
        SAMPLE_ATTENDANCE,
        'Teacher One',
        'IMPACT',
        lessons,
        'Teacher One - ATTENDANCE CONTROL.csv',
    )
    assert not errors
    learner = next(r for r in records if 'SAMPLE LEARNER ONE' in r['attendance_name'])
    assert learner['faltas'] == '3'
    assert learner['missed_aulas'] == '26,28'


def test_apply_attendance_to_students():
    students = [{
        'teacher': 'Teacher One',
        'turma': 'IMPACT',
        'student_name': 'Sample Learner One',
        'faltas': '0',
        'missed_aulas': '',
        'observacao': 'existing',
    }]
    records = [{
        'teacher': 'Teacher One',
        'turma': 'IMPACT',
        'attendance_name': 'SAMPLE LEARNER ONE',
        'faltas': '2',
        'missed_aulas': '26,28',
        'notes': 'late once',
    }]
    apply_attendance_to_students(students, records, [])
    assert students[0]['faltas'] == '2'
    assert students[0]['missed_aulas'] == '26,28'
    assert 'Attendance: late once' in students[0]['observacao']


def test_normalize_student_row_fills_gramatica():
    row = normalize_student_row({
        'teacher': 'Teacher One',
        'turma': 'COMET',
        'student_name': 'Test',
        'speaking': '4',
        'writing': '2',
        'reading': '4',
        'listening': '4',
        'participacao': '4',
        'comportamento': '5',
    })
    assert row['gramatica'] == '4'
    assert row['trabalho_equipe'] == '5'


def test_parse_upload_csv_teacher_grade_sheet():
    rows, note, errors = parse_upload_csv(
        'students',
        SAMPLE_TEACHER_REPORT,
        user={'teacher_name': 'Teacher One'},
        source_filename='Teacher One - Abril-COMET.csv',
    )
    assert not errors
    assert note
    assert rows[0]['teacher'] == 'Teacher One'
    assert rows[0]['turma'] == 'COMET'
    assert rows[0]['gramatica']
