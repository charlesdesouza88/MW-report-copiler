"""Reforço/reposição flow: a teacher flags a student, the coordination assigns a teacher and a date."""

import csv
import html as html_lib
import io
import re

import app as web_app
from extra_sessions import EXTRA_SESSION_FIELDS
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
    return page.split('id="aguardando-agendamento"', 1)[1].split("<!-- /pedidos -->", 1)[0]


def _awaiting(page, student="Jane Doe"):
    """(index, identity hidden fields) of the student's awaiting row, as a browser would post them."""
    for idx, block in re.findall(r'data-awaiting="(\d+)"[^>]*>(.*?)(?=data-awaiting="|\Z)', _panel(page), re.S):
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
    assert "Aula com <strong>Prof. Paula</strong>" in chuck.get("/extra-sessions").get_data(as_text=True)

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


def _ident(row):
    return {f"orig_{k}": row[k] for k in ("student_name", "turma", "date", "session_type")}


def test_class_teacher_records_result_and_missed_class_goes_back_to_coordination(school):
    chuck = _client("chuck@test.local", "chuckpass")
    admin = _client("admin@test.local", "testpass")
    paula = school["paula"]
    _flag_jane(chuck)
    _schedule(admin, date="2026-10-20")
    row = _jane_reposicao(school)
    page = paula.get("/extra-sessions").get_data(as_text=True)
    idx = int(re.search(r'data-scheduled="(\d+)"', page).group(1))
    assert "Registrar resultado" in page

    # Student did not come: stays open, flagged for rescheduling.
    paula.post(f"/extra-sessions/{idx}/outcome", data={**_ident(row), "result": "NAO"})
    row = _jane_reposicao(school)
    assert row["realizado"] == "NÃO"
    assert "Faltou · reagendar" in admin.get("/extra-sessions").get_data(as_text=True)
    assert "A coordenação vai reagendar" in chuck.get("/extra-sessions").get_data(as_text=True)

    # Coordination reschedules: the missed mark is cleared.
    page = admin.get("/extra-sessions").get_data(as_text=True)
    a_idx = int(re.search(r'data-scheduled="(\d+)"', page).group(1))
    admin.post(f"/extra-sessions/{a_idx}/schedule", data={**_ident(row), "assigned_teacher": "Paula",
                                                          "date_picker": "2026-10-27"})
    row = _jane_reposicao(school)
    assert (row["date"], row["realizado"]) == ("27/10/2026", "")

    # Done, with what was worked on; the student's flag is cleared so no new request appears.
    paula.post(f"/extra-sessions/{idx}/outcome", data={**_ident(row), "result": "OK",
                                                        "assuntos": "Unit 3 past simple"})
    row = _jane_reposicao(school)
    assert (row["realizado"], row["assuntos"]) == ("OK", "Unit 3 past simple")
    page = chuck.get("/extra-sessions").get_data(as_text=True)
    assert "Jane Doe" not in _panel(page) and "Unit 3 past simple" in page.split('id="concluidas"', 1)[1]


def test_unrelated_teacher_cannot_record_result(school):
    chuck = _client("chuck@test.local", "chuckpass")
    admin = _client("admin@test.local", "testpass")
    _flag_jane(chuck)
    _schedule(admin, teacher="Chuck")
    row = _jane_reposicao(school)
    for i in range(4):
        school["paula"].post(f"/extra-sessions/{i}/outcome", data={**_ident(row), "result": "OK"})
    assert _jane_reposicao(school)["realizado"] == ""


def test_cancelling_a_request_does_not_bring_it_back(school):
    chuck = _client("chuck@test.local", "chuckpass")
    _flag_jane(chuck)
    page = chuck.get("/extra-sessions").get_data(as_text=True)
    action = re.search(r'action="(/extra-sessions/\d+/delete)"', _panel(page)).group(1)
    assert "Cancelar pedido" in _panel(page)
    chuck.post(action, data=_ident(_jane_reposicao(school)))
    chuck.get("/extra-sessions")  # page load reconciles flagged students
    assert not [r for r in _sessions(school) if r["turma"] == "MASTER" and r["session_type"] == "Reposição"]
    student = chuck.get("/students/0/edit").get_data(as_text=True)
    assert '<option value="Reposição" selected' not in student


def test_request_form_uses_roster_and_blocks_duplicates(school):
    chuck = _client("chuck@test.local", "chuckpass")
    form = chuck.get("/extra-sessions/new").get_data(as_text=True)
    assert 'value="MASTER|Jane Doe"' in form and "Bob Smith" not in form  # only own students

    resp = chuck.post("/extra-sessions/new", data={"student_pick": "SPARK|Bob Smith", "session_type": "Reforço"})
    assert resp.status_code == 400  # not Chuck's student
    chuck.post("/extra-sessions/new", data={"student_pick": "MASTER|Jane Doe", "session_type": "Nivelamento",
                                            "motivo": "Past simple"})
    chuck.post("/extra-sessions/new", data={"student_pick": "MASTER|Jane Doe", "session_type": "Nivelamento"})
    rows = [r for r in _sessions(school) if r["session_type"] == "Nivelamento"]
    assert len(rows) == 1
    assert (rows[0]["student_name"], rows[0]["turma"], rows[0]["teacher"], rows[0]["motivo"]) == \
        ("Jane Doe (MASTER)", "MASTER", "Chuck", "Past simple")
    page = chuck.get("/extra-sessions").get_data(as_text=True)
    assert "Past simple" in _panel(page) and "já tem um pedido de Nivelamento em aberto" in page


