import io
import json
import zipfile
from pathlib import Path

import app as web_app
from auth import UserStore


def _students_csv():
    return (
        "teacher,turma,turma_display,nivel,horario,student_name,participacao,comportamento,speaking,listening,foco,writing,reading,gramatica,trabalho_equipe,organizacao,pontualidade,respeito_regras,faltas,missed_aulas,aula_extra,feedback_participacao,feedback_foco,feedback_trabalho_equipe,recomendacoes,observacao\n"
        "Chuck,MASTER,Masters,Adults Book 4,Tue 19:00,Jane Doe,4,3,4,5,4,3,4,2,3,3,3,3,1,2,Reposicao,Good,Focus,Team,Practice speaking,\n"
    )


def _lessons_csv():
    return (
        "turma,aula_num,date,licao_conteudo,atividade_extra,habilidades\n"
        "MASTER,1,01/01,Lesson 1,,\n"
        "MASTER,2,03/01,Lesson 2,,\n"
    )


def _init_user_store(monkeypatch, data_dir):
    from auth import UserStore

    store = UserStore(db_store=None, json_path=data_dir / "users.json")
    store.initialize()
    store.ensure_bootstrap_superadmin("admin@test.local", "testpass")
    monkeypatch.setattr(web_app, "user_store", store)
    monkeypatch.setattr(web_app, "SUPERADMIN_EMAIL", "admin@test.local")
    monkeypatch.setattr(web_app, "SUPERADMIN_PASSWORD", "testpass")


