from form_ui import (
    NIVEL_CHOICES,
    date_from_form,
    format_class_schedule,
    format_date_for_input,
    is_valid_nivel,
    is_valid_weekday,
    parse_storage_date,
    parse_time_range_from_horario,
    storage_date_to_iso,
    turma_code_from_nivel,
)


def test_nivel_choices():
    assert 'KIDS 1' in NIVEL_CHOICES
    assert 'TEENS 5' in NIVEL_CHOICES
    assert len(NIVEL_CHOICES) == 9


def test_turma_code_from_nivel():
    assert turma_code_from_nivel('KIDS 1') == 'KIDS_1'
    assert turma_code_from_nivel('TEENS 3') == 'TEENS_3'


def test_is_valid_nivel():
    assert is_valid_nivel('KIDS 2')
    assert not is_valid_nivel('Adults Book 4')


def test_is_valid_weekday():
    assert is_valid_weekday('Terça-feira')
    assert not is_valid_weekday('Feriado')


def test_format_class_schedule():
    assert format_class_schedule(
        ['Terça-feira', 'Quinta-feira'], '19:00', '20:00',
    ) == 'Terça-feira e Quinta-feira 19:00 - 20:00'
    assert format_class_schedule([], '19:00', '20:00') == '19:00 - 20:00'


def test_parse_storage_date_brazilian_day_first():
    assert parse_storage_date('05/03/2026') == '05/03/2026'
    assert parse_storage_date('5/3/26') == '05/03/2026'
    assert parse_storage_date('05/03') == f'05/03/{__import__("datetime").datetime.now().year}'
    assert parse_storage_date('2026-03-05') == '05/03/2026'
    assert parse_storage_date('03/05/2026') == '03/05/2026'
    assert parse_storage_date('') == ''
    assert parse_storage_date('not-a-date') == ''


def test_format_date_for_input():
    assert format_date_for_input('01/02/2026') == '01/02/2026'
    assert format_date_for_input('2026-02-01') == '01/02/2026'


def test_storage_date_to_iso_from_brazilian():
    assert storage_date_to_iso('05/03/2026') == '2026-03-05'


def test_date_from_form_accepts_brazilian_text():
    class Form(dict):
        def get(self, key, default=''):
            return super().get(key, default)

    assert date_from_form(Form({'date_picker': '10/02/2026'})) == '10/02/2026'
    assert date_from_form(Form({'date_picker': '2026-02-10'})) == '10/02/2026'


def test_parse_time_range_from_horario():
    assert parse_time_range_from_horario('Terça e quinta, 19:00 - 20:00') == (
        '19:00', '20:00',
    )
    assert parse_time_range_from_horario('Tue 19:00') == ('', '')
