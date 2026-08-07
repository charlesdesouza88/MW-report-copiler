import base64

from teacher_profiles import (
    can_edit_profile,
    encode_photo,
    get_or_empty,
    load_profiles,
    photo_data_url,
    save_profiles,
    upsert_profile,
)


def _actor(role='teacher', user_id=2):
    return {'id': user_id, 'role': role, 'active': True}


def test_upsert_and_load_profile(tmp_path):
    rows = []
    profile, err = upsert_profile(
        rows,
        2,
        bio='Professor de Teens',
        phone='1133334444',
        whatsapp='11999998888',
        contact_email='chuck@school.com',
        specialty='Teens',
    )
    assert err is None
    assert profile['bio'] == 'Professor de Teens'
    assert profile['whatsapp'] == '11999998888'
    assert len(rows) == 1

    path = tmp_path / 'teacher_profiles.json'
    save_profiles(path, rows)
    loaded = load_profiles(path)
    assert loaded[0]['specialty'] == 'Teens'
    assert get_or_empty(loaded, 2)['phone'] == '1133334444'
    assert get_or_empty(loaded, 99)['bio'] == ''


def test_photo_encode_and_permissions():
    jpeg = b'\xff\xd8\xff\xe0' + b'\x00' * 40
    mime, b64, err = encode_photo(jpeg)
    assert err is None
    assert mime == 'image/jpeg'
    assert base64.b64decode(b64)[:3] == b'\xff\xd8\xff'

    bad, _, err = encode_photo(b'not-an-image')
    assert bad == ''
    assert err is not None

    assert can_edit_profile(_actor('teacher', 2), 2)
    assert not can_edit_profile(_actor('teacher', 2), 3)
    assert can_edit_profile(_actor('admin', 1), 3)

    rows = []
    upsert_profile(rows, 2, bio='x', photo_mime=mime, photo_base64=b64)
    assert photo_data_url(rows[0]).startswith('data:image/jpeg;base64,')


def test_clear_photo():
    rows = []
    jpeg = b'\xff\xd8\xff\xe0' + b'\x00' * 20
    mime, b64, err = encode_photo(jpeg)
    assert err is None
    upsert_profile(rows, 2, bio='Hi', photo_mime=mime, photo_base64=b64)
    assert rows[0]['photo_base64']
    upsert_profile(rows, 2, bio='Hi', clear_photo=True)
    assert rows[0]['photo_base64'] == ''
    assert rows[0]['photo_mime'] == ''
