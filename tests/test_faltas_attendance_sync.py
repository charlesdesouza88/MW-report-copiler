"""Lesson attendance must update Faltas on the Alunos list and edit form."""

import app as web_app
from auth import UserStore


def _students_csv():
    return (
        "teacher,turma,turma_display,nivel,horario,student_name,participacao,comportamento,speaking,listening,foco,writing,reading,gramatica,trabalho_equipe,organizacao,pontualidade,respeito_regras,faltas,missed_aulas,aula_extra,feedback_participacao,feedback_foco,feedback_trabalho_equipe,recomendacoes,observacao\n"
        "Chuck,MASTER,Masters,Adults Book 4,Tue 19:00,Jane Doe,4,3,4,5,4,3,4,2,3,3,3,3,0,,,Good,Focus,Team,Practice speaking,\n"
    )


def test_absent_lesson_updates_student_faltas(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "students.csv").write_text(_students_csv(), encoding="utf-8")
    (data_dir / "teacher_classes.json").write_text("{}", encoding="utf-8")
    (data_dir / "lessons.csv").write_text(
        "turma,aula_num,date,licao_conteudo,atividade_extra,habilidades\n"
        "MASTER,1,15/05/2026,Lesson 1,,\n",
        encoding="utf-8",
    )

    store = UserStore(db_store=None, json_path=data_dir / "users.json")
    store.initialize()
    store.create_teacher("chuck@test.local", "pass1234", "Chuck")

    monkeypatch.setattr(web_app, "DATA_DIR", data_dir)
    monkeypatch.setattr(web_app, "db_store", None)
    monkeypatch.setattr(web_app, "OUT_DIR", tmp_path / "output")
    web_app.OUT_DIR.mkdir()
    monkeypatch.setattr(web_app, "user_store", store)
    monkeypatch.setattr(web_app, "_monthly_migration_done", True)

    client = web_app.app.test_client()
    client.post("/login", data={"email": "chuck@test.local", "password": "pass1234"})

    response = client.post(
        "/lessons/0/edit",
        data={
            "turma": "MASTER",
            "aula_num": "1",
            "date": "15/05/2026",
            "licao_conteudo": "Lesson 1",
            "atividade_extra": "",
            "habilidades": "",
            "attendance_count": "1",
            "attendance_student_0": "Jane Doe",
            "attendance_status_0": "absent",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200

    students_html = client.get("/students?month=2026-05").get_data(as_text=True)
    assert 'Faltas</span><strong>1</strong>' in students_html

    edit_html = client.get("/students/0/edit?month=2026-05").get_data(as_text=True)
    assert 'data-presence="faltas">1<' in edit_html
    assert 'Faltou: aula 1' in edit_html


def test_typed_faltas_are_ignored_attendance_decides(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "students.csv").write_text(_students_csv(), encoding="utf-8")
    (data_dir / "teacher_classes.json").write_text("{}", encoding="utf-8")
    (data_dir / "lessons.csv").write_text(
        "turma,aula_num,date,licao_conteudo,atividade_extra,habilidades\n"
        "MASTER,1,15/05/2026,Lesson 1,,\n",
        encoding="utf-8",
    )

    store = UserStore(db_store=None, json_path=data_dir / "users.json")
    store.initialize()
    store.create_teacher("chuck@test.local", "pass1234", "Chuck")

    monkeypatch.setattr(web_app, "DATA_DIR", data_dir)
    monkeypatch.setattr(web_app, "db_store", None)
    monkeypatch.setattr(web_app, "OUT_DIR", tmp_path / "output")
    web_app.OUT_DIR.mkdir()
    monkeypatch.setattr(web_app, "user_store", store)
    monkeypatch.setattr(web_app, "_monthly_migration_done", True)

    client = web_app.app.test_client()
    client.post("/login", data={"email": "chuck@test.local", "password": "pass1234"})

    client.post(
        "/lessons/0/edit",
        data={
            "turma": "MASTER",
            "aula_num": "1",
            "date": "15/05/2026",
            "licao_conteudo": "Lesson 1",
            "atividade_extra": "",
            "habilidades": "",
            "attendance_count": "1",
            "attendance_student_0": "Jane Doe",
            "attendance_status_0": "present",
        },
        follow_redirects=True,
    )

    save = client.post(
        "/students/0/edit?month=2026-05",
        data={
            "teacher": "Chuck",
            "turma": "MASTER",
            "turma_display": "Masters",
            "nivel": "Adults Book 4",
            "horario": "Tue 19:00",
            "student_name": "Jane Doe",
            "participacao": "4",
            "comportamento": "3",
            "speaking": "4",
            "listening": "5",
            "foco": "4",
            "writing": "3",
            "reading": "4",
            "gramatica": "2",
            "trabalho_equipe": "3",
            "organizacao": "3",
            "pontualidade": "3",
            "respeito_regras": "3",
            "faltas": "3",
            "missed_aulas": "",
            "aula_extra": "",
            "feedback_participacao": "Good",
            "feedback_foco": "Focus",
            "feedback_trabalho_equipe": "Team",
            "recomendacoes": "Practice speaking",
            "observacao": "",
        },
        follow_redirects=True,
    )
    assert save.status_code == 200

    students_html = client.get("/students?month=2026-05").get_data(as_text=True)
    assert 'Faltas</span><strong>0</strong>' in students_html  # present in the logged lesson

    edit_html = client.get("/students/0/edit?month=2026-05").get_data(as_text=True)
    assert 'data-presence="faltas">0<' in edit_html


def test_list_and_edit_show_attendance_faltas_over_stale_saved_value(monkeypatch, tmp_path):
    """A stale saved count (1) gives way to the attendance taken in Aulas (2 absences)."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "students.csv").write_text(_students_csv(), encoding="utf-8")
    (data_dir / "teacher_classes.json").write_text("{}", encoding="utf-8")
    (data_dir / "lessons.csv").write_text(
        "turma,aula_num,date,licao_conteudo,atividade_extra,habilidades\n"
        "MASTER,1,10/05/2026,Lesson 1,,\n"
        "MASTER,2,17/05/2026,Lesson 2,,\n",
        encoding="utf-8",
    )
    (data_dir / "lesson_attendance.csv").write_text(
        "turma,aula_num,student_name,status\n"
        "MASTER,1,Jane Doe,absent\n"
        "MASTER,2,Jane Doe,absent\n",
        encoding="utf-8",
    )
    reviews_path = data_dir / "student_monthly_reviews.json"
    reviews_path.write_text(
        '[{"report_month":"2026-05","turma":"MASTER","student_id":"6a03573506b6a182",'
        '"student_name":"Jane Doe","faltas":"1","missed_aulas":"","participacao":"4",'
        '"comportamento":"3","speaking":"4","listening":"5","foco":"4","writing":"3",'
        '"reading":"4","gramatica":"2","trabalho_equipe":"3","organizacao":"3",'
        '"pontualidade":"3","respeito_regras":"3","aula_extra":"",'
        '"feedback_participacao":"","feedback_foco":"","feedback_trabalho_equipe":"",'
        '"recomendacoes":"","observacao":""}]',
        encoding="utf-8",
    )

    store = UserStore(db_store=None, json_path=data_dir / "users.json")
    store.initialize()
    store.create_teacher("chuck@test.local", "pass1234", "Chuck")

    monkeypatch.setattr(web_app, "DATA_DIR", data_dir)
    monkeypatch.setattr(web_app, "db_store", None)
    monkeypatch.setattr(web_app, "OUT_DIR", tmp_path / "output")
    web_app.OUT_DIR.mkdir()
    monkeypatch.setattr(web_app, "user_store", store)
    monkeypatch.setattr(web_app, "MONTHLY_REVIEWS_PATH", reviews_path)
    monkeypatch.setattr(web_app, "_monthly_migration_done", True)

    client = web_app.app.test_client()
    client.post("/login", data={"email": "chuck@test.local", "password": "pass1234"})

    students_html = client.get("/students?month=2026-05").get_data(as_text=True)
    assert 'Faltas</span><strong>2</strong>' in students_html

    edit_html = client.get("/students/0/edit?month=2026-05").get_data(as_text=True)
    assert 'data-presence="faltas">2<' in edit_html
    assert 'Faltou: aula 1, 2' in edit_html



def test_form_shows_late_arrivals_and_autosave_cannot_change_faltas(monkeypatch, tmp_path):
    """Presence is read-only on the student form: it comes from each lesson's attendance."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "students.csv").write_text(_students_csv(), encoding="utf-8")
    (data_dir / "teacher_classes.json").write_text("{}", encoding="utf-8")
    (data_dir / "lessons.csv").write_text(
        "turma,aula_num,date,licao_conteudo,atividade_extra,habilidades\n"
        "MASTER,1,10/05/2026,Lesson 1,,\n"
        "MASTER,2,17/05/2026,Lesson 2,,\n",
        encoding="utf-8",
    )
    (data_dir / "lesson_attendance.csv").write_text(
        "turma,aula_num,student_name,status\n"
        "MASTER,1,Jane Doe,absent\n"
        "MASTER,2,Jane Doe,tardy\n",
        encoding="utf-8",
    )
    reviews_path = data_dir / "student_monthly_reviews.json"
    store = UserStore(db_store=None, json_path=data_dir / "users.json")
    store.initialize()
    store.create_teacher("chuck@test.local", "pass1234", "Chuck")
    monkeypatch.setattr(web_app, "DATA_DIR", data_dir)
    monkeypatch.setattr(web_app, "db_store", None)
    monkeypatch.setattr(web_app, "OUT_DIR", tmp_path / "output")
    web_app.OUT_DIR.mkdir()
    monkeypatch.setattr(web_app, "user_store", store)
    monkeypatch.setattr(web_app, "MONTHLY_REVIEWS_PATH", reviews_path)
    monkeypatch.setattr(web_app, "_monthly_migration_done", True)

    client = web_app.app.test_client()
    client.post("/login", data={"email": "chuck@test.local", "password": "pass1234"})
    with client.session_transaction() as sess:
        sess["review_month"] = "2026-05"

    html = client.get("/students/0/edit").get_data(as_text=True)
    assert 'data-presence="faltas">1<' in html
    assert "Faltou: aula 1" in html and "Atrasou: aula 2" in html
    assert 'name="faltas"' not in html and 'name="missed_aulas"' not in html

    saved = client.post("/students/0/autosave", data={
        "orig_turma": "MASTER", "orig_student_name": "Jane Doe",
        "teacher": "Chuck", "turma": "MASTER", "student_name": "Jane Doe",
        "speaking": "5", "faltas": "9", "missed_aulas": "1,2,3,4,5,6,7,8,9",
    }, headers={"Accept": "application/json"})
    assert saved.get_json()["ok"], saved.get_data(as_text=True)
    import json
    may = [r for r in json.loads(reviews_path.read_text()) if r["report_month"] == "2026-05"]
    assert may[0]["speaking"] == "5"
    assert may[0]["faltas"] == "1" and may[0]["missed_aulas"] == "1"
