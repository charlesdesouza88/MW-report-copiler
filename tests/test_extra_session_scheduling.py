"""Reforço/reposição flow: a teacher flags a student, the coordination assigns a teacher and a date."""

import csv
import html as html_lib
import io
import re

import app as web_app
from test_teacher_isolation import school  # noqa: F401  (pytest fixture: Chuck owns Jane/MASTER, Paula owns Bob/SPARK)

JANE = {"orig_turma": "MASTER", "orig_student_name": "Jane Doe"}


def _client(email, password):
    client = web_app.app.test_client()
    assert client.post("/login", data={"email": email, "password": password}).status_code in (302, 303)
    with client.session_transaction() as sess:
        sess["review_month"] = "2026-09"
    return client


def _sessions(school):
    text = (school["data"] / "extra_sessions.csv").read_text(encoding="utf-8")
    return list(csv.DictReader(io.StringIO(text)))


def _jane_reposicao(school):
    rows = [r for r in _sessions(school) if r["session_type"] == "Reposição" and r["turma"] == "MASTER"]
    assert len(rows) == 1, rows
    return rows[0]


def _flag_jane(chuck, value="Reposição"):
    resp = chuck.post("/students/0/autosave", data={
        **JANE, "teacher": "Chuck", "turma": "MASTER", "student_name": "Jane Doe", "aula_extra": value,
    }, headers={"Accept": "application/json"})
    assert resp.get_json()["ok"], resp.get_data(as_text=True)


def _panel(page):
    if 'id="aguardando-agendamento"' not in page:
        return ""
    return page.split('id="aguardando-agendamento"', 1)[1].split("filter-panel", 1)[0]


def _awaiting(page, student="Jane Doe"):
    """(index, identity hidden fields) of the student's awaiting row, as a browser would post them."""
    for idx, block in re.findall(r'data-awaiting="(\d+)">(.*?)(?=data-awaiting="|\Z)', _panel(page), re.S):
        if student in block:
            ident = {k: html_lib.unescape(v) for k, v in
                     re.findall(r'<input type="hidden" name="(orig_[a-z_]+)" value="([^"]*)"', block)}
            return int(idx), ident
    raise AssertionError(f"{student} not awaiting")


def _schedule(admin, teacher="Paula", date="2026-10-20", horario=""):
    idx, ident = _awaiting(admin.get("/extra-sessions").get_data(as_text=True))
    return admin.post(f"/extra-sessions/{idx}/schedule", data={
        **ident, "assigned_teacher": teacher, "date_picker": date, "horario": horario})


def test_flagged_student_waits_then_coordination_schedules(school):
    chuck = _client("chuck@test.local", "chuckpass")
    admin = _client("admin@test.local", "testpass")
    paula = school["paula"]
    _flag_jane(chuck)

    teacher_page = chuck.get("/extra-sessions").get_data(as_text=True)
    panel = _panel(teacher_page)
    assert "Aguardando agendamento (1)" in panel and "Aguardando a coordenação" in panel
    assert "Jane Doe" in panel and "Bob Smith" not in panel  # a teacher only sees their own students
    assert 'name="assigned_teacher"' not in panel

    admin_panel = _panel(admin.get("/extra-sessions").get_data(as_text=True))
    assert "Jane Doe" in admin_panel and "Bob Smith" in admin_panel  # the coordination sees everyone

    idx, ident = _awaiting(admin.get("/extra-sessions").get_data(as_text=True))
    forged = chuck.post(f"/extra-sessions/{idx}/schedule",
                        data={**ident, "assigned_teacher": "Chuck", "date_picker": "2026-10-20"})
    assert forged.status_code == 403  # teachers cannot schedule
    assert _jane_reposicao(school)["date"] == ""

    assert _schedule(admin, horario="15:30").status_code == 302
    row = _jane_reposicao(school)
    assert (row["teacher"], row["assigned_teacher"], row["date"], row["horario"], row["marcado"]) == \
        ("Chuck", "Paula", "20/10/2026", "15:30", "OK")
    assert "agendado com Prof. Paula em 20/10/2026 às 15:30" in admin.get("/extra-sessions").get_data(as_text=True)

    # The student's teacher and the class teacher both see it, and it left their waiting lists.
    for client in (chuck, paula):
        page = client.get("/extra-sessions").get_data(as_text=True)
        assert "20/10/2026" in page and "Jane Doe" not in _panel(page)
    assert "Aula com Prof. Paula" in chuck.get("/extra-sessions").get_data(as_text=True)

    # Chuck saving Jane again keeps the appointment (no reset, no duplicate request).
    _flag_jane(chuck)
    row = _jane_reposicao(school)
    assert row["assigned_teacher"] == "Paula" and row["date"] == "20/10/2026"


def test_schedule_requires_teacher_and_date(school):
    admin = _client("admin@test.local", "testpass")
    _flag_jane(_client("chuck@test.local", "chuckpass"))
    _schedule(admin, teacher="", date="2026-10-20")
    _schedule(admin, teacher="Paula", date="")
    assert _jane_reposicao(school)["date"] == ""
    assert "Escolha o professor e a data" in admin.get("/extra-sessions").get_data(as_text=True)


def test_class_teacher_can_record_the_class_but_not_take_over_or_delete(school):
    chuck = _client("chuck@test.local", "chuckpass")
    admin = _client("admin@test.local", "testpass")
    paula = school["paula"]
    _flag_jane(chuck)
    _schedule(admin)

    page = paula.get("/extra-sessions").get_data(as_text=True)
    edit_links = sorted(set(int(i) for i in re.findall(r'/extra-sessions/(\d+)/edit', page)))
    row = _jane_reposicao(school)
    ident = {f"orig_{k}": row[k] for k in ("student_name", "turma", "date", "session_type")}
    for i in edit_links:  # whichever index is Jane's, the forged owner/assignment must not stick
        paula.post(f"/extra-sessions/{i}/edit", data={
            **ident, "student_name": row["student_name"], "turma": "MASTER", "teacher": "Paula",
            "assigned_teacher": "Somebody Else", "session_type": "Reposição", "date_picker": "2026-10-20",
            "realizado": "OK",
        })
    row = _jane_reposicao(school)
    assert (row["teacher"], row["assigned_teacher"], row["realizado"]) == ("Chuck", "Paula", "OK")

    for i in edit_links:
        paula.post(f"/extra-sessions/{i}/delete", data={**ident, "orig_date": row["date"]})
    _jane_reposicao(school)  # still there: only Chuck or the coordination may delete it
