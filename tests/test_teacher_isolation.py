"""One teacher must never read or change another teacher's students, lessons, sessions, classes or reports.

Paula (class SPARK) attacks Chuck's data (class MASTER, student Jane Doe) through every route
a logged-in teacher can reach, including forged identity fields and direct URLs.
"""

import csv
import hashlib
import io
import json

import pytest

import app as web_app
from auth import UserStore
from test_app import _seed_teacher_classes, _students_csv

CHUCK_SECRETS = ("Jane Doe", "Chuck lesson", "Chuck secret topic")
JANE_IDENTITY = {"orig_turma": "MASTER", "orig_student_name": "Jane Doe"}
CHUCK_LESSON = {"orig_turma": "MASTER", "orig_aula_num": "1", "orig_date": "01/09/2026"}
CHUCK_SESSION = {"orig_student_name": "Jane Doe", "orig_turma": "MASTER",
                 "orig_date": "10/09/2026", "orig_session_type": "Reforço"}


@pytest.fixture
def school(monkeypatch, tmp_path):
    data, out = tmp_path / "data", tmp_path / "out"
    data.mkdir()
    out.mkdir()
    header, jane = _students_csv().strip().split("\n")
    bob = jane.replace("Chuck,MASTER,Masters", "Paula,SPARK,Spark").replace("Jane Doe", "Bob Smith")
    (data / "students.csv").write_text(f"{header}\n{jane}\n{bob}\n", encoding="utf-8")
    (data / "lessons.csv").write_text(
        "turma,aula_num,date,licao_conteudo,atividade_extra,habilidades\n"
        "MASTER,1,01/09/2026,Chuck lesson,,\nSPARK,1,02/09/2026,Paula lesson,,\n", encoding="utf-8")
    (data / "extra_sessions.csv").write_text(
        "teacher,student_name,turma,date,horario,turno,session_type,assuntos,observacao,contatado,marcado,realizado\n"
        "Chuck,Jane Doe,MASTER,10/09/2026,,,Reforço,Chuck secret topic,,,,\n", encoding="utf-8")
    _seed_teacher_classes(data, "Chuck", ("MASTER", "Masters", "Terça-feira", "Quinta-feira", "19:00"))
    path = _seed_teacher_classes(data, "Paula", ("SPARK", "Spark", "Segunda-feira", "Quarta-feira", "08:00"))

    store = UserStore(db_store=None, json_path=data / "users.json")
    store.initialize()
    store.ensure_bootstrap_superadmin("admin@test.local", "testpass")
    store.create_teacher("chuck@test.local", "chuckpass", "Chuck")
    store.create_teacher("paula@test.local", "paulapass", "Paula")
    for name, value in dict(user_store=store, DATA_DIR=data, OUT_DIR=out, TEACHER_CLASSES_PATH=path,
                            SNAPSHOTS_PATH=data / "student_snapshots.json",
                            MONTHLY_REVIEWS_PATH=data / "student_monthly_reviews.json", db_store=None).items():
        monkeypatch.setattr(web_app, name, value)

    def login(email, password):
        client = web_app.app.test_client()
        assert client.post("/login", data={"email": email, "password": password}).status_code in (302, 303)
        with client.session_transaction() as sess:
            sess["review_month"] = "2026-09"
        return client

    login("admin@test.local", "testpass").post("/generate", data={"report_month": "2026-09"})
    chuck_id = next(u["id"] for u in store.list_users() if u["email"] == "chuck@test.local")
    login("chuck@test.local", "chuckpass").post("/profile", data={"bio": "Chuck bio", "whatsapp": "111"})
    return {"data": data, "out": out, "paula": login("paula@test.local", "paulapass"), "chuck_id": chuck_id}


def _chuck_state(school):
    """Everything of Chuck's that Paula must not be able to change."""
    data = school["data"]

    def rows(name):
        return list(csv.DictReader(io.StringIO((data / name).read_text(encoding="utf-8"))))

    registry = json.loads((data / "teacher_classes.json").read_text(encoding="utf-8"))
    profiles_path = data / "teacher_profiles.json"
    profiles = json.loads(profiles_path.read_text(encoding="utf-8")) if profiles_path.exists() else []
    return {
        "profile": [p for p in profiles if str(p.get("user_id")) == str(school["chuck_id"])],
        "jane": [r for r in rows("students.csv") if r["turma"] == "MASTER"],
        "lessons": [r for r in rows("lessons.csv") if r["turma"] == "MASTER"],
        "sessions": [r for r in rows("extra_sessions.csv") if r["teacher"] == "Chuck"],
        "classes": [c for c in registry.get("Chuck", []) if c["turma"] == "MASTER"],
        "reports": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in school["out"].glob("MASTER_*")},
    }


