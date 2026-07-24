import json

import app as web_app
from report_periods import student_snapshot_id
from student_reviews import review_key
from student_transfer import (
    students_with_transfer_aliases,
    transfer_students,
    transfers_for_student,
)

from test_app import _init_user_store, _login, _seed_teacher_classes


def _student(name="Jane Doe", turma="TEENS_1", teacher="Chuck"):
    return {
        "teacher": teacher,
        "turma": turma,
        "turma_display": turma.replace("_", " ").title(),
        "nivel": "TEENS 1",
        "horario": "Ter 19:00",
        "student_name": name,
    }


def _monthly_row(turma, name, month, **fields):
    sid = student_snapshot_id(turma, name)
    row = {
        "report_month": month,
        "turma": turma,
        "student_id": sid,
        "faltas": "1",
        "speaking": "4",
    }
    row.update(fields)
    return f"{turma}|{sid}|{month}", row


def _dest(turma="TEENS_2", teacher="Paula"):
    return {
        "turma": turma,
        "turma_display": "Teens 2",
        "horario": "Qua 18:00",
        "teacher": teacher,
    }


def test_transfer_moves_reviews_snapshots_and_roster():
    students = [_student(), _student(name="Other Kid")]
    monthly_store = dict([
        _monthly_row("TEENS_1", "Jane Doe", "2025-05"),
        _monthly_row("TEENS_1", "Jane Doe", "2025-06", faltas="2"),
        _monthly_row("TEENS_1", "Other Kid", "2025-06"),
    ])
    old_sid = student_snapshot_id("TEENS_1", "Jane Doe")
    snapshot_store = {
        f"TEENS_1|{old_sid}|2025-05": {
            "report_month": "2025-05",
            "turma": "TEENS_1",
            "student_id": old_sid,
            "composite_score": 4,
        },
    }
    extras = [{
        "teacher": "Chuck",
        "student_name": "Jane Doe (TEENS_1)",
        "turma": "TEENS_1",
        "session_type": "Reforço",
    }]
    log = []

    summary, err = transfer_students(
        students, ["Jane Doe"], "TEENS_1", _dest(),
        monthly_store, snapshot_store, extras, log,
        when="2025-07-01",
    )

    assert err is None
    assert summary["count"] == 1

    # Roster follows the destination turma and teacher.
    jane = next(s for s in students if s["student_name"] == "Jane Doe")
    assert jane["turma"] == "TEENS_2"
    assert jane["teacher"] == "Paula"
    assert jane["turma_display"] == "Teens 2"

    # Monthly reviews rekeyed to the new identity; other students untouched.
    new_key_may = review_key("TEENS_2", "Jane Doe", "2025-05")
    new_key_jun = review_key("TEENS_2", "Jane Doe", "2025-06")
    assert monthly_store[new_key_may]["faltas"] == "1"
    assert monthly_store[new_key_jun]["faltas"] == "2"
    assert monthly_store[new_key_jun]["turma"] == "TEENS_2"
    assert review_key("TEENS_1", "Jane Doe", "2025-05") not in monthly_store
    assert review_key("TEENS_1", "Other Kid", "2025-06") in monthly_store

    # Snapshots rekeyed so month-over-month trends keep working.
    new_sid = student_snapshot_id("TEENS_2", "Jane Doe")
    snap = snapshot_store[f"TEENS_2|{new_sid}|2025-05"]
    assert snap["composite_score"] == 4
    assert snap["turma"] == "TEENS_2"
    assert f"TEENS_1|{old_sid}|2025-05" not in snapshot_store

    # Extra sessions move together.
    assert extras[0]["turma"] == "TEENS_2"
    assert extras[0]["teacher"] == "Paula"

    # Transfer is logged for traceability.
    assert log[0]["from_turma"] == "TEENS_1"
    assert log[0]["to_turma"] == "TEENS_2"
    assert log[0]["months_moved"] == 2
    assert log[0]["date"] == "2025-07-01"


def test_transfer_rejects_same_name_in_destination():
    students = [_student(), _student(turma="TEENS_2", teacher="Paula")]
    summary, err = transfer_students(
        students, ["Jane Doe"], "TEENS_1", _dest(),
        {}, {}, [], [],
    )
    assert summary is None
    assert "mesmo nome" in err


def test_transfers_for_student_follows_chain_from_current_turma():
    log = [
        {"student_name": "Jane Doe", "from_turma": "TEENS_1", "to_turma": "TEENS_2"},
        {"student_name": "Jane Doe", "from_turma": "KIDS_1", "to_turma": "KIDS_2"},
        {"student_name": "Jane Doe", "from_turma": "TEENS_2", "to_turma": "TEENS_3"},
    ]
    chain = transfers_for_student(log, "Jane Doe", current_turma="TEENS_3")
    assert [(e["from_turma"], e["to_turma"]) for e in chain] == [
        ("TEENS_1", "TEENS_2"),
        ("TEENS_2", "TEENS_3"),
    ]


