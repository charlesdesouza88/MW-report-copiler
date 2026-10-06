"""Rows are addressed by list position; forms carry orig_* identity so a shifted list never hits the wrong row."""

import csv
import html as H
import io
import re

from test_app import _init_user_store, _login, _students_csv

import app as web_app
from extra_sessions import EXTRA_SESSION_FIELDS

LESSONS = (
    "turma,aula_num,date,licao_conteudo,atividade_extra,habilidades\n"
    "MASTER,1,01/09/2026,Lição 1,,\n"
    "MASTER,2,03/09/2026,Lição 2,,\n"
    "MASTER,3,08/09/2026,Lição 3,,\n"
)


def _setup(monkeypatch, tmp_path, names=("Ana Souza", "Bruno Lima", "Carla Dias")):
    data_dir = tmp_path / "data"
    out_dir = tmp_path / "output"
    data_dir.mkdir()
    out_dir.mkdir()
    header, row = _students_csv().strip().split("\n")
    (data_dir / "students.csv").write_text(
        header + "\n" + "\n".join(row.replace("Jane Doe", n) for n in names) + "\n", encoding="utf-8",
    )
    (data_dir / "lessons.csv").write_text(LESSONS, encoding="utf-8")
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=EXTRA_SESSION_FIELDS)
    writer.writeheader()
    for name in names:
        writer.writerow({"teacher": "Chuck", "student_name": name, "turma": "MASTER",
                         "date": "10/09/2026", "session_type": "Reforço", "assuntos": f"Revisão {name}"})
    (data_dir / "extra_sessions.csv").write_text(buf.getvalue(), encoding="utf-8")
    _init_user_store(monkeypatch, data_dir)
    monkeypatch.setattr(web_app, "DATA_DIR", data_dir)
    monkeypatch.setattr(web_app, "OUT_DIR", out_dir)
    monkeypatch.setattr(web_app, "SNAPSHOTS_PATH", data_dir / "student_snapshots.json")
    monkeypatch.setattr(web_app, "MONTHLY_REVIEWS_PATH", data_dir / "student_monthly_reviews.json")
    monkeypatch.setattr(web_app, "db_store", None)
    return data_dir


def _clients():
    a, b = web_app.app.test_client(), web_app.app.test_client()
    _login(a)
    _login(b)
    for c in (a, b):
        with c.session_transaction() as sess:
            sess["review_month"] = "2026-09"
    return a, b


def _form(page_html, label, action_part):
    """Action and hidden fields of the first `action_part` form after `label` on the page."""
    start = page_html.index(label)
    match = re.search(r'<form[^>]*action="([^"]*' + re.escape(action_part) + r'[^"]*)".*?</form>',
                      page_html[start:], re.DOTALL)
    fields = {k: H.unescape(v) for k, v in re.findall(r'name="([^"]+)" value="([^"]*)"', match.group(0))}
    return H.unescape(match.group(1)), fields


def _rows(path, key):
    return [r[key] for r in csv.DictReader(io.StringIO(path.read_text(encoding="utf-8")))]


def test_locate_by_identity():
    locate = web_app._locate_by_identity
    rows = [{"turma": "M", "student_name": "Ana"}, {"turma": "M", "student_name": "Bruno"}]
    form = {"orig_turma": "M", "orig_student_name": "Bruno"}
    fields = web_app.STUDENT_IDENTITY
    assert locate(rows, 1, form, fields, required=True) == 1      # still in place
    assert locate(rows, 2, form, fields, required=True) == 1      # list shifted
    assert locate(rows[:1], 1, form, fields, required=True) is None  # gone
    assert locate(rows, 0, {}, fields, required=True) is None     # destructive, no identity
    assert locate(rows, 0, {}, fields, required=False) == 0       # edit from an old page
    assert locate(rows, 5, {}, fields, required=False) is None


