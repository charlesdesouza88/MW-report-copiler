"""Tests for login history helpers and contact deep links."""

from login_events import (
    append_login,
    contact_email_for_user,
    events_for_user,
    events_newest_first,
    format_logged_at,
    last_login_by_user_id,
    load_events,
    mailto_href,
    save_events,
    whatsapp_digits,
    whatsapp_href,
)


def _user(user_id=2, email='teacher@test.local', role='teacher', name='Chuck'):
    return {
        'id': user_id,
        'email': email,
        'role': role,
        'teacher_name': name,
        'active': True,
    }


def test_whatsapp_digits_adds_brazil_country_code():
    assert whatsapp_digits('11999998888') == '5511999998888'
    assert whatsapp_digits('(11) 99999-8888') == '5511999998888'
    assert whatsapp_digits('5511999998888') == '5511999998888'
    assert whatsapp_digits('0011999998888') == '5511999998888'
    assert whatsapp_digits('') == ''


def test_whatsapp_and_mailto_hrefs():
    assert whatsapp_href('11999998888') == 'https://wa.me/5511999998888'
    assert 'text=Ola' in whatsapp_href('11999998888', text='Ola')
    assert mailto_href('a@b.com') == 'mailto:a@b.com'
    assert 'subject=' in mailto_href('a@b.com', subject='Oi')
    assert mailto_href('') == ''
    assert whatsapp_href('') == ''


def test_contact_email_prefers_profile():
    user = _user()
    assert contact_email_for_user(user, {'contact_email': 'prof@school.com'}) == 'prof@school.com'
    assert contact_email_for_user(user, {}) == 'teacher@test.local'


def test_append_login_and_last_login(tmp_path):
    rows = []
    first = append_login(rows, _user())
    assert first is not None
    assert len(rows) == 1
    second = append_login(rows, _user())
    assert second is not None
    assert len(rows) == 2
    assert first['id'] != second['id']

    latest = last_login_by_user_id(rows)
    assert latest[2]['id'] == second['id']
    history = events_for_user(rows, 2)
    assert len(history) == 2
    assert history[0]['id'] == second['id']

    path = tmp_path / 'login_events.json'
    save_events(path, rows)
    loaded = load_events(path)
    assert len(loaded) == 2
    assert events_newest_first(loaded, limit=1)[0]['id'] == second['id']


def test_format_logged_at_empty_and_iso():
    assert format_logged_at('') == 'Nunca'
    label = format_logged_at('2026-08-10T18:30:00Z')
    assert '/' in label
    assert ':' in label
