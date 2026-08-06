from teacher_chat import (
    KIND_BUG,
    append_message,
    can_access_chat,
    can_resolve_bugs,
    load_messages,
    messages_after,
    open_bug_count,
    resolve_bug,
    save_messages,
    thread_tree,
)


def _user(role='teacher', user_id=2, name='Chuck', email='chuck@test.local'):
    return {
        'id': user_id,
        'role': role,
        'teacher_name': name,
        'email': email,
        'active': True,
    }


def test_append_chat_and_bug(tmp_path):
    rows = []
    msg, err = append_message(rows, _user(), 'Olá equipe')
    assert err is None
    assert msg['kind'] == 'chat'
    assert msg['bug_status'] == ''
    assert len(rows) == 1

    bug, err = append_message(rows, _user(), 'Falta não salva', kind=KIND_BUG)
    assert err is None
    assert bug['kind'] == 'bug'
    assert bug['bug_status'] == 'open'
    assert open_bug_count(rows) == 1

    path = tmp_path / 'teacher_chat.json'
    save_messages(path, rows)
    loaded = load_messages(path)
    assert len(loaded) == 2
    assert loaded[1]['body'] == 'Falta não salva'


def test_reply_requires_parent():
    rows = []
    append_message(rows, _user(), 'Root')
    root_id = rows[0]['id']
    reply, err = append_message(rows, _user(user_id=3, name='Ana'), 'Concordo', parent_id=root_id)
    assert err is None
    assert reply['parent_id'] == root_id
    tree = thread_tree(rows)
    assert len(tree) == 1
    assert len(tree[0]['replies']) == 1

    _, err = append_message(rows, _user(), 'Órfão', parent_id='missing')
    assert err is not None


def test_only_admin_resolves_bugs():
    rows = []
    append_message(rows, _user(), 'Bug X', kind=KIND_BUG)
    bug_id = rows[0]['id']

    assert can_access_chat(_user())
    assert not can_resolve_bugs(_user())
    assert can_resolve_bugs(_user(role='admin', name=''))
    assert can_resolve_bugs(_user(role='superadmin', name=''))

    _, err = resolve_bug(rows, bug_id, _user())
    assert err is not None
    assert rows[0]['bug_status'] == 'open'

    msg, err = resolve_bug(rows, bug_id, _user(role='admin', name='Admin'))
    assert err is None
    assert msg['bug_status'] == 'resolved'
    assert open_bug_count(rows) == 0


def test_messages_after_cursor():
    rows = []
    append_message(rows, _user(), 'A')
    first = rows[0]['id']
    append_message(rows, _user(), 'B')
    newer = messages_after(rows, after_id=first)
    assert len(newer) == 1
    assert newer[0]['body'] == 'B'
    assert messages_after(rows, after_id='nope') == []
