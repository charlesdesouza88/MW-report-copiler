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
    assert 'name="faltas" value="1"' in edit_html
    assert 'name="missed_aulas" value="1"' in edit_html


def test_manual_faltas_without_missed_aulas_persists(monkeypatch, tmp_path):
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
    assert 'Faltas</span><strong>3</strong>' in students_html

    edit_html = client.get("/students/0/edit?month=2026-05").get_data(as_text=True)
    assert 'name="faltas" value="3"' in edit_html

