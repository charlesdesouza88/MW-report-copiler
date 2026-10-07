"""Participação feedback is picked from ready-made comments; only Recomendações/Observação are typed."""

import re
from html.parser import HTMLParser

import app as web_app
from feedback_options import FEEDBACK_FIELDS, FEEDBACK_OPTIONS, feedback_phrases, is_legacy_feedback
from test_app import _init_teacher_store, _login, _students_csv


class _FormValues(HTMLParser):
    """What a browser would submit for the student form (inputs, selected options, textareas)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.values, self._select, self._textarea, self._in_form = {}, None, None, False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'form' and a.get('id') == 'student-edit-form':
            self._in_form = True
        if not self._in_form:
            return
        if tag == 'input' and a.get('name') and a.get('type') not in ('file', 'checkbox', 'submit'):
            self.values[a['name']] = a.get('value') or ''
        elif tag == 'select' and a.get('name'):
            self._select = a['name']
            self.values.setdefault(a['name'], '')
        elif tag == 'option' and self._select and 'selected' in a:
            self.values[self._select] = a.get('value') or ''
        elif tag == 'textarea' and a.get('name'):
            self._textarea = a['name']
            self.values[a['name']] = ''

    def handle_endtag(self, tag):
        if tag == 'select':
            self._select = None
        elif tag == 'textarea':
            self._textarea = None
        elif tag == 'form':
            self._in_form = False

    def handle_data(self, data):
        if self._textarea:
            self.values[self._textarea] += data


def _client(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "students.csv").write_text(_students_csv(), encoding="utf-8")
    monkeypatch.setattr(web_app, "DATA_DIR", data_dir)
    monkeypatch.setattr(web_app, "OUT_DIR", tmp_path / "output")
    web_app.OUT_DIR.mkdir()
    _init_teacher_store(monkeypatch, data_dir, teacher_name="Chuck")
    client = web_app.app.test_client()
    _login(client, email="teacher@test.local", password="teachpass")
    return client


def _form_values(html):
    parser = _FormValues()
    parser.feed(html)
    return parser.values


def test_each_category_has_unique_neutral_phrases():
    for field in FEEDBACK_FIELDS:
        groups = FEEDBACK_OPTIONS[field]
        assert [g for g, _ in groups] == ['Destaque (4–5)', 'Bom (3)', 'Precisa de atenção (1–2)']
        phrases = feedback_phrases(field)
        assert len(phrases) == len(set(phrases)) >= 9
        for phrase in phrases:
            # Fits any student: no "(a)" placeholders or gendered "o aluno/a aluna".
            assert '(a)' not in phrase and 'o aluno' not in phrase.lower() and 'a aluna' not in phrase.lower()
            assert phrase.endswith('.')
    assert not is_legacy_feedback('feedback_foco', '')
    assert not is_legacy_feedback('feedback_foco', feedback_phrases('feedback_foco')[0])
    assert is_legacy_feedback('feedback_foco', 'Focus')


def test_feedback_fields_are_dropdowns_and_notes_stay_typed(monkeypatch, tmp_path):
    html = _client(monkeypatch, tmp_path).get("/students/0/edit").get_data(as_text=True)
    for field in FEEDBACK_FIELDS:
        assert f'<select name="{field}"' in html
        assert f'<textarea name="{field}"' not in html
        for phrase in feedback_phrases(field):
            assert f'value="{phrase}"' in html
    assert html.count('<optgroup label="Destaque (4–5)">') == 3
    assert '<textarea name="recomendacoes"' in html
    assert '<textarea name="observacao"' in html


def test_feedback_typed_before_the_dropdown_is_kept(monkeypatch, tmp_path):
    """The fixture's old free text ("Good", "Focus", "Team") stays selected, not wiped."""
    html = _client(monkeypatch, tmp_path).get("/students/0/edit").get_data(as_text=True)
    values = _form_values(html)
    assert values['feedback_participacao'] == 'Good'
    assert values['feedback_foco'] == 'Focus'
    assert values['feedback_trabalho_equipe'] == 'Team'
    assert re.search(r'<option value="Good" selected>Texto anterior: Good</option>', html)


def test_chosen_feedback_is_saved_and_shown_again(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    values = _form_values(client.get("/students/0/edit").get_data(as_text=True))
    chosen = {
        'feedback_participacao': feedback_phrases('feedback_participacao')[0],
        'feedback_foco': feedback_phrases('feedback_foco')[-1],
        'feedback_trabalho_equipe': '',
    }
    values.update(chosen)
    values['recomendacoes'] = 'Praticar a escrita em casa.'
    response = client.post("/students/0/autosave", data=values)
    assert response.status_code == 200 and response.get_json()['ok'], response.get_data(as_text=True)

    after = _form_values(client.get("/students/0/edit").get_data(as_text=True))
    for field, phrase in chosen.items():
        assert after[field] == phrase
    assert after['recomendacoes'] == 'Praticar a escrita em casa.'
