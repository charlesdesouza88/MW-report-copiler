from pathlib import Path

from compiler import build_student_ctx
from report_periods import (
    available_report_months,
    available_semesters,
    compute_month_trend,
    current_semester,
    default_report_month,
    default_semester,
    filter_lessons_by_month,
    filter_lessons_by_semester,
    filter_months_by_semester,
    filter_report_files_by_month,
    individual_report_filename,
    load_snapshots,
    month_in_semester,
    months_in_semester,
    parse_lesson_month,
    previous_calendar_month,
    report_month_from_filename,
    semester_for_date,
    semester_for_month,
    semester_label,
    student_snapshot_id,
    upsert_month_snapshots,
)


def test_parse_lesson_month():
    assert parse_lesson_month('10/02/2026') == '2026-02'
    assert parse_lesson_month('01/03') == f'{__import__("datetime").datetime.now().year}-03'


def test_semester_for_month_option_a():
    assert semester_for_month('2026-02') == '2026-S1'
    assert semester_for_month('2026-06') == '2026-S1'
    assert semester_for_month('2026-07') == '2026-S1'
    assert semester_for_month('2026-08') == '2026-S2'
    assert semester_for_month('2026-12') == '2026-S2'
    assert semester_for_month('2027-01') == '2026-S2'
    assert semester_for_date('15/03/2026') == '2026-S1'
    assert semester_label('2026-S1') == '1º semestre 2026'
    assert semester_label('2026-S2') == '2º semestre 2026'


def test_months_in_semester():
    assert months_in_semester('2026-S1') == [
        '2026-02', '2026-03', '2026-04', '2026-05', '2026-06', '2026-07',
    ]
    assert months_in_semester('2026-S2') == [
        '2026-08', '2026-09', '2026-10', '2026-11', '2026-12', '2027-01',
    ]
    assert month_in_semester('2026-03', '2026-S1')
    assert not month_in_semester('2026-09', '2026-S1')


def test_filter_lessons_and_months_by_semester():
    lessons = [
        {'date': '01/02/2026'},
        {'date': '15/03/2026'},
        {'date': '10/08/2026'},
    ]
    s1 = filter_lessons_by_semester(lessons, '2026-S1')
    assert len(s1) == 2
    s2 = filter_lessons_by_semester(lessons, '2026-S2')
    assert len(s2) == 1
    months = filter_months_by_semester(
        ['2026-02', '2026-08', '2026-03'], '2026-S1',
    )
    assert months == ['2026-02', '2026-03']


def test_available_and_default_semester(monkeypatch):
    from datetime import datetime

    class FakeDateTime:
        @classmethod
        def now(cls):
            return datetime(2026, 8, 5)

    monkeypatch.setattr('report_periods.datetime', FakeDateTime)
    lessons = [
        {'date': '01/02/2026'},
        {'date': '15/03/2026'},
    ]
    assert available_semesters(lessons, include_current=True) == ['2026-S1', '2026-S2']
    assert current_semester() == '2026-S2'
    # Prefer S1 when that is where lesson data lives
    assert default_semester(lessons) == '2026-S1'


def test_available_and_default_month():
    lessons = [
        {'date': '01/02/2026'},
        {'date': '15/03/2026'},
        {'date': ''},
    ]
    assert available_report_months(lessons) == ['2026-02', '2026-03']
    assert default_report_month(lessons) == '2026-03'


def test_default_report_month_prefers_current_over_future(monkeypatch):
    from datetime import datetime

    class FakeDateTime:
        @classmethod
        def now(cls):
            return datetime(2026, 5, 30)

    monkeypatch.setattr('report_periods.datetime', FakeDateTime)
    lessons = [
        {'date': '01/05/2026'},
        {'date': '01/06/2026'},
    ]
    assert default_report_month(lessons) == '2026-05'


def test_filter_lessons_by_month():
    lessons = [
        {'turma': 'A', 'aula_num': '1', 'date': '01/02/2026'},
        {'turma': 'A', 'aula_num': '2', 'date': '01/03/2026'},
    ]
    filtered = filter_lessons_by_month(lessons, '2026-02')
    assert len(filtered) == 1
    assert filtered[0]['aula_num'] == '1'


def test_report_month_from_filename():
    assert report_month_from_filename('MASTER_Jane_2026-03_report.html') == '2026-03'
    assert report_month_from_filename('MASTER_Jane_report.html') is None
    assert report_month_from_filename('MASTER_2026-03_class_diagnostic.html') == '2026-03'


def test_individual_report_filename():
    assert individual_report_filename('MASTER', 'Jane Doe') == 'MASTER_Jane_Doe_report.html'
    assert individual_report_filename('MASTER', 'Jane Doe', '2026-03') == (
        'MASTER_Jane_Doe_2026-03_report.html'
    )


def test_compute_month_trend():
    sid = student_snapshot_id('MASTER', 'Jane')
    snapshots = {
        f'MASTER|{sid}|2026-02': {'composite_score': 3},
    }
    improved = compute_month_trend(4, '2026-03', snapshots, 'MASTER', 'Jane')
    assert improved['direction'] == 'improved'
    assert improved['delta'] == 1

    first = compute_month_trend(4, '2026-02', {}, 'MASTER', 'Jane')
    assert first['direction'] == 'first'

    null_prior = compute_month_trend(
        4,
        '2026-03',
        {f'MASTER|{sid}|2026-02': {'composite_score': None}},
        'MASTER',
        'Jane',
    )
    assert null_prior['direction'] == 'first'


def test_previous_calendar_month():
    assert previous_calendar_month('2026-03') == '2026-02'
    assert previous_calendar_month('2026-01') == '2025-12'


def test_filter_report_files_by_month(tmp_path):
    a = tmp_path / 'MASTER_Jane_2026-02_report.html'
    b = tmp_path / 'MASTER_Jane_2026-03_report.html'
    c = tmp_path / 'MASTER_Jane_report.html'
    for p in (a, b, c):
        p.write_text('x', encoding='utf-8')
    feb = filter_report_files_by_month([a, b, c], '2026-02')
    assert [p.name for p in feb] == ['MASTER_Jane_2026-02_report.html']
    all_files = filter_report_files_by_month([a, b, c], '')
    assert len(all_files) == 3


def test_upsert_month_snapshots(tmp_path):
    path = tmp_path / 'snapshots.json'
    student = {
        'turma': 'MASTER',
        'student_name': 'Jane',
        'participacao': '4',
        'comportamento': '3',
        'speaking': '4',
        'listening': '4',
        'foco': '4',
        'writing': '4',
        'reading': '4',
        'gramatica': '4',
        'faltas': '0',
        'missed_aulas': '',
        'aula_extra': '',
    }
    lessons = [
        {
            'turma': 'MASTER',
            'aula_num': '1',
            'date': '01/03/2026',
            'licao_conteudo': 'L1',
            'atividade_extra': '',
            'habilidades': '',
        },
    ]
    upsert_month_snapshots(path, '2026-03', [student], lessons, build_student_ctx)
    store = load_snapshots(path)
    sid = student_snapshot_id('MASTER', 'Jane')
    assert f'MASTER|{sid}|2026-03' in store
    assert store[f'MASTER|{sid}|2026-03']['composite_score'] >= 1
    assert 'student_name' not in store[f'MASTER|{sid}|2026-03']
    assert store[f'MASTER|{sid}|2026-03']['student_id'] == sid