def test_teacher_cannot_read_another_teachers_data(school):
    paula, out = school["paula"], school["out"]
    master_reports = sorted(p.name for p in out.glob("MASTER_*"))
    assert master_reports, "fixture should have generated Chuck's reports"

    pages = ["/", "/students", "/lessons", "/extra-sessions", "/reports", "/chat",
             "/upload/download/students", "/upload/download/lessons"]
    for i in range(4):
        pages += [f"/students/{i}/edit", f"/lessons/{i}/edit", f"/extra-sessions/{i}/edit"]
    def assert_no_leak(path, resp):
        assert resp.status_code < 500, (path, resp.status_code)
        body = resp.get_data().decode("utf-8", "replace")  # error pages too
        assert not [s for s in CHUCK_SECRETS if s in body], path

    for path in pages:
        assert_no_leak(path, paula.get(path))

    for name in master_reports:
        for path in (f"/reports/preview/{name}", f"/reports/download/{name}"):
            resp = paula.get(path)
            assert resp.status_code in (403, 404), path
            assert_no_leak(path, resp)
    archive = paula.get("/reports/download-all")
    assert b"MASTER" not in archive.get_data()
    for path in ["/admin/teachers", "/admin/turmas/transfer", "/admin/alunos/transfer"]:
        assert paula.get(path).status_code == 403, path


def test_teacher_cannot_change_another_teachers_data(school):
    paula = school["paula"]
    before = _chuck_state(school)
    assert before["profile"] and before["profile"][0]["bio"] == "Chuck bio"
    jane_form = {**JANE_IDENTITY, "student_name": "Jane Doe", "turma": "MASTER", "teacher": "Chuck", "speaking": "1"}
    for i in range(4):
        paula.post(f"/students/{i}/delete", data=JANE_IDENTITY)
        paula.post(f"/students/{i}/edit", data=jane_form)
        paula.post(f"/students/{i}/autosave", data=jane_form)
        paula.post(f"/students/{i}/photo", data={"clear_photo": "1"})
        paula.post(f"/lessons/{i}/delete", data=CHUCK_LESSON)
        paula.post(f"/lessons/{i}/edit", data={**CHUCK_LESSON, "turma": "MASTER", "aula_num": "1",
                                               "date_picker": "01/09/2026", "licao_conteudo": "hacked"})
        paula.post(f"/extra-sessions/{i}/delete", data=CHUCK_SESSION)
        paula.post(f"/extra-sessions/{i}/edit", data={**CHUCK_SESSION, "student_name": "Jane Doe",
                                                      "turma": "MASTER", "assuntos": "hacked"})
    paula.post("/students/new", data={"student_name": "Intruder Kid", "class_choice": "MASTER",
                                      "turma": "MASTER", "teacher": "Chuck", "nivel": "TEENS 4"})
    paula.post("/lessons/new", data={"turma": "MASTER", "aula_num": "9", "date_picker": "20/09/2026",
                                     "licao_conteudo": "x", "attendance_count": "0"})
    paula.post("/turmas/delete", data={"turma": "MASTER", "teacher": "Chuck"})
    paula.post("/turmas/MASTER/edit", data={"turma_display": "Hacked", "class_weekday_1": "Segunda-feira",
                                            "class_weekday_2": "Quarta-feira", "turma_time_start": "08:00",
                                            "turma_time_end": "09:00", "teacher": "Chuck"})
    header = _students_csv().strip().split("\n")[0]
    paula.post("/upload", data={"students": (io.BytesIO(
        f"{header}\nChuck,MASTER,Masters,TEENS 4,x,Fake Kid,4,4,4,4,4,4,4,4,4,4,4,4,0,,,,,,,\n".encode()), "s.csv")})
    paula.post("/upload/delete/students")
    paula.post("/upload/delete/lessons")
    paula.post("/generate", data={"report_month": "2026-09"})
    paula.post("/admin/alunos/transfer", data={"from_turma": "MASTER", "students": "Jane Doe", "dest": "SPARK"})
    paula.post("/admin/turmas/transfer", data={"turma": "MASTER", "from_teacher": "Chuck", "to_teacher": "Paula"})
    forged_profile = paula.post(f"/profile/{school['chuck_id']}", data={"bio": "hacked", "whatsapp": "000"})
    assert forged_profile.status_code in (403, 404)

    assert _chuck_state(school) == before

    # Control: the same session can still change Paula's own class, so the attacks above were really served.
    paula.post("/lessons/new", data={"turma": "SPARK", "aula_num": "2", "date_picker": "09/09/2026",
                                     "licao_conteudo": "Paula own lesson", "attendance_count": "0"})
    assert "Paula own lesson" in (school["data"] / "lessons.csv").read_text(encoding="utf-8")