def test_student_delete_hits_the_student_on_screen_after_list_shift(monkeypatch, tmp_path):
    data_dir = _setup(monkeypatch, tmp_path)
    a, b = _clients()
    page_a = a.get("/students").get_data(as_text=True)
    bruno_action, bruno_fields = _form(page_a, "Bruno Lima", "/delete")

    action, fields = _form(b.get("/students").get_data(as_text=True), "Ana Souza", "/delete")
    b.post(action, data=fields)
    assert _rows(data_dir / "students.csv", "student_name") == ["Bruno Lima", "Carla Dias"]

    a.post(bruno_action, data=bruno_fields)
    assert _rows(data_dir / "students.csv", "student_name") == ["Carla Dias"]


def test_student_delete_refuses_when_student_already_gone(monkeypatch, tmp_path):
    data_dir = _setup(monkeypatch, tmp_path)
    a, b = _clients()
    page_a = a.get("/students").get_data(as_text=True)
    action, fields = _form(page_a, "Carla Dias", "/delete")
    b.post(*_form(b.get("/students").get_data(as_text=True), "Carla Dias", "/delete")[:1],
           data=_form(b.get("/students").get_data(as_text=True), "Carla Dias", "/delete")[1])

    response = a.post(action, data=fields, follow_redirects=True)
    assert _rows(data_dir / "students.csv", "student_name") == ["Ana Souza", "Bruno Lima"]
    assert "A lista mudou" in response.get_data(as_text=True)


def test_student_delete_without_identity_is_refused(monkeypatch, tmp_path):
    """A page loaded before this fix posts no orig_* fields: never guess on a delete."""
    data_dir = _setup(monkeypatch, tmp_path)
    a, _ = _clients()
    a.post("/students/0/delete")
    assert _rows(data_dir / "students.csv", "student_name") == ["Ana Souza", "Bruno Lima", "Carla Dias"]


def test_lesson_edit_saves_onto_the_lesson_that_was_opened(monkeypatch, tmp_path):
    data_dir = _setup(monkeypatch, tmp_path)
    a, b = _clients()
    edit_html = a.get("/lessons/2/edit").get_data(as_text=True)     # Lição 3, 08/09
    fields = dict(re.findall(r'name="(orig_[a-z_]+)" value="([^"]*)"', edit_html))
    assert fields == {"orig_turma": "MASTER", "orig_aula_num": "3", "orig_date": "08/09/2026"}

    action, del_fields = _form(b.get("/lessons").get_data(as_text=True), "01/09/2026", "/delete")
    b.post(action, data=del_fields)                                  # lesson 1 removed → list shifts

    a.post("/lessons/2/edit", data={**fields, "turma": "MASTER", "aula_num": "3",
                                    "date_picker": "08/09/2026", "licao_conteudo": "Lição 3 editada",
                                    "habilidades": "", "attendance_count": "0"})
    lessons = list(csv.DictReader(io.StringIO((data_dir / "lessons.csv").read_text(encoding="utf-8"))))
    assert [(r["aula_num"], r["licao_conteudo"]) for r in lessons] == [("2", "Lição 2"), ("3", "Lição 3 editada")]


def test_lesson_delete_after_list_shift(monkeypatch, tmp_path):
    data_dir = _setup(monkeypatch, tmp_path)
    a, b = _clients()
    target = _form(a.get("/lessons").get_data(as_text=True), "03/09/2026", "/delete")
    b.post(*_form(b.get("/lessons").get_data(as_text=True), "01/09/2026", "/delete")[:1],
           data=_form(b.get("/lessons").get_data(as_text=True), "01/09/2026", "/delete")[1])
    a.post(target[0], data=target[1])
    assert _rows(data_dir / "lessons.csv", "aula_num") == ["3"]


def test_extra_session_delete_after_list_shift(monkeypatch, tmp_path):
    data_dir = _setup(monkeypatch, tmp_path)
    a, b = _clients()
    target = _form(a.get("/extra-sessions").get_data(as_text=True), "Revisão Bruno Lima", "/delete")
    first = _form(b.get("/extra-sessions").get_data(as_text=True), "Revisão Ana Souza", "/delete")
    b.post(first[0], data=first[1])
    a.post(target[0], data=target[1])
    subjects = _rows(data_dir / "extra_sessions.csv", "assuntos")
    assert "Revisão Bruno Lima" not in subjects and "Revisão Ana Souza" not in subjects
    assert "Revisão Carla Dias" in subjects
