"""Tests for per-month student review storage."""

import json
from pathlib import Path

from student_reviews import (
    DEFAULT_MONTHLY_VALUES,
    apply_upload_row,
    extract_roster_fields,
    merge_roster_for_month,
    migrate_roster_scores_to_month,
    review_key,
    session_in_month,
    split_student_row,
    store_from_rows,
    upsert_monthly_review,
)


def _student(name='Jane', participacao='4'):
    return {
        'teacher': 'Chuck',
        'turma': 'MASTER',
        'turma_display': 'Masters',
        'nivel': 'Book 4',
        'horario': 'Tue 19:00',
        'student_name': name,
        'participacao': participacao,
        'comportamento': '3',
        'speaking': '4',
        'listening': '5',
        'foco': '4',
        'writing': '3',
        'reading': '4',
        'gramatica': '2',
        'trabalho_equipe': '3',
        'organizacao': '3',
        'pontualidade': '3',
        'respeito_regras': '3',
        'faltas': '1',
        'missed_aulas': '2',
        'aula_extra': '',
        'feedback_participacao': '',
        'feedback_foco': '',
        'feedback_trabalho_equipe': '',
        'recomendacoes': '',
        'observacao': '',
    }


def test_split_student_row():
    profile, monthly = split_student_row(_student())
    assert profile['student_name'] == 'Jane'
    assert profile['turma'] == 'MASTER'
    assert monthly['participacao'] == '4'
    assert 'student_name' not in profile or profile.get('student_name')


def test_review_key_stable():
    k1 = review_key('MASTER', 'Jane Doe', '2026-03')
    k2 = review_key('MASTER', 'Jane Doe', '2026-03')
    assert k1 == k2
    assert k1.endswith('|2026-03')


def test_merge_uses_monthly_store():
    roster = [_student(participacao='1')]
    store = {}
    upsert_monthly_review(store, _student(participacao='5'), '2026-03')
    merged = merge_roster_for_month(roster, store, '2026-03')
    assert merged[0]['participacao'] == '5'
    assert merged[0]['student_name'] == 'Jane'


def test_merge_unsaved_month_uses_defaults_not_previous():
    roster = [_student(participacao='1')]
    store = {}
    upsert_monthly_review(store, _student(participacao='4'), '2026-02')
    merged = merge_roster_for_month(roster, store, '2026-03')
    assert merged[0]['participacao'] == DEFAULT_MONTHLY_VALUES['participacao']
    assert merged[0]['faltas'] == '0'
    assert merged[0]['missed_aulas'] == ''
    assert merged[0]['aula_extra'] == ''


def test_merge_unsaved_month_does_not_copy_presence_or_scores():
    roster = [_student()]
    store = {}
    upsert_monthly_review(
        store,
        {**_student(), 'faltas': '3', 'missed_aulas': '1,2', 'aula_extra': 'Reposição'},
        '2026-04',
    )
    merged = merge_roster_for_month(roster, store, '2026-05')
    assert merged[0]['faltas'] == '0'
    assert merged[0]['missed_aulas'] == ''
    assert merged[0]['aula_extra'] == ''
    assert merged[0]['participacao'] == DEFAULT_MONTHLY_VALUES['participacao']


def test_merge_falls_back_to_roster_legacy_when_no_monthly_rows():
    roster = [_student(participacao='3')]
    store = {}
    merged = merge_roster_for_month(roster, store, '2026-03')
    assert merged[0]['participacao'] == '3'


def test_merge_ignores_legacy_roster_once_monthly_exists():
    roster = [_student(participacao='1')]
    store = {}
    upsert_monthly_review(store, _student(participacao='5'), '2026-02')
    # Roster still has participacao=1, but monthly history exists → fresh defaults.
    merged = merge_roster_for_month(roster, store, '2026-03')
    assert merged[0]['participacao'] == DEFAULT_MONTHLY_VALUES['participacao']
    assert merged[0]['participacao'] != '1'
    assert merged[0]['participacao'] != '5'


def test_merge_defaults_when_empty():
    row = {
        'teacher': 'Chuck',
        'turma': 'MASTER',
        'student_name': 'Jane',
    }
    merged = merge_roster_for_month([row], {}, '2026-03')
    assert merged[0]['participacao'] == DEFAULT_MONTHLY_VALUES['participacao']


def test_migrate_roster_scores_to_month():
    roster = [_student(participacao='4')]
    store = {}
    changed = migrate_roster_scores_to_month(roster, store, '2026-03')
    assert changed is True
    key = review_key('MASTER', 'Jane', '2026-03')
    assert store[key]['participacao'] == '4'
    assert migrate_roster_scores_to_month(roster, store, '2026-03') is False


def test_store_from_rows_roundtrip():
    rows = [{
        'report_month': '2026-03',
        'turma': 'MASTER',
        'student_id': 'abc',
        'participacao': '5',
    }]
    store = store_from_rows(rows)
    assert len(store) == 1
    assert list(store.values())[0]['participacao'] == '5'


def test_load_save_json(tmp_path):
    from student_reviews import load_monthly_reviews, save_monthly_reviews

    path = tmp_path / 'reviews.json'
    store = {}
    upsert_monthly_review(store, _student(participacao='2'), '2026-04')
    save_monthly_reviews(path, store)
    loaded = load_monthly_reviews(path)
    merged = merge_roster_for_month([_student()], loaded, '2026-04')
    assert merged[0]['participacao'] == '2'
    assert json.loads(path.read_text(encoding='utf-8'))[0]['report_month'] == '2026-04'


def test_extract_roster_fields():
    roster = extract_roster_fields(_student())
    assert roster['student_name'] == 'Jane'
    assert 'participacao' not in roster


def test_apply_upload_row_splits_profile_and_monthly():
    store = {}
    profile = apply_upload_row(_student(participacao='5'), store, '2026-03')
    assert profile.get('participacao', '') == ''
    assert profile['student_name'] == 'Jane'
    merged = merge_roster_for_month([profile], store, '2026-03')
    assert merged[0]['participacao'] == '5'


def test_session_in_month():
    assert session_in_month({'date': '15/03/2026'}, '2026-03') is True
    assert session_in_month({'date': '15/02/2026'}, '2026-03') is False
    assert session_in_month({'date': ''}, '2026-03') is False
    assert session_in_month({'date': 'invalid'}, '2026-03') is False


def test_upsert_sets_report_month_and_scores():
    store = {}
    upsert_monthly_review(store, _student(participacao='3'), '2026-06')
    row = list(store.values())[0]
    assert row['report_month'] == '2026-06'
    assert row['participacao'] == '3'
    assert row['turma'] == 'MASTER'
