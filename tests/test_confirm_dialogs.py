"""Delete buttons must really ask first: their confirm() handler has to be valid JavaScript.

`|tojson` output inside a double-quoted attribute ends the attribute at its first quote, the handler
throws, and the browser submits the delete without asking. Names with apostrophes must also work.
"""

import json
from html.parser import HTMLParser

import app as web_app
from test_app import _init_teacher_store, _login, _students_csv

TRICKY_NAME = "Ana D'Ávila \"Nina\""


class _Handlers(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.handlers = []

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if name == "onsubmit" and value and "confirm(" in value:
                self.handlers.append(value)


def _handlers(html):
    parser = _Handlers()
    parser.feed(html)
    return parser.handlers


def _client(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "students.csv").write_text(_students_csv().replace("Jane Doe", f'"{TRICKY_NAME.replace(chr(34), chr(34) * 2)}"'),
                                           encoding="utf-8")
    (data_dir / "lessons.csv").write_text(
        "turma,aula_num,date,licao_conteudo,atividade_extra,habilidades\nMASTER,1,01/09/2026,Colors,,\n",
        encoding="utf-8")
    monkeypatch.setattr(web_app, "DATA_DIR", data_dir)
    monkeypatch.setattr(web_app, "OUT_DIR", tmp_path / "output")
    web_app.OUT_DIR.mkdir()
    _init_teacher_store(monkeypatch, data_dir, teacher_name="Chuck")
    client = web_app.app.test_client()
    _login(client, email="teacher@test.local", password="teachpass")
    return client


def test_delete_confirmations_are_valid_javascript(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    messages = []
    for path in ["/students", "/lessons", "/"]:
        handlers = _handlers(client.get(path).get_data(as_text=True))
        assert handlers, path
        for handler in handlers:
            handler = handler.strip().rstrip(";")
            assert handler.startswith("return confirm(") and handler.endswith(")"), (path, handler)
            arg = handler[len("return confirm("):-1]
            if arg.startswith('"'):
                messages.append(json.loads(arg))  # must be one complete JS string literal
            else:
                assert arg.startswith("'") and arg.endswith("'") and "'" not in arg[1:-1], (path, handler)
    assert f"Excluir {TRICKY_NAME}?" in messages
    assert any(m.startswith("Excluir a turma «Masters»") for m in messages)
    assert any(m.startswith("Excluir aula 1") for m in messages)
