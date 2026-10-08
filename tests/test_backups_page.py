"""Admin backups page: full download, restore points from bulk actions, and restore."""

import io
import json
import zipfile

import pytest

import app as web_app
from db_store import DatabaseStore
from test_app import _init_teacher_store, _login, _students_csv


@pytest.fixture
def school(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(web_app, "DATA_DIR", data_dir)
    monkeypatch.setattr(web_app, "OUT_DIR", tmp_path / "output")
    web_app.OUT_DIR.mkdir()
    store = DatabaseStore(f"sqlite:///{tmp_path / 'app.db'}")
    store.initialize()
    monkeypatch.setattr(web_app, "db_store", store)
    monkeypatch.setattr(web_app, "_services_ready", True)
    _init_teacher_store(monkeypatch, data_dir, teacher_name="Chuck")
    admin = web_app.app.test_client()
    _login(admin, email="admin@test.local", password="testpass")
    upload(admin, _students_csv())
    teacher = web_app.app.test_client()
    _login(teacher, email="teacher@test.local", password="teachpass")
    return {"store": store, "admin": admin, "teacher": teacher}


def upload(client, csv_text):
    return client.post("/upload", data={"students": (io.BytesIO(csv_text.encode()), "alunos.csv")})


def test_teachers_cannot_reach_backups(school):
    teacher = school["teacher"]
    assert teacher.get("/admin/backups").status_code == 403
    assert teacher.get("/admin/backups/download").status_code == 403
    assert teacher.post("/admin/backups/1/restore").status_code == 403
    assert "Backups" not in teacher.get("/").get_data(as_text=True)


def test_wrong_csv_upload_can_be_undone(school):
    admin, store = school["admin"], school["store"]
    assert [s["student_name"] for s in store.load_students()] == ["Jane Doe"]
    upload(admin, _students_csv().replace("Jane Doe", "Wrong Kid"))
    assert [s["student_name"] for s in store.load_students()] == ["Wrong Kid"]

    page = admin.get("/admin/backups").get_data(as_text=True)
    assert "Upload de CSV" in page and "Alunos" in page
    point = next(b for b in store.list_backups() if b["reason"] == "Upload de CSV")
    resp = admin.post(f"/admin/backups/{point['id']}/restore")
    assert resp.status_code == 302
    assert [s["student_name"] for s in store.load_students()] == ["Jane Doe"]
    assert "Alunos restaurado (1 registro(s))" in admin.get("/admin/backups").get_data(as_text=True)


def test_deleting_all_students_can_be_undone(school):
    admin, store = school["admin"], school["store"]
    admin.post("/upload/delete/students")
    assert store.load_students() == []
    point = next(b for b in store.list_backups() if b["reason"] == "Remoção de CSV")
    admin.post(f"/admin/backups/{point['id']}/restore")
    assert [s["student_name"] for s in store.load_students()] == ["Jane Doe"]


def test_full_backup_zip_has_all_data_and_no_passwords(school):
    resp = school["admin"].get("/admin/backups/download")
    assert resp.status_code == 200
    assert resp.headers["Content-Disposition"].startswith("attachment; filename=mister_wiz_backup_")
    zf = zipfile.ZipFile(io.BytesIO(resp.get_data()))
    assert {"mister_wiz_dados.json", "alunos.csv", "aulas.csv", "LEIA-ME.txt"} <= set(zf.namelist())
    data = json.loads(zf.read("mister_wiz_dados.json"))
    assert [s["student_name"] for s in data["students"]] == ["Jane Doe"]
    assert "Jane Doe" in zf.read("alunos.csv").decode()
    raw = zf.read("mister_wiz_dados.json").decode()
    assert "password_hash" not in raw and "pbkdf2" not in raw and "scrypt" not in raw


def test_restore_of_unknown_point_shows_error(school):
    school["admin"].post("/admin/backups/99999/restore")
    assert "Ponto de restauração não encontrado" in school["admin"].get("/admin/backups").get_data(as_text=True)


def test_undo_whole_action_restores_every_store_it_changed(school):
    admin, store = school["admin"], school["store"]
    store.save_lessons([{"turma": "MASTER", "aula_num": "1", "date": "01/09/2026"}])
    with web_app.backup_reason("Transferência de turma"):  # what the transfer routes do
        store.save_students([])
        store.save_lessons([])
    page = admin.get("/admin/backups").get_data(as_text=True)
    assert page.count("Desfazer ação inteira</button>") == 1
    ids = [b["id"] for b in store.list_backups() if b["reason"] == "Transferência de turma"]
    admin.post("/admin/backups/restore-group", data={"backup_id": ids})
    assert [s["student_name"] for s in store.load_students()] == ["Jane Doe"]
    assert len(store.load_lessons()) == 1
    assert "Ação desfeita" in admin.get("/admin/backups").get_data(as_text=True)


def test_deleting_one_student_is_one_undoable_action(school):
    admin, store = school["admin"], school["store"]
    admin.post("/students/0/delete", data={"orig_turma": "MASTER", "orig_student_name": "Jane Doe"})
    assert store.load_students() == []
    points = [b for b in store.list_backups() if b["reason"] == "Exclusão de aluno"]
    assert "students" in {b["store"] for b in points}
    admin.post("/admin/backups/restore-group", data={"backup_id": [b["id"] for b in points]})
    assert [s["student_name"] for s in store.load_students()] == ["Jane Doe"]


def test_csv_mode_backup_has_only_data_files_and_users_without_hashes(school, monkeypatch):
    data_dir = web_app.DATA_DIR
    (data_dir / "students.csv").write_text(_students_csv(), encoding="utf-8")
    (data_dir / "secret_token.txt").write_text("sk-live-123", encoding="utf-8")
    monkeypatch.setattr(web_app, "db_store", None)
    zf = zipfile.ZipFile(io.BytesIO(school["admin"].get("/admin/backups/download").get_data()))
    names = set(zf.namelist())
    assert "students.csv" in names and "users.json" in names
    assert "secret_token.txt" not in names
    users = json.loads(zf.read("users.json"))
    assert {u["email"] for u in users} >= {"admin@test.local", "teacher@test.local"}
    assert all("password_hash" not in u for u in users)