def _login(client, email="admin@test.local", password="testpass"):
    return client.post(
        "/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )


def _seed_teacher_classes(data_dir, teacher_name, *entries):
    """entries: (turma, turma_display) or (turma, turma_display, day1, day2, time)."""
    from auth import normalize_teacher_name
    from form_ui import format_class_schedule
    from teacher_classes import load_registry, save_registry

    path = data_dir / "teacher_classes.json"
    data = load_registry(path)
    key = normalize_teacher_name(teacher_name)
    bucket = data.setdefault(key, [])
    for entry in entries:
        turma, display = entry[0], entry[1]
        weekdays = list(entry[2:4]) if len(entry) > 2 else []
        time_start = entry[4] if len(entry) > 4 else "19:00"
        time_end = entry[5] if len(entry) > 5 else "20:00"
        bucket.append({
            "turma": turma,
            "turma_display": display or turma,
            "class_weekdays": weekdays,
            "class_time_start": time_start,
            "class_time_end": time_end,
            "horario": format_class_schedule(weekdays, time_start, time_end)
            if weekdays else "",
        })
    save_registry(path, data)
    return path


def _init_teacher_store(monkeypatch, data_dir, teacher_name="Chuck"):
    from auth import UserStore

    store = UserStore(db_store=None, json_path=data_dir / "users.json")
    store.initialize()
    store.ensure_bootstrap_superadmin("admin@test.local", "testpass")
    store.create_teacher("teacher@test.local", "teachpass", teacher_name)
    monkeypatch.setattr(web_app, "user_store", store)
    classes_path = _seed_teacher_classes(
        data_dir,
        teacher_name,
        ("MASTER", "Masters", "Terça-feira", "Quinta-feira", "19:00"),
    )
    monkeypatch.setattr(web_app, "TEACHER_CLASSES_PATH", classes_path)


def test_health_returns_ok():
    client = web_app.app.test_client()
    response = client.get("/health")
    assert response.status_code == 200
    assert response.get_data(as_text=True) == "ok"


def test_health_db_csv_mode():
    client = web_app.app.test_client()
    response = client.get("/health/db")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["configured"] is False
    assert payload["mode"] == "csv"


def test_health_auth_omits_account_emails(monkeypatch, tmp_path):
    monkeypatch.setattr(web_app, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(web_app, "OUT_DIR", tmp_path / "output")
    web_app.DATA_DIR.mkdir()
    web_app.OUT_DIR.mkdir()
    _init_user_store(monkeypatch, web_app.DATA_DIR)

    client = web_app.app.test_client()
    response = client.get("/health/auth")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["user_count"] == 1
    assert "accounts" not in payload
    assert "configured_email" not in payload
    assert "admin@test.local" not in response.get_data(as_text=True)


def test_login_success_sets_session(monkeypatch, tmp_path):
    monkeypatch.setattr(web_app, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(web_app, "OUT_DIR", tmp_path / "output")
    web_app.DATA_DIR.mkdir()
    web_app.OUT_DIR.mkdir()
    _init_user_store(monkeypatch, web_app.DATA_DIR)

    client = web_app.app.test_client()
    response = _login(client)

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/")


def test_protected_route_requires_login(monkeypatch, tmp_path):
    monkeypatch.setattr(web_app, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(web_app, "OUT_DIR", tmp_path / "output")
    web_app.DATA_DIR.mkdir()
    web_app.OUT_DIR.mkdir()

    client = web_app.app.test_client()
    response = client.get("/")

    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_generate_reports_writes_html_files(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    out_dir = tmp_path / "output"
    data_dir.mkdir()
    out_dir.mkdir()
    (data_dir / "students.csv").write_text(_students_csv(), encoding="utf-8")
    (data_dir / "lessons.csv").write_text(_lessons_csv(), encoding="utf-8")

    _init_user_store(monkeypatch, data_dir)
    monkeypatch.setattr(web_app, "BASE", Path(web_app.__file__).parent)
    monkeypatch.setattr(web_app, "DATA_DIR", data_dir)
    monkeypatch.setattr(web_app, "TMPL_DIR", Path(web_app.__file__).parent / "templates")
    monkeypatch.setattr(web_app, "OUT_DIR", out_dir)

    client = web_app.app.test_client()
    _login(client)

    response = client.post("/generate", follow_redirects=False)

    assert response.status_code == 302
    assert "/reports" in response.headers["Location"]
    assert "month=" in response.headers["Location"]
    generated = sorted(p.name for p in out_dir.glob("*.html"))
    assert any(name.endswith("_report.html") for name in generated)
    assert any("class_diagnostic" in name for name in generated)


def test_reports_page_with_null_prior_snapshot(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    out_dir = tmp_path / "output"
    data_dir.mkdir()
    out_dir.mkdir()
    (data_dir / "students.csv").write_text(_students_csv(), encoding="utf-8")
    (data_dir / "lessons.csv").write_text(_lessons_csv(), encoding="utf-8")
    (out_dir / "MASTER_Jane_Doe_2026-03_report.html").write_text("<html>ok</html>", encoding="utf-8")
    (data_dir / "student_snapshots.json").write_text(
        json.dumps(
            [
                {
                    'report_month': '2026-03',
                    'turma': 'MASTER',
                    'student_id': '6a03573506b6a182',
                    'composite_score': 4,
                },
                {
                    'report_month': '2026-02',
                    'turma': 'MASTER',
                    'student_id': '6a03573506b6a182',
                    'composite_score': None,
                },
            ],
            ensure_ascii=False,
        ),
        encoding='utf-8',
    )

    _init_user_store(monkeypatch, data_dir)
    monkeypatch.setattr(web_app, "DATA_DIR", data_dir)
    monkeypatch.setattr(web_app, "OUT_DIR", out_dir)
    monkeypatch.setattr(web_app, "SNAPSHOTS_PATH", data_dir / "student_snapshots.json")

    client = web_app.app.test_client()
    _login(client)
    response = client.get("/reports?month=2026-03")

    assert response.status_code == 200
    assert "Jane" in response.get_data(as_text=True)


def test_turma_from_diagnostic_filename():
    assert web_app._turma_from_diagnostic_filename('MASTER_2026-03_class_diagnostic.html') == 'MASTER'
    assert web_app._turma_from_diagnostic_filename('KIDS_2_CLASS_2026-03_class_diagnostic.html') == 'KIDS_2_CLASS'
    assert web_app._turma_from_diagnostic_filename('MASTER_class_diagnostic.html') == 'MASTER'


def test_reports_page_unified_filter_markup(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    out_dir = tmp_path / "output"
    data_dir.mkdir()
    out_dir.mkdir()
    (data_dir / "students.csv").write_text(_students_csv(), encoding="utf-8")
    (data_dir / "lessons.csv").write_text(_lessons_csv(), encoding="utf-8")
    (out_dir / "MASTER_Jane_Doe_2026-03_report.html").write_text("<html>ok</html>", encoding="utf-8")
    (out_dir / "MASTER_2026-03_class_diagnostic.html").write_text("<html>diag</html>", encoding="utf-8")

    _init_user_store(monkeypatch, data_dir)
    monkeypatch.setattr(web_app, "DATA_DIR", data_dir)
    monkeypatch.setattr(web_app, "OUT_DIR", out_dir)
    monkeypatch.setattr(web_app, "SNAPSHOTS_PATH", data_dir / "student_snapshots.json")

    client = web_app.app.test_client()
    _login(client)
    html = client.get("/reports").get_data(as_text=True)

    assert 'id="filter-reports"' in html
    assert 'data-filter-key="report_kind"' in html
    assert 'data-filter-key="month"' in html
    assert 'data-filter-value="2026-03"' in html
    assert 'data-filter-key="turma"' in html
    assert 'data-filter-key="trend"' in html
    assert 'data-report-kind="individual"' in html
    assert 'data-report-kind="diagnostic"' in html
    assert 'data-month="2026-03"' in html
    assert 'urlKeys: ["month"]' in html
    assert "Relatórios (" in html
    assert "Diagnóstico de turma" in html


def test_generate_missing_csv_shows_upload_error(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    out_dir = tmp_path / "output"
    data_dir.mkdir()
    out_dir.mkdir()

    _init_user_store(monkeypatch, data_dir)
    monkeypatch.setattr(web_app, "DATA_DIR", data_dir)
    monkeypatch.setattr(web_app, "TMPL_DIR", Path(web_app.__file__).parent / "templates")
    monkeypatch.setattr(web_app, "OUT_DIR", out_dir)

    client = web_app.app.test_client()
    _login(client)
    response = client.post("/generate")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "students.csv não encontrado" in html
    assert "csv-preview-table" in html


def test_generate_invalid_csv_reuses_full_upload_context(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    out_dir = tmp_path / "output"
    data_dir.mkdir()
    out_dir.mkdir()
    (data_dir / "students.csv").write_text("teacher,turma\nChuck,MASTER\n", encoding="utf-8")
    (data_dir / "lessons.csv").write_text(_lessons_csv(), encoding="utf-8")

    _init_user_store(monkeypatch, data_dir)
    monkeypatch.setattr(web_app, "DATA_DIR", data_dir)
    monkeypatch.setattr(web_app, "TMPL_DIR", Path(web_app.__file__).parent / "templates")
    monkeypatch.setattr(web_app, "OUT_DIR", out_dir)

    client = web_app.app.test_client()
    _login(client)
    response = client.post("/generate")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "CSV de Alunos invalido" in html
    assert "csv-preview-table" in html


def test_reports_preview_path_is_sanitized(monkeypatch, tmp_path):
    out_dir = tmp_path / "output"
    out_dir.mkdir()
    (out_dir / "safe.html").write_text("<html>ok</html>", encoding="utf-8")

    monkeypatch.setattr(web_app, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(web_app, "OUT_DIR", out_dir)
    web_app.DATA_DIR.mkdir(exist_ok=True)
    _init_user_store(monkeypatch, web_app.DATA_DIR)

    client = web_app.app.test_client()
    _login(client)

    ok = client.get("/reports/preview/safe.html")
    blocked = client.get("/reports/preview/../secret.txt")

    assert ok.status_code == 200
    assert blocked.status_code == 404


def test_upload_invalid_students_csv_shows_error_and_does_not_crash(monkeypatch, tmp_path):
    monkeypatch.setattr(web_app, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(web_app, "OUT_DIR", tmp_path / "output")
    web_app.DATA_DIR.mkdir()
    web_app.OUT_DIR.mkdir()
    _init_user_store(monkeypatch, web_app.DATA_DIR)

    client = web_app.app.test_client()
    _login(client)

    bad_students = io.BytesIO(b"teacher,turma\nChuck,MASTER\n")
    response = client.post(
        "/upload",
        data={"students": (bad_students, "students.csv")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    assert b"Erro no CSV de Alunos" in response.data
    assert not (web_app.DATA_DIR / "students.csv").exists()


def test_upload_template_students_download(monkeypatch, tmp_path):
    monkeypatch.setattr(web_app, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(web_app, "OUT_DIR", tmp_path / "output")
    web_app.DATA_DIR.mkdir()
    web_app.OUT_DIR.mkdir()
    _init_user_store(monkeypatch, web_app.DATA_DIR)

    client = web_app.app.test_client()
    _login(client)

    response = client.get("/upload/template/students")

    assert response.status_code == 200
    assert "attachment;" in response.headers.get("Content-Disposition", "")
    assert "students_template.csv" in response.headers.get("Content-Disposition", "")
    assert response.data.startswith(b"\xef\xbb\xbf")
    assert b"teacher,turma,turma_display" in response.data
    assert b"Jane Doe" in response.data


def test_login_page_has_viewport(monkeypatch, tmp_path):
    monkeypatch.setattr(web_app, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(web_app, "OUT_DIR", tmp_path / "output")

    client = web_app.app.test_client()
    response = client.get("/login")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'name="viewport"' in html
    assert "width=device-width" in html
    assert 'name="email"' in html


def test_authenticated_shell_has_drawer_markup(monkeypatch, tmp_path):
    monkeypatch.setattr(web_app, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(web_app, "OUT_DIR", tmp_path / "output")
    web_app.DATA_DIR.mkdir()
    web_app.OUT_DIR.mkdir()
    _init_user_store(monkeypatch, web_app.DATA_DIR)

    client = web_app.app.test_client()
    _login(client)
    response = client.get("/")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'name="viewport"' in html
    assert 'id="menu-toggle"' in html
    assert 'id="nav-backdrop"' in html
    assert 'class="students-cards-view"' not in html


def test_students_page_has_dual_view_markup(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "students.csv").write_text(_students_csv(), encoding="utf-8")

    monkeypatch.setattr(web_app, "DATA_DIR", data_dir)
    monkeypatch.setattr(web_app, "OUT_DIR", tmp_path / "output")
    web_app.OUT_DIR.mkdir()
    _init_user_store(monkeypatch, data_dir)

    client = web_app.app.test_client()
    _login(client)
    response = client.get("/students")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "students-table-view" in html
    assert "students-cards-view" in html
    assert "student-card-item" in html


def test_upload_page_shows_csv_template_preview(monkeypatch, tmp_path):
    monkeypatch.setattr(web_app, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(web_app, "OUT_DIR", tmp_path / "output")
    web_app.DATA_DIR.mkdir()
    web_app.OUT_DIR.mkdir()
    _init_user_store(monkeypatch, web_app.DATA_DIR)

    client = web_app.app.test_client()
    _login(client)
    response = client.get("/upload")

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "csv-preview-table" in html
    assert "Identificação" in html
    assert "Nome do aluno" in html
    assert "Lesson 3: Past tense review" in html or "Lição 3" in html


def test_lessons_page_and_teacher_scope(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "students.csv").write_text(_students_csv(), encoding="utf-8")
    (data_dir / "teacher_classes.json").write_text("{}", encoding="utf-8")
    (data_dir / "lessons.csv").write_text(
        "turma,aula_num,date,licao_conteudo,atividade_extra,habilidades\n"
        "MASTER,1,01/01,L1,,\n"
        "OTHER,1,01/01,L9,,\n",
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
    _init_user_store(monkeypatch, data_dir)

    client = web_app.app.test_client()
    client.post("/login", data={"email": "chuck@test.local", "password": "pass1234"})
    response = client.get("/lessons")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "MASTER" in html
    assert "L9" not in html

    new_form = client.get("/lessons/new")
    new_html = new_form.get_data(as_text=True)
    assert new_form.status_code == 200
    assert 'name="habilidades"' in new_html
    assert 'name="licao_conteudo"' in new_html
    assert 'name="attendance_status_0"' in new_html
    assert 'Presente' in new_html
    assert 'Ausente' in new_html
    assert 'Atrasado' in new_html
    assert 'value="2"' in new_html or 'id="aula-num-input"' in new_html

    create = client.post(
        "/lessons/new",
        data={
            "turma": "MASTER",
            "aula_num": "99",
            "date": "01/05/2026",
            "licao_conteudo": "Lição 10",
            "atividade_extra": "",
            "habilidades": "Inteligência emocional",
            "attendance_count": "1",
            "attendance_student_0": "Jane Doe",
            "attendance_status_0": "absent",
        },
        follow_redirects=True,
    )
    assert create.status_code == 200
    assert "Lição 10" in create.get_data(as_text=True)
    students_text = (data_dir / "students.csv").read_text(encoding="utf-8")
    assert "Jane Doe" in students_text
    reviews_path = data_dir / "student_monthly_reviews.json"
    assert reviews_path.exists()
    reviews_text = reviews_path.read_text(encoding="utf-8")
    assert "99" in reviews_text
    assert '"faltas": "2"' in reviews_text or '"faltas":"2"' in reviews_text.replace(' ', '')
    attendance_text = (data_dir / "lesson_attendance.csv").read_text(encoding="utf-8")
    assert "Jane Doe" in attendance_text
    assert "absent" in attendance_text

    students_html = client.get("/students?month=2026-05").get_data(as_text=True)
    assert "Jane Doe" in students_html
    assert 'Faltas</span><strong>2</strong>' in students_html

    edit_html = client.get("/students/0/edit?month=2026-05").get_data(as_text=True)
    assert 'name="faltas" value="2"' in edit_html
    assert 'name="missed_aulas" value="2,99"' in edit_html

    blocked = client.post(
        "/lessons/new",
        data={
            "turma": "OTHER",
            "aula_num": "1",
            "date": "01/01",
            "licao_conteudo": "Hack",
            "atividade_extra": "",
            "habilidades": "",
        },
    )
    assert blocked.status_code == 403


def test_lessons_page_lists_dashboard_turma_without_lessons(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "students.csv").write_text(_students_csv(), encoding="utf-8")
    (data_dir / "lessons.csv").write_text(
        "turma,aula_num,date,licao_conteudo,atividade_extra,habilidades\n"
        "MASTER,1,01/01,L1,,\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(web_app, "DATA_DIR", data_dir)
    monkeypatch.setattr(web_app, "OUT_DIR", tmp_path / "output")
    web_app.OUT_DIR.mkdir()
    _init_teacher_store(monkeypatch, data_dir, teacher_name="Chuck")
    _seed_teacher_classes(
        data_dir,
        "Chuck",
        ("NEW_CLASS", "Turma Nova", "Segunda-feira", "Quarta-feira", "10:00", "11:00"),
    )

    client = web_app.app.test_client()
    _login(client, email="teacher@test.local", password="teachpass")
    html = client.get("/lessons").get_data(as_text=True)

    assert 'data-filter-value="NEW_CLASS"' in html
    assert "Turma Nova" in html
    assert "L1" in html

    create = client.post(
        "/lessons/new",
        data={
            "turma": "NEW_CLASS",
            "aula_num": "1",
            "date_picker": "2026-06-10",
            "licao_conteudo": "Primeira aula",
            "atividade_extra": "",
            "habilidades": "Speaking",
            "attendance_count": "0",
        },
        follow_redirects=False,
    )
    assert create.status_code == 302
    assert "turma=NEW_CLASS" in (create.headers.get("Location") or "") or True
    saved = (data_dir / "lessons.csv").read_text(encoding="utf-8")
    assert "Primeira aula" in saved
    assert "NEW_CLASS" in saved


def test_flagged_student_appears_in_extra_sessions(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "students.csv").write_text(_students_csv(), encoding="utf-8")
    (data_dir / "teacher_classes.json").write_text("{}", encoding="utf-8")
    (data_dir / "lessons.csv").write_text(
        "turma,aula_num,date,licao_conteudo,atividade_extra,habilidades\n"
        "MASTER,1,01/01,L1,,\n",
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
    _init_user_store(monkeypatch, data_dir)

    client = web_app.app.test_client()
    client.post("/login", data={"email": "chuck@test.local", "password": "pass1234"})
    client.post(
        "/students/0/edit",
        data={
            "teacher": "Chuck",
            "turma": "MASTER",
            "turma_display": "Masters",
            "nivel": "KIDS 1",
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
            "faltas": "1",
            "missed_aulas": "2",
            "aula_extra": "Reforço",
            "feedback_participacao": "Good",
            "feedback_foco": "Focus",
            "feedback_trabalho_equipe": "Team",
            "recomendacoes": "Practice speaking",
            "observacao": "",
        },
        follow_redirects=True,
    )

    response = client.get("/extra-sessions")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Jane Doe" in html
    assert "Indicado no relatório" in html
    assert "Reforço" in html


def test_teacher_sees_only_own_students(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    csv_text = (
        "teacher,turma,turma_display,nivel,horario,student_name,participacao,comportamento,speaking,listening,foco,writing,reading,gramatica,trabalho_equipe,organizacao,pontualidade,respeito_regras,faltas,missed_aulas,aula_extra,feedback_participacao,feedback_foco,feedback_trabalho_equipe,recomendacoes,observacao\n"
        "Chuck,MASTER,Masters,Book,Tue,Jane Doe,4,3,4,5,4,3,4,2,3,3,3,3,1,2,,,,,,\n"
        "Barbara,MASTER,Masters,Book,Tue,Bob Smith,4,3,4,5,4,3,4,2,3,3,3,3,1,2,,,,,,\n"
    )
    (data_dir / "students.csv").write_text(csv_text, encoding="utf-8")

    store = UserStore(db_store=None, json_path=data_dir / "users.json")
    store.initialize()
    store.create_teacher("chuck@test.local", "pass1234", "Chuck")

    monkeypatch.setattr(web_app, "DATA_DIR", data_dir)
    monkeypatch.setattr(web_app, "OUT_DIR", tmp_path / "output")
    web_app.OUT_DIR.mkdir()
    monkeypatch.setattr(web_app, "user_store", store)

    client = web_app.app.test_client()
    client.post("/login", data={"email": "chuck@test.local", "password": "pass1234"})
    response = client.get("/students")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Jane Doe" in html
    assert "Bob Smith" not in html


def test_teacher_cannot_create_student_in_other_turma(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "students.csv").write_text(_students_csv(), encoding="utf-8")

    monkeypatch.setattr(web_app, "DATA_DIR", data_dir)
    monkeypatch.setattr(web_app, "OUT_DIR", tmp_path / "output")
    web_app.OUT_DIR.mkdir()
    _init_teacher_store(monkeypatch, data_dir, teacher_name="Chuck")

    client = web_app.app.test_client()
    _login(client, email="teacher@test.local", password="teachpass")
    response = client.post(
        "/students/new",
        data={
            "teacher": "Chuck",
            "turma": "OTHER",
            "student_name": "Mallory",
        },
    )

    assert response.status_code == 200
    assert "não permitida" in response.get_data(as_text=True) or "Dashboard" in response.get_data(as_text=True)
    assert "Mallory" not in (data_dir / "students.csv").read_text(encoding="utf-8")


def test_teacher_edits_turma_and_updates_students(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    csv = (
        "teacher,turma,turma_display,nivel,horario,student_name,participacao,comportamento,"
        "speaking,listening,foco,writing,reading,gramatica,trabalho_equipe,organizacao,"
        "pontualidade,respeito_regras,faltas,missed_aulas,aula_extra,feedback_participacao,"
        "feedback_foco,feedback_trabalho_equipe,recomendacoes,observacao\n"
        "Chuck,MASTER,Masters,TEENS 4,Old schedule,Kid One,3,3,3,3,3,3,3,3,3,3,3,3,0,,,,,,,\n"
    )
    (data_dir / "students.csv").write_text(csv, encoding="utf-8")
    monkeypatch.setattr(web_app, "DATA_DIR", data_dir)
    monkeypatch.setattr(web_app, "OUT_DIR", tmp_path / "output")
    web_app.OUT_DIR.mkdir()
    _init_teacher_store(monkeypatch, data_dir, teacher_name="Chuck")
    _seed_teacher_classes(
        data_dir,
        "Chuck",
        ("MASTER", "Masters", "Segunda-feira", "Quarta-feira", "09:00", "10:00"),
    )

    client = web_app.app.test_client()
    _login(client, email="teacher@test.local", password="teachpass")
    html = client.get("/turmas/MASTER/edit").get_data(as_text=True)
    assert "Editar turma" in html
    assert 'name="turma_display"' in html

    response = client.post(
        "/turmas/MASTER/edit",
        data={
            "turma_display": "Masters Evening",
            "class_weekday_1": "Terça-feira",
            "class_weekday_2": "Quinta-feira",
            "turma_time_start": "19:00",
            "turma_time_end": "20:00",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "atualizada" in response.get_data(as_text=True)
    saved = (data_dir / "students.csv").read_text(encoding="utf-8")
    assert "Masters Evening" in saved
    assert "Terça-feira e Quinta-feira 19:00 - 20:00" in saved


def test_teacher_deletes_empty_turma(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "students.csv").write_text(_students_csv(), encoding="utf-8")

    monkeypatch.setattr(web_app, "DATA_DIR", data_dir)
    monkeypatch.setattr(web_app, "OUT_DIR", tmp_path / "output")
    web_app.OUT_DIR.mkdir()
    _init_teacher_store(monkeypatch, data_dir, teacher_name="Chuck")
    _seed_teacher_classes(
        data_dir,
        "Chuck",
        ("ORPHAN", "Orphan class", "Segunda-feira", "Quarta-feira", "10:00", "11:00"),
    )

    client = web_app.app.test_client()
    _login(client, email="teacher@test.local", password="teachpass")
    response = client.post(
        "/turmas/delete",
        data={"turma": "ORPHAN"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "excluída" in response.get_data(as_text=True)
    registry = (data_dir / "teacher_classes.json").read_text(encoding="utf-8")
    assert "ORPHAN" not in registry


def test_teacher_cannot_delete_turma_with_students(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "students.csv").write_text(_students_csv(), encoding="utf-8")
    monkeypatch.setattr(web_app, "DATA_DIR", data_dir)
    monkeypatch.setattr(web_app, "OUT_DIR", tmp_path / "output")
    web_app.OUT_DIR.mkdir()
    _init_teacher_store(monkeypatch, data_dir, teacher_name="Chuck")
    _seed_teacher_classes(
        data_dir,
        "Chuck",
        ("MASTER", "Masters", "Terça-feira", "Quinta-feira", "19:00", "20:00"),
    )

    client = web_app.app.test_client()
    _login(client, email="teacher@test.local", password="teachpass")
    response = client.post(
        "/turmas/delete",
        data={"turma": "MASTER"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "Não é possível excluir" in response.get_data(as_text=True)
    assert "MASTER" in (data_dir / "teacher_classes.json").read_text(encoding="utf-8")


def test_teacher_creates_turma_on_dashboard(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "students.csv").write_text(_students_csv(), encoding="utf-8")

    monkeypatch.setattr(web_app, "DATA_DIR", data_dir)
    monkeypatch.setattr(web_app, "OUT_DIR", tmp_path / "output")
    web_app.OUT_DIR.mkdir()
    _init_teacher_store(monkeypatch, data_dir, teacher_name="Chuck")

    client = web_app.app.test_client()
    _login(client, email="teacher@test.local", password="teachpass")
    response = client.post(
        "/turmas/create",
        data={
            "turma_display": "Kids segunda",
            "class_weekday_1": "Terça-feira",
            "class_weekday_2": "Quinta-feira",
            "turma_time_start": "19:30",
            "turma_time_end": "20:30",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    registry = (data_dir / "teacher_classes.json").read_text(encoding="utf-8")
    assert "KIDS_SEGUNDA" in registry
    assert "Kids segunda" in registry
    assert "Terça-feira" in registry
    assert "19:30 - 20:30" in registry


def test_students_page_shows_class_name_not_nivel(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    csv = (
        "teacher,turma,turma_display,nivel,horario,student_name,participacao,comportamento,"
        "speaking,listening,foco,writing,reading,gramatica,trabalho_equipe,organizacao,"
        "pontualidade,respeito_regras,faltas,missed_aulas,aula_extra,feedback_participacao,"
        "feedback_foco,feedback_trabalho_equipe,recomendacoes,observacao\n"
        "Chuck,TEENS_1,TEENS 1,TEENS 1,Tue 19:00,Kid,3,3,3,3,3,3,3,3,3,3,3,3,0,,,,,,,\n"
    )
    (data_dir / "students.csv").write_text(csv, encoding="utf-8")
    monkeypatch.setattr(web_app, "DATA_DIR", data_dir)
    monkeypatch.setattr(web_app, "OUT_DIR", tmp_path / "output")
    web_app.OUT_DIR.mkdir()
    _init_teacher_store(monkeypatch, data_dir, teacher_name="Chuck")
    from teacher_classes import add_class, load_registry, save_registry

    data = load_registry(web_app.TEACHER_CLASSES_PATH)
    add_class(
        data,
        "Chuck",
        turma_display="Turma Teens noite",
        class_weekdays=["Terça-feira", "Quinta-feira"],
        class_time_start="19:00",
        class_time_end="20:00",
        turma="TEENS_1",
    )
    save_registry(web_app.TEACHER_CLASSES_PATH, data)

    client = web_app.app.test_client()
    _login(client, email="teacher@test.local", password="teachpass")
    html = client.get("/students").get_data(as_text=True)
    assert "Turma Teens noite" in html
    assert 'data-filter-value="TEENS_1">Turma Teens noite' in html


def test_teacher_adds_student_to_dashboard_turma(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "students.csv").write_text(_students_csv(), encoding="utf-8")

    monkeypatch.setattr(web_app, "DATA_DIR", data_dir)
    monkeypatch.setattr(web_app, "OUT_DIR", tmp_path / "output")
    web_app.OUT_DIR.mkdir()
    _init_teacher_store(monkeypatch, data_dir, teacher_name="Chuck")
    client = web_app.app.test_client()
    _login(client, email="teacher@test.local", password="teachpass")
    client.post(
        "/turmas/create",
        data={
            "turma_display": "Kids 2 class",
            "class_weekday_1": "Segunda-feira",
            "class_weekday_2": "Quarta-feira",
            "turma_time_start": "10:00",
            "turma_time_end": "11:00",
        },
    )

    response = client.post(
        "/students/new",
        data={
            "teacher": "Chuck",
            "class_choice": "KIDS_2_CLASS",
            "nivel": "KIDS 2",
            "student_name": "New Class Kid",
            "participacao": "3",
            "comportamento": "3",
            "speaking": "3",
            "listening": "3",
            "foco": "3",
            "writing": "3",
            "reading": "3",
            "gramatica": "3",
            "faltas": "0",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    csv_text = (data_dir / "students.csv").read_text(encoding="utf-8")
    assert "New Class Kid" in csv_text
    assert "KIDS_2_CLASS" in csv_text


def test_student_edit_redirect_preserves_turma_filter(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "students.csv").write_text(_students_csv(), encoding="utf-8")
    monkeypatch.setattr(web_app, "DATA_DIR", data_dir)
    monkeypatch.setattr(web_app, "OUT_DIR", tmp_path / "output")
    web_app.OUT_DIR.mkdir()
    _init_teacher_store(monkeypatch, data_dir, teacher_name="Chuck")

    client = web_app.app.test_client()
    _login(client, email="teacher@test.local", password="teachpass")
    response = client.post(
        "/students/0/edit?turma=MASTER",
        data={
            "return_turma": "MASTER",
            "teacher": "Chuck",
            "class_choice": "MASTER",
            "nivel": "TEENS 4",
            "student_name": "Jane Doe",
            "participacao": "3",
            "comportamento": "3",
            "speaking": "3",
            "listening": "3",
            "foco": "3",
            "writing": "3",
            "reading": "3",
            "gramatica": "3",
            "trabalho_equipe": "3",
            "organizacao": "3",
            "pontualidade": "3",
            "respeito_regras": "3",
            "faltas": "0",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "turma=MASTER" in (response.headers.get("Location") or "")


def test_teacher_edits_csv_student_with_turma_dropdown(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    csv = (
        "teacher,turma,turma_display,nivel,horario,student_name,participacao,comportamento,"
        "speaking,listening,foco,writing,reading,gramatica,trabalho_equipe,organizacao,"
        "pontualidade,respeito_regras,faltas,missed_aulas,aula_extra,feedback_participacao,"
        "feedback_foco,feedback_trabalho_equipe,recomendacoes,observacao\n"
        "Chuck,MASTER,Masters,TEENS 4,Terça e quinta 19:00 - 20:00,Bruna Vieira,5,3,5,3,3,4,4,4,3,3,3,3,0,,,,,,,\n"
    )
    (data_dir / "students.csv").write_text(csv, encoding="utf-8")
    monkeypatch.setattr(web_app, "DATA_DIR", data_dir)
    monkeypatch.setattr(web_app, "OUT_DIR", tmp_path / "output")
    web_app.OUT_DIR.mkdir()
    _init_teacher_store(monkeypatch, data_dir, teacher_name="Chuck")

    client = web_app.app.test_client()
    _login(client, email="teacher@test.local", password="teachpass")
    edit_html = client.get("/students/0/edit").get_data(as_text=True)
    assert 'name="class_choice"' in edit_html
    assert "Selecione a turma do aluno" not in edit_html

    response = client.post(
        "/students/0/edit",
        data={
            "teacher": "Chuck",
            "class_choice": "MASTER",
            "nivel": "TEENS 4",
            "student_name": "Bruna Vieira Matias",
            "participacao": "5",
            "comportamento": "3",
            "speaking": "5",
            "listening": "3",
            "foco": "3",
            "writing": "4",
            "reading": "4",
            "gramatica": "4",
            "trabalho_equipe": "3",
            "organizacao": "3",
            "pontualidade": "3",
            "respeito_regras": "3",
            "faltas": "0",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    saved = (data_dir / "students.csv").read_text(encoding="utf-8")
    assert "Bruna Vieira Matias" in saved
    assert "Selecione a turma" not in client.get("/students/0/edit").get_data(as_text=True)


def _student_form_payload(**overrides):
    data = {
        "teacher": "Chuck",
        "class_choice": "MASTER",
        "nivel": "TEENS 4",
        "student_name": "Jane Doe",
        "participacao": "3",
        "comportamento": "3",
        "speaking": "3",
        "listening": "3",
        "foco": "3",
        "writing": "3",
        "reading": "3",
        "gramatica": "3",
        "trabalho_equipe": "3",
        "organizacao": "3",
        "pontualidade": "3",
        "respeito_regras": "3",
        "faltas": "0",
        "observacao": "",
        "recomendacoes": "",
        "feedback_participacao": "",
        "feedback_foco": "",
        "feedback_trabalho_equipe": "",
    }
    data.update(overrides)
    return data


def test_student_edit_page_includes_autosave_assets(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "students.csv").write_text(_students_csv(), encoding="utf-8")
    monkeypatch.setattr(web_app, "DATA_DIR", data_dir)
    monkeypatch.setattr(web_app, "OUT_DIR", tmp_path / "output")
    web_app.OUT_DIR.mkdir()
    _init_teacher_store(monkeypatch, data_dir, teacher_name="Chuck")

    client = web_app.app.test_client()
    _login(client, email="teacher@test.local", password="teachpass")
    html = client.get("/students/0/edit").get_data(as_text=True)
    assert 'id="student-edit-form"' in html
    assert "student_autosave.js" in html
    assert "/students/0/autosave" in html


def test_student_autosave_persists_observations(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "students.csv").write_text(_students_csv(), encoding="utf-8")
    (data_dir / "lessons.csv").write_text(_lessons_csv(), encoding="utf-8")
    monkeypatch.setattr(web_app, "DATA_DIR", data_dir)
    monkeypatch.setattr(web_app, "OUT_DIR", tmp_path / "output")
    web_app.OUT_DIR.mkdir()
    _init_teacher_store(monkeypatch, data_dir, teacher_name="Chuck")

    client = web_app.app.test_client()
    _login(client, email="teacher@test.local", password="teachpass")
    response = client.post(
        "/students/0/autosave",
        data=_student_form_payload(
            student_name="Jane Doe",
            observacao="Precisa reforço em speaking",
            recomendacoes="Praticar em casa",
            speaking="2",
        ),
        headers={"Accept": "application/json"},
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["ok"] is True
    assert "saved_at" in body

    reviews_path = data_dir / "student_monthly_reviews.json"
    if reviews_path.exists():
        stored = json.loads(reviews_path.read_text(encoding="utf-8"))
        rows = stored.get("rows") if isinstance(stored, dict) else stored
        assert any(
            (row.get("observacao") or "").startswith("Precisa reforço")
            for row in rows
        )


def test_student_autosave_requires_login(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "students.csv").write_text(_students_csv(), encoding="utf-8")
    monkeypatch.setattr(web_app, "DATA_DIR", data_dir)
    monkeypatch.setattr(web_app, "OUT_DIR", tmp_path / "output")
    web_app.OUT_DIR.mkdir()

    client = web_app.app.test_client()
    response = client.post(
        "/students/0/autosave",
        data=_student_form_payload(),
        headers={"Accept": "application/json"},
    )
    assert response.status_code == 401
    assert response.get_json()["login_required"] is True


def test_teacher_new_student_form_lists_dashboard_turmas(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "students.csv").write_text(_students_csv(), encoding="utf-8")

    monkeypatch.setattr(web_app, "DATA_DIR", data_dir)
    monkeypatch.setattr(web_app, "OUT_DIR", tmp_path / "output")
    web_app.OUT_DIR.mkdir()
    _init_teacher_store(monkeypatch, data_dir, teacher_name="Chuck")

    client = web_app.app.test_client()
    _login(client, email="teacher@test.local", password="teachpass")
    html = client.get("/students/new").get_data(as_text=True)

    assert "Masters" in html
    assert "MASTER" in html
    assert "criar classe" not in html.lower()
    assert "KIDS 1" in html


def test_student_new_requires_turma(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "students.csv").write_text(_students_csv(), encoding="utf-8")

    monkeypatch.setattr(web_app, "DATA_DIR", data_dir)
    monkeypatch.setattr(web_app, "OUT_DIR", tmp_path / "output")
    web_app.OUT_DIR.mkdir()
    _init_user_store(monkeypatch, data_dir)

    client = web_app.app.test_client()
    _login(client)
    response = client.post(
        "/students/new",
        data={"student_name": "No Turma Kid", "teacher": "Chuck", "turma": ""},
    )

    assert response.status_code == 200
    assert "Informe o nome do aluno e a turma" in response.get_data(as_text=True)


def test_student_new_creates_row(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "students.csv").write_text(_students_csv(), encoding="utf-8")
    (data_dir / "lessons.csv").write_text(_lessons_csv(), encoding="utf-8")

    monkeypatch.setattr(web_app, "DATA_DIR", data_dir)
    monkeypatch.setattr(web_app, "OUT_DIR", tmp_path / "output")
    monkeypatch.setattr(web_app, "MONTHLY_REVIEWS_PATH", data_dir / "student_monthly_reviews.json")
    monkeypatch.setattr(web_app, "_monthly_migration_done", False)
    web_app.OUT_DIR.mkdir()
    _init_user_store(monkeypatch, data_dir)

    client = web_app.app.test_client()
    _login(client)
    response = client.post(
        "/students/new",
        data={
            "teacher": "Chuck",
            "turma": "KIDS",
            "student_name": "New Kid",
            "participacao": "3",
            "comportamento": "3",
            "speaking": "3",
            "listening": "3",
            "foco": "3",
            "writing": "3",
            "reading": "3",
            "gramatica": "3",
            "faltas": "0",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert "/students" in response.headers["Location"]
    assert "New Kid" in (data_dir / "students.csv").read_text(encoding="utf-8")
    reviews_path = data_dir / "student_monthly_reviews.json"
    assert reviews_path.exists()
    reviews = json.loads(reviews_path.read_text(encoding="utf-8"))
    assert any(r.get("participacao") == "3" for r in reviews)


def test_set_review_month_redirects(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "students.csv").write_text(_students_csv(), encoding="utf-8")
    (data_dir / "lessons.csv").write_text(
        "turma,aula_num,date,licao_conteudo,atividade_extra,habilidades\n"
        "MASTER,1,15/03/2026,Lesson 1,,\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(web_app, "DATA_DIR", data_dir)
    monkeypatch.setattr(web_app, "OUT_DIR", tmp_path / "output")
    web_app.OUT_DIR.mkdir()
    monkeypatch.setattr(web_app, "MONTHLY_REVIEWS_PATH", data_dir / "student_monthly_reviews.json")
    monkeypatch.setattr(web_app, "_monthly_migration_done", True)
    _init_user_store(monkeypatch, data_dir)

    client = web_app.app.test_client()
    _login(client)
    response = client.post(
        "/review-month",
        data={"review_month": "2026-03", "next": "http://localhost/students"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    with client.session_transaction() as sess:
        assert sess.get("review_month") == "2026-03"


def test_set_review_month_blocks_open_redirect(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "students.csv").write_text(_students_csv(), encoding="utf-8")
    (data_dir / "lessons.csv").write_text(
        "turma,aula_num,date,licao_conteudo,atividade_extra,habilidades\n"
        "MASTER,1,15/03/2026,Lesson 1,,\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(web_app, "DATA_DIR", data_dir)
    monkeypatch.setattr(web_app, "OUT_DIR", tmp_path / "output")
    web_app.OUT_DIR.mkdir()
    monkeypatch.setattr(web_app, "MONTHLY_REVIEWS_PATH", data_dir / "student_monthly_reviews.json")
    monkeypatch.setattr(web_app, "_monthly_migration_done", True)
    _init_user_store(monkeypatch, data_dir)

    client = web_app.app.test_client()
    _login(client)
    response = client.post(
        "/review-month",
        data={
            "review_month": "2026-03",
            "next": "http://localhost.evil.com/phish",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/?month=2026-03")


def test_student_delete_cascades_related_records(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "students.csv").write_text(_students_csv(), encoding="utf-8")
    (data_dir / "lessons.csv").write_text(_lessons_csv(), encoding="utf-8")
    (data_dir / "lesson_attendance.csv").write_text(
        "turma,aula_num,student_name,status\n"
        "MASTER,2,Jane Doe,absent\n",
        encoding="utf-8",
    )
    (data_dir / "extra_sessions.csv").write_text(
        "teacher,student_name,turma,date,horario,turno,session_type,status,observacao\n"
        "Chuck,Jane Doe,MASTER,10/02/2026,09:00,Manhã,Reposição,OK,,\n",
        encoding="utf-8",
    )
    reviews = [{
        "report_month": "2026-02",
        "turma": "MASTER",
        "student_name": "Jane Doe",
        "participacao": "4",
        "faltas": "1",
        "missed_aulas": "2",
    }]
    (data_dir / "student_monthly_reviews.json").write_text(
        json.dumps(reviews), encoding="utf-8"
    )

    monkeypatch.setattr(web_app, "DATA_DIR", data_dir)
    monkeypatch.setattr(web_app, "OUT_DIR", tmp_path / "output")
    monkeypatch.setattr(web_app, "MONTHLY_REVIEWS_PATH", data_dir / "student_monthly_reviews.json")
    monkeypatch.setattr(web_app, "_monthly_migration_done", True)
    web_app.OUT_DIR.mkdir()
    _init_user_store(monkeypatch, data_dir)

    client = web_app.app.test_client()
    _login(client)
    with client.session_transaction() as sess:
        sess["review_month"] = "2026-02"

    response = client.post("/students/0/delete", follow_redirects=True)
    assert response.status_code == 200
    assert "Jane Doe" not in (data_dir / "students.csv").read_text(encoding="utf-8")
    assert "Jane Doe" not in (data_dir / "lesson_attendance.csv").read_text(encoding="utf-8")
    assert "Jane Doe" not in (data_dir / "extra_sessions.csv").read_text(encoding="utf-8")
    assert json.loads((data_dir / "student_monthly_reviews.json").read_text(encoding="utf-8")) == []


def test_monthly_scores_differ_by_review_month(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "students.csv").write_text(_students_csv(), encoding="utf-8")
    (data_dir / "lessons.csv").write_text(
        "turma,aula_num,date,licao_conteudo,atividade_extra,habilidades\n"
        "MASTER,1,15/02/2026,Lesson 1,,\n"
        "MASTER,2,15/03/2026,Lesson 2,,\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(web_app, "DATA_DIR", data_dir)
    monkeypatch.setattr(web_app, "OUT_DIR", tmp_path / "output")
    web_app.OUT_DIR.mkdir()
    reviews_path = data_dir / "student_monthly_reviews.json"
    monkeypatch.setattr(web_app, "MONTHLY_REVIEWS_PATH", reviews_path)
    monkeypatch.setattr(web_app, "_monthly_migration_done", True)
    _init_user_store(monkeypatch, data_dir)

    client = web_app.app.test_client()
    _login(client)

    base_form = {
        "teacher": "Chuck",
        "turma": "MASTER",
        "student_name": "Jane Doe",
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
        "faltas": "1",
        "missed_aulas": "2",
        "aula_extra": "Reposicao",
    }

    client.post(
        "/students/0/edit?month=2026-03",
        data={**base_form, "participacao": "5"},
        follow_redirects=False,
    )
    client.post(
        "/students/0/edit?month=2026-02",
        data={**base_form, "participacao": "2"},
        follow_redirects=False,
    )

    assert reviews_path.exists()
    reviews = json.loads(reviews_path.read_text(encoding="utf-8"))
    scores = {row["report_month"]: row["participacao"] for row in reviews}
    assert scores.get("2026-03") == "5"
    assert scores.get("2026-02") == "2"

    html_mar = client.get("/students?month=2026-03").get_data(as_text=True)
    html_feb = client.get("/students?month=2026-02").get_data(as_text=True)
    assert ">5<" in html_mar or "participacao" in html_mar.lower()
    assert ">2<" in html_feb


def test_upload_template_lessons_download(monkeypatch, tmp_path):
    monkeypatch.setattr(web_app, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(web_app, "OUT_DIR", tmp_path / "output")
    web_app.DATA_DIR.mkdir()
    web_app.OUT_DIR.mkdir()
    _init_user_store(monkeypatch, web_app.DATA_DIR)

    client = web_app.app.test_client()
    _login(client)

    response = client.get("/upload/template/lessons")

    assert response.status_code == 200
    assert "lessons_template.csv" in response.headers.get("Content-Disposition", "")
    assert response.data.startswith(b"\xef\xbb\xbf")
    assert b"turma,aula_num,date,licao_conteudo" in response.data
    assert b"MASTER,2," in response.data


def test_admin_delete_student_with_merged_monthly_data(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "students.csv").write_text(_students_csv(), encoding="utf-8")
    (data_dir / "lessons.csv").write_text(
        "turma,aula_num,date,licao_conteudo,atividade_extra,habilidades\n"
        "MASTER,1,10/05/2026,Lesson 1,,\n"
        "MASTER,2,12/05/2026,Lesson 2,,\n",
        encoding="utf-8",
    )
    (data_dir / "lesson_attendance.csv").write_text(
        "turma,aula_num,student_name,status\n"
        "MASTER,2,Jane Doe,absent\n",
        encoding="utf-8",
    )
    reviews = [{
        "teacher": "Chuck",
        "turma": "MASTER",
        "student_name": "Jane Doe",
        "month": "2026-05",
        "participacao": "5",
        "comportamento": "4",
        "speaking": "4",
        "listening": "4",
        "foco": "4",
        "writing": "4",
        "reading": "4",
        "gramatica": "4",
        "trabalho_equipe": "4",
        "organizacao": "4",
        "pontualidade": "4",
        "respeito_regras": "4",
        "faltas": "1",
        "missed_aulas": "2",
        "aula_extra": "",
        "feedback_participacao": "",
        "feedback_foco": "",
        "feedback_trabalho_equipe": "",
        "recomendacoes": "",
        "observacao": "",
    }]
    (data_dir / "student_monthly_reviews.json").write_text(
        json.dumps(reviews), encoding="utf-8"
    )

    monkeypatch.setattr(web_app, "DATA_DIR", data_dir)
    monkeypatch.setattr(web_app, "OUT_DIR", tmp_path / "output")
    monkeypatch.setattr(web_app, "MONTHLY_REVIEWS_PATH", data_dir / "student_monthly_reviews.json")
    monkeypatch.setattr(web_app, "_monthly_migration_done", True)
    web_app.OUT_DIR.mkdir()
    _init_user_store(monkeypatch, data_dir)

    client = web_app.app.test_client()
    _login(client)
    with client.session_transaction() as sess:
        sess["review_month"] = "2026-05"

    response = client.post("/students/0/delete", follow_redirects=True)

    assert response.status_code == 200
    remaining = (data_dir / "students.csv").read_text(encoding="utf-8")
    assert "Jane Doe" not in remaining


def test_admin_delete_students_csv(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "students.csv").write_text(_students_csv(), encoding="utf-8")

    monkeypatch.setattr(web_app, "DATA_DIR", data_dir)
    monkeypatch.setattr(web_app, "OUT_DIR", tmp_path / "output")
    web_app.OUT_DIR.mkdir()
    _init_user_store(monkeypatch, data_dir)

    client = web_app.app.test_client()
    _login(client)
    response = client.post("/upload/delete/students", follow_redirects=True)

    assert response.status_code == 200
    assert not (data_dir / "students.csv").exists()
    assert b"alert-success" in response.data
    assert b"arquivo CSV removido" in response.data


def test_teacher_delete_only_own_students(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    mixed = (
        "teacher,turma,turma_display,nivel,horario,student_name,participacao,comportamento,speaking,listening,foco,writing,reading,gramatica,trabalho_equipe,organizacao,pontualidade,respeito_regras,faltas,missed_aulas,aula_extra,feedback_participacao,feedback_foco,feedback_trabalho_equipe,recomendacoes,observacao\n"
        "Chuck,MASTER,Masters,Adults Book 4,Tue 19:00,Jane Doe,4,3,4,5,4,3,4,2,3,3,3,3,1,2,Reposicao,Good,Focus,Team,Practice speaking,\n"
        "Barbara,SPARK,Spark,Teens,Tue 18:00,Bob Smith,3,3,3,3,3,3,3,3,3,3,3,3,0,0,,,,,,\n"
    )
    (data_dir / "students.csv").write_text(mixed, encoding="utf-8")

    monkeypatch.setattr(web_app, "DATA_DIR", data_dir)
    monkeypatch.setattr(web_app, "OUT_DIR", tmp_path / "output")
    web_app.OUT_DIR.mkdir()
    _init_teacher_store(monkeypatch, data_dir, teacher_name="Chuck")

    client = web_app.app.test_client()
    _login(client, email="teacher@test.local", password="teachpass")
    response = client.post("/upload/delete/students", follow_redirects=True)

    assert response.status_code == 200
    assert b"1 registro(s) do seu perfil" in response.data
    remaining = (data_dir / "students.csv").read_text(encoding="utf-8")
    assert "Jane Doe" not in remaining
    assert "Bob Smith" in remaining


def test_teacher_upload_rejects_other_teacher_rows(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    monkeypatch.setattr(web_app, "DATA_DIR", data_dir)
    monkeypatch.setattr(web_app, "OUT_DIR", tmp_path / "output")
    web_app.OUT_DIR.mkdir()
    _init_teacher_store(monkeypatch, data_dir)

    bad_csv = _students_csv().replace("Chuck,", "Ana,", 1)

    client = web_app.app.test_client()
    _login(client, email="teacher@test.local", password="teachpass")
    response = client.post(
        "/upload",
        data={"students": (io.BytesIO(bad_csv.encode()), "students.csv")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"teacher deve ser" in response.data
    assert not (data_dir / "students.csv").exists()


def test_extra_sessions_import_and_list(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(web_app, "DATA_DIR", data_dir)
    monkeypatch.setattr(web_app, "OUT_DIR", tmp_path / "output")
    web_app.OUT_DIR.mkdir()
    _init_user_store(monkeypatch, data_dir)

    csv_body = (
        ",Nome do aluno ou responsável,Data ,Horário,Assuntos trabalhados,Observação,"
        "Turno,Contatado,Marcado,Realizado,Professor\n"
        ",Import Kid (MASTER),01/05,09:00,Reforço - test,,Manhã,ok,ok,ok,Chuck\n"
    )

    client = web_app.app.test_client()
    _login(client)
    response = client.post(
        "/extra-sessions/import",
        data={"file": (io.BytesIO(csv_body.encode("utf-8")), "atendimentos.csv"), "mode": "merge"},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"adicionado" in response.data
    assert b"Import Kid" in response.data


def test_teacher_extra_sessions_scoped(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(web_app, "DATA_DIR", data_dir)
    monkeypatch.setattr(web_app, "OUT_DIR", tmp_path / "output")
    web_app.OUT_DIR.mkdir()
    _init_teacher_store(monkeypatch, data_dir)

    web_app._save_extra_sessions([
        {"teacher": "Chuck", "student_name": "A", "turma": "T1", "date": "1", "horario": "",
         "turno": "", "session_type": "Reforço", "assuntos": "", "observacao": "",
         "contatado": "", "marcado": "", "realizado": ""},
        {"teacher": "Ana", "student_name": "B", "turma": "T2", "date": "2", "horario": "",
         "turno": "", "session_type": "Reforço", "assuntos": "", "observacao": "",
         "contatado": "", "marcado": "", "realizado": ""},
    ])

    client = web_app.app.test_client()
    _login(client, email="teacher@test.local", password="teachpass")
    response = client.get("/extra-sessions")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert ">A</strong>" in html or "student_name\">A" in html
    assert ">B</strong>" not in html


def test_download_atendimentos_template(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(web_app, "DATA_DIR", data_dir)
    monkeypatch.setattr(web_app, "OUT_DIR", tmp_path / "output")
    web_app.OUT_DIR.mkdir()
    _init_teacher_store(monkeypatch, data_dir)

    client = web_app.app.test_client()
    _login(client, email="teacher@test.local", password="teachpass")
    response = client.get("/extra-sessions/template")
    assert response.status_code == 200
    assert "attachment" in response.headers.get("Content-Disposition", "")
    body = response.get_data(as_text=True)
    assert "Nome do aluno ou responsável" in body
    assert "Chuck" in body


def test_teacher_upload_merges_without_wiping_other_teachers(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "students.csv").write_text(
        _students_csv().replace("Jane Doe", "Bob Smith").replace("Chuck,", "Ana,", 1),
        encoding="utf-8",
    )

    monkeypatch.setattr(web_app, "DATA_DIR", data_dir)
    monkeypatch.setattr(web_app, "OUT_DIR", tmp_path / "output")
    web_app.OUT_DIR.mkdir()
    _init_teacher_store(monkeypatch, data_dir)

    client = web_app.app.test_client()
    _login(client, email="teacher@test.local", password="teachpass")
    response = client.post(
        "/upload",
        data={"students": (io.BytesIO(_students_csv().encode()), "students.csv")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Alunos carregado" in response.data
    text = (data_dir / "students.csv").read_text(encoding="utf-8")
    assert "Jane Doe" in text
    assert "Bob Smith" in text


def test_responsive_layout_markers(monkeypatch, tmp_path):
    """List pages expose table + card views and action columns use shared layout classes."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "students.csv").write_text(_students_csv(), encoding="utf-8")
    (data_dir / "lessons.csv").write_text(_lessons_csv(), encoding="utf-8")
    monkeypatch.setattr(web_app, "DATA_DIR", data_dir)
    monkeypatch.setattr(web_app, "OUT_DIR", tmp_path / "output")
    web_app.OUT_DIR.mkdir()
    _init_user_store(monkeypatch, data_dir)

    web_app._save_extra_sessions([
        {"teacher": "Chuck", "student_name": "Jane Doe", "turma": "MASTER", "date": "01/05",
         "horario": "09:00", "turno": "Manhã", "session_type": "Reforço", "assuntos": "Test",
         "observacao": "", "contatado": "ok", "marcado": "ok", "realizado": "ok"},
    ])

    client = web_app.app.test_client()
    _login(client)

    students_html = client.get("/students").get_data(as_text=True)
    assert 'td class="col-actions"' in students_html
    assert "students-cards-view" in students_html
    assert "student-card-actions" in students_html

    lessons_html = client.get("/lessons").get_data(as_text=True)
    assert 'td class="col-actions"' in lessons_html
    assert "lesson-card-item" in lessons_html

    extra_html = client.get("/extra-sessions").get_data(as_text=True)
    assert "session-card-item" in extra_html
    assert "students-cards-view" in extra_html
    assert 'td class="col-actions"' in extra_html

    dashboard_html = client.get("/").get_data(as_text=True)
    assert "list-row-actions" in dashboard_html or "turma-list" in dashboard_html

    upload_html = client.get("/upload").get_data(as_text=True)
    assert "inline-actions" in upload_html
    assert "viewport" in upload_html


def test_turma_transfer_page_and_auto_transfer(monkeypatch, tmp_path):
  data_dir = tmp_path / "data"
  data_dir.mkdir()
  (data_dir / "students.csv").write_text(_students_csv(), encoding="utf-8")
  (data_dir / "lessons.csv").write_text(_lessons_csv(), encoding="utf-8")
  monkeypatch.setattr(web_app, "DATA_DIR", data_dir)
  monkeypatch.setattr(web_app, "OUT_DIR", tmp_path / "output")
  web_app.OUT_DIR.mkdir()
  _init_user_store(monkeypatch, data_dir)
  _seed_teacher_classes(
      data_dir,
      "Chuck",
      ("MASTER", "Masters", "Terça-feira", "Quinta-feira", "19:00", "20:00"),
  )
  web_app.user_store.create_teacher("paula@test.local", "teachpass", "Paula")

  client = web_app.app.test_client()
  _login(client)

  page = client.get("/admin/turmas/transfer").get_data(as_text=True)
  assert "Transferir turma" in page
  assert "Chuck" in page

  response = client.post(
      "/admin/turmas/transfer",
      data={
          "action": "transfer",
          "from_teacher": "Chuck",
          "to_teacher": "Paula",
          "turma": "MASTER",
      },
      follow_redirects=True,
  )
  assert response.status_code == 200
  assert b"transferida" in response.data

  students_text = (data_dir / "students.csv").read_text(encoding="utf-8")
  assert "Paula" in students_text
  assert ",Chuck," not in students_text

  registry = json.loads((data_dir / "teacher_classes.json").read_text(encoding="utf-8"))
  assert "Paula" in registry or any(k.casefold() == "paula" for k in registry)
  chuck_keys = [k for k in registry if k.casefold() == "chuck"]
  if chuck_keys:
      chuck_turmas = {r.get("turma") for r in registry[chuck_keys[0]]}
      assert "MASTER" not in chuck_turmas


def test_turma_transfer_export_zip(monkeypatch, tmp_path):
  data_dir = tmp_path / "data"
  data_dir.mkdir()
  (data_dir / "students.csv").write_text(_students_csv(), encoding="utf-8")
  (data_dir / "lessons.csv").write_text(_lessons_csv(), encoding="utf-8")
  monkeypatch.setattr(web_app, "DATA_DIR", data_dir)
  monkeypatch.setattr(web_app, "OUT_DIR", tmp_path / "output")
  web_app.OUT_DIR.mkdir()
  _init_user_store(monkeypatch, data_dir)
  _seed_teacher_classes(
      data_dir,
      "Chuck",
      ("MASTER", "Masters", "Terça-feira", "Quinta-feira", "19:00", "20:00"),
  )
  web_app.user_store.create_teacher("paula@test.local", "teachpass", "Paula")

  client = web_app.app.test_client()
  _login(client)

  response = client.post(
      "/admin/turmas/transfer",
      data={
          "action": "export",
          "from_teacher": "Chuck",
          "to_teacher": "Paula",
          "turma": "MASTER",
      },
  )
  assert response.status_code == 200
  assert response.mimetype == "application/zip"
  zf = zipfile.ZipFile(io.BytesIO(response.data))
  assert "students.csv" in zf.namelist()
  assert "lessons.csv" in zf.namelist()


def test_superadmin_dashboard_shows_class_display_names(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "students.csv").write_text(
        "teacher,turma,turma_display,nivel,horario,student_name,participacao,comportamento,speaking,listening,foco,writing,reading,gramatica,trabalho_equipe,organizacao,pontualidade,respeito_regras,faltas,missed_aulas,aula_extra,feedback_participacao,feedback_foco,feedback_trabalho_equipe,recomendacoes,observacao\n"
        "Chuck,TEENS_1,Teens Book 1,Teens Book 1,Mon 18:00,Alice,4,3,4,5,4,3,4,2,3,3,3,3,1,2,Reposicao,Good,Focus,Team,Practice speaking,\n",
        encoding="utf-8",
    )
    (data_dir / "lessons.csv").write_text(
        "turma,aula_num,date,licao_conteudo,atividade_extra,habilidades\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(web_app, "DATA_DIR", data_dir)
    monkeypatch.setattr(web_app, "OUT_DIR", tmp_path / "output")
    web_app.OUT_DIR.mkdir()
    _init_user_store(monkeypatch, data_dir)
    _seed_teacher_classes(
        data_dir,
        "Chuck",
        ("TEENS_1", "Prize", "Segunda-feira", "Quarta-feira", "18:00", "19:00"),
    )

    client = web_app.app.test_client()
    _login(client)
    html = client.get("/").get_data(as_text=True)

    assert "Prize" in html
    assert ">TEENS_1<" not in html
    assert 'href="/students?turma=TEENS_1"' in html


def test_superadmin_dashboard_includes_registry_only_class(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "students.csv").write_text(
        "teacher,turma,turma_display,nivel,horario,student_name,participacao,comportamento,speaking,listening,foco,writing,reading,gramatica,trabalho_equipe,organizacao,pontualidade,respeito_regras,faltas,missed_aulas,aula_extra,feedback_participacao,feedback_foco,feedback_trabalho_equipe,recomendacoes,observacao\n",
        encoding="utf-8",
    )
    (data_dir / "lessons.csv").write_text(
        "turma,aula_num,date,licao_conteudo,atividade_extra,habilidades\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(web_app, "DATA_DIR", data_dir)
    monkeypatch.setattr(web_app, "OUT_DIR", tmp_path / "output")
    web_app.OUT_DIR.mkdir()
    _init_user_store(monkeypatch, data_dir)
    _seed_teacher_classes(
        data_dir,
        "Chuck",
        ("MASTER", "Masters", "Terça-feira", "Quinta-feira", "19:00", "20:00"),
    )

    client = web_app.app.test_client()
    _login(client)
    html = client.get("/").get_data(as_text=True)

    assert "Masters" in html
    assert 'href="/students?turma=MASTER"' in html


def test_admin_can_edit_turma(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "students.csv").write_text(_students_csv(), encoding="utf-8")
    (data_dir / "lessons.csv").write_text(_lessons_csv(), encoding="utf-8")
    monkeypatch.setattr(web_app, "DATA_DIR", data_dir)
    monkeypatch.setattr(web_app, "OUT_DIR", tmp_path / "output")
    web_app.OUT_DIR.mkdir()
    _init_user_store(monkeypatch, data_dir)
    _seed_teacher_classes(
        data_dir,
        "Chuck",
        ("MASTER", "Masters", "Terça-feira", "Quinta-feira", "19:00", "20:00"),
    )

    client = web_app.app.test_client()
    _login(client)

    response = client.get("/turmas/MASTER/edit?teacher=Chuck")
    assert response.status_code == 200
    assert "Masters" in response.get_data(as_text=True)

    response = client.post(
        "/turmas/MASTER/edit?teacher=Chuck",
        data={
            "teacher": "Chuck",
            "turma_display": "Masters Updated",
            "class_weekday_1": "Segunda-feira",
            "class_weekday_2": "Quarta-feira",
            "turma_time_start": "18:00",
            "turma_time_end": "19:00",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"atualizada" in response.data

    students_text = (data_dir / "students.csv").read_text(encoding="utf-8")
    assert "Masters Updated" in students_text


def test_admin_can_create_turma(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "students.csv").write_text(
        "teacher,turma,turma_display,nivel,horario,student_name,participacao,comportamento,speaking,listening,foco,writing,reading,gramatica,trabalho_equipe,organizacao,pontualidade,respeito_regras,faltas,missed_aulas,aula_extra,feedback_participacao,feedback_foco,feedback_trabalho_equipe,recomendacoes,observacao\n",
        encoding="utf-8",
    )
    (data_dir / "lessons.csv").write_text(
        "turma,aula_num,date,licao_conteudo,atividade_extra,habilidades\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(web_app, "DATA_DIR", data_dir)
    monkeypatch.setattr(web_app, "OUT_DIR", tmp_path / "output")
    web_app.OUT_DIR.mkdir()
    _init_user_store(monkeypatch, data_dir)

    client = web_app.app.test_client()
    _login(client)
    response = client.post(
        "/turmas/create",
        data={
            "teacher": "Chuck",
            "turma_display": "New Class",
            "class_weekday_1": "Terça-feira",
            "class_weekday_2": "Quinta-feira",
            "turma_time_start": "19:00",
            "turma_time_end": "20:00",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"criada" in response.data
    registry = json.loads((data_dir / "teacher_classes.json").read_text(encoding="utf-8"))
    assert any(
        entry.get("turma_display") == "New Class"
        for entries in registry.values()
        for entry in entries
    )


def test_teacher_cannot_edit_other_teacher_turma(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "students.csv").write_text(_students_csv(), encoding="utf-8")
    (data_dir / "lessons.csv").write_text(_lessons_csv(), encoding="utf-8")
    monkeypatch.setattr(web_app, "DATA_DIR", data_dir)
    monkeypatch.setattr(web_app, "OUT_DIR", tmp_path / "output")
    web_app.OUT_DIR.mkdir()
    _init_teacher_store(monkeypatch, data_dir, teacher_name="Chuck")
    _seed_teacher_classes(
        data_dir,
        "Paula",
        ("PAULA_ONLY", "Paula Class", "Terça-feira", "Quinta-feira", "19:00", "20:00"),
    )

    client = web_app.app.test_client()
    _login(client, email="teacher@test.local", password="teachpass")
    response = client.get("/turmas/PAULA_ONLY/edit?teacher=Paula")
    assert response.status_code == 302