def test_students_with_transfer_aliases_adds_old_identity():
    students = [_student(turma="TEENS_2", teacher="Paula")]
    log = [{
        "student_name": "Jane Doe",
        "from_turma": "TEENS_1",
        "to_turma": "TEENS_2",
    }]
    rows = students_with_transfer_aliases(students, log)
    alias = [r for r in rows if r.get("_transfer_alias")]
    assert len(alias) == 1
    assert alias[0]["turma"] == "TEENS_1"
    assert alias[0]["teacher"] == "Paula"
    assert alias[0]["student_name"] == "Jane Doe"


def _students_csv_two_turmas():
    return (
        "teacher,turma,turma_display,nivel,horario,student_name,participacao,comportamento,speaking,listening,foco,writing,reading,gramatica,trabalho_equipe,organizacao,pontualidade,respeito_regras,faltas,missed_aulas,aula_extra,feedback_participacao,feedback_foco,feedback_trabalho_equipe,recomendacoes,observacao\n"
        "Chuck,TEENS_1,Teens 1,TEENS 1,Ter 19:00,Jane Doe,,,,,,,,,,,,,,,,,,,,\n"
        "Chuck,TEENS_1,Teens 1,TEENS 1,Ter 19:00,Bob Roe,,,,,,,,,,,,,,,,,,,,\n"
    )


def test_transfer_route_moves_student_and_history(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    out_dir = tmp_path / "output"
    data_dir.mkdir()
    out_dir.mkdir()
    (data_dir / "students.csv").write_text(_students_csv_two_turmas(), encoding="utf-8")
    (data_dir / "lessons.csv").write_text(
        "turma,aula_num,date,licao_conteudo,atividade_extra,habilidades\n"
        "TEENS_1,1,05/05,Lesson 1,,\n",
        encoding="utf-8",
    )
    key, row = _monthly_row("TEENS_1", "Jane Doe", "2025-05", faltas="3")
    (data_dir / "student_monthly_reviews.json").write_text(
        json.dumps([row]), encoding="utf-8",
    )

    _init_user_store(monkeypatch, data_dir)
    monkeypatch.setattr(web_app, "DATA_DIR", data_dir)
    monkeypatch.setattr(web_app, "OUT_DIR", out_dir)
    monkeypatch.setattr(web_app, "SNAPSHOTS_PATH", data_dir / "student_snapshots.json")
    classes_path = _seed_teacher_classes(
        data_dir,
        "Paula",
        ("TEENS_2", "Teens 2", "Quarta-feira", "Sexta-feira", "18:00"),
    )
    monkeypatch.setattr(web_app, "TEACHER_CLASSES_PATH", classes_path)

    client = web_app.app.test_client()
    _login(client)

    page = client.get("/admin/alunos/transfer?from_turma=TEENS_1")
    assert page.status_code == 200
    assert "Jane Doe" in page.get_data(as_text=True)

    response = client.post(
        "/admin/alunos/transfer",
        data={
            "action": "transfer",
            "from_turma": "TEENS_1",
            "dest": "Paula||TEENS_2",
            "students": ["Jane Doe"],
        },
    )
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "transferido" in html

    # Roster persisted with the new turma/teacher.
    roster = (data_dir / "students.csv").read_text(encoding="utf-8")
    assert "Paula,TEENS_2" in roster
    assert "Chuck,TEENS_1,Teens 1,TEENS 1,Ter 19:00,Bob Roe" in roster

    # Monthly review history moved to the new identity.
    reviews = json.loads(
        (data_dir / "student_monthly_reviews.json").read_text(encoding="utf-8"),
    )
    assert len(reviews) == 1
    assert reviews[0]["turma"] == "TEENS_2"
    assert reviews[0]["student_id"] == student_snapshot_id("TEENS_2", "Jane Doe")
    assert reviews[0]["faltas"] == "3"

    # Transfer log written.
    log = json.loads((data_dir / "student_transfers.json").read_text(encoding="utf-8"))
    assert log[0]["student_name"] == "Jane Doe"
    assert log[0]["from_turma"] == "TEENS_1"
    assert log[0]["to_turma"] == "TEENS_2"

    # Edit page shows the enrollment history.
    listing = client.get("/students?turma=TEENS_2")
    assert "Jane Doe" in listing.get_data(as_text=True)