def test_edit_form_hides_internal_marker_and_keeps_request_linked(school):
    chuck = _client("chuck@test.local", "chuckpass")
    _flag_jane(chuck)
    idx, _ = _awaiting(chuck.get("/extra-sessions").get_data(as_text=True))
    edit = chuck.get(f"/extra-sessions/{idx}/edit").get_data(as_text=True)
    assert "__auto_aula_extra__" not in edit
    row = _jane_reposicao(school)
    chuck.post(f"/extra-sessions/{idx}/edit", data={**_ident(row), "student_name": row["student_name"],
                                                     "turma": "MASTER", "session_type": "Reposição",
                                                     "motivo": "Faltou às aulas 3 e 4", "observacao": ""})
    row = _jane_reposicao(school)
    assert row["observacao"] == "__auto_aula_extra__" and row["motivo"] == "Faltou às aulas 3 e 4"


def _dashboard_count(client):
    return int(re.search(r'data-extra-requested="(\d+)"', client.get("/").get_data(as_text=True)).group(1))


def test_dashboard_shows_pending_requests(school):
    chuck = _client("chuck@test.local", "chuckpass")
    admin = _client("admin@test.local", "testpass")
    paula = school["paula"]
    _flag_jane(chuck, value="")  # the fixture starts Jane flagged; begin from no request
    base_admin, base_chuck, base_paula = _dashboard_count(admin), _dashboard_count(chuck), _dashboard_count(paula)
    _flag_jane(chuck)  # counted even before anyone opens the Reforço page
    assert (_dashboard_count(admin), _dashboard_count(chuck), _dashboard_count(paula)) == \
        (base_admin + 1, base_chuck + 1, base_paula)
    _schedule(admin)
    assert (_dashboard_count(admin), _dashboard_count(chuck)) == (base_admin, base_chuck)
    assert "aguardando agendamento" in admin.get("/").get_data(as_text=True)
    assert "aguardando a coordenação" in chuck.get("/").get_data(as_text=True)


def test_result_only_for_scheduled_classes(school):
    chuck = _client("chuck@test.local", "chuckpass")
    _flag_jane(chuck)
    idx, _ = _awaiting(chuck.get("/extra-sessions").get_data(as_text=True))
    chuck.post(f"/extra-sessions/{idx}/outcome", data={**_ident(_jane_reposicao(school)), "result": "OK"})
    row = _jane_reposicao(school)
    assert row["realizado"] == "" and row["date"] == ""  # still a request, not "done"
    assert "Só é possível registrar o resultado de aulas agendadas" in chuck.get("/extra-sessions").get_data(as_text=True)


def _add_session_rows(school, *rows):
    path = school["data"] / "extra_sessions.csv"
    existing = _sessions(school)
    fields = EXTRA_SESSION_FIELDS
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in existing + [dict({f: "" for f in fields}, **r) for r in rows]:
            writer.writerow(row)


def test_renamed_student_keeps_one_request(school):
    chuck = _client("chuck@test.local", "chuckpass")
    _flag_jane(chuck)
    chuck.post("/students/0/autosave", data={
        **JANE, "teacher": "Chuck", "turma": "MASTER", "student_name": "Jane Doe Smith", "aula_extra": "Reposição",
    }, headers={"Accept": "application/json"})
    chuck.get("/extra-sessions")
    reps = [r for r in _sessions(school) if r["session_type"] == "Reposição" and r["turma"] == "MASTER"]
    assert [r["student_name"] for r in reps] == ["Jane Doe Smith (MASTER)"]


def test_requests_follow_the_roster_and_unknown_names_are_flagged(school):
    # Imported with the wrong teacher and no class, as on the live site; plus a name nobody has.
    _add_session_rows(school,
                      {"teacher": "Paula", "student_name": "JANE DOE", "turma": "", "session_type": "Nivelamento"},
                      {"teacher": "Paula", "student_name": "Ghost Kid (SPARK)", "turma": "SPARK",
                       "session_type": "Reforço"})
    chuck = _client("chuck@test.local", "chuckpass")
    admin = _client("admin@test.local", "testpass")
    page = admin.get("/extra-sessions").get_data(as_text=True)
    row = next(r for r in _sessions(school) if r["session_type"] == "Nivelamento")
    assert (row["student_name"], row["turma"], row["teacher"]) == ("Jane Doe (MASTER)", "MASTER", "Chuck")
    assert "Jane Doe" in _panel(chuck.get("/extra-sessions").get_data(as_text=True))  # now with her teacher
    ghost = page.split("Ghost Kid", 1)[1].split("</article>", 1)[0]
    assert "Aluno não encontrado no cadastro" in ghost
    assert page.count("Aluno não encontrado no cadastro") == 1
    assert any(r["student_name"] == "Ghost Kid (SPARK)" for r in _sessions(school))  # flagged, never deleted
