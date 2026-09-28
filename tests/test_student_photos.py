import base64
import io
import json

import app as web_app
from auth import UserStore
from compiler import create_report_environment, generate_individual_reports
from db_store import DatabaseStore
from student_photos import (find_photo, move_photo, photo_data_url, photo_key,
                            remove_photo, set_photo)
from test_app import _init_teacher_store, _login, _students_csv

# Smallest valid PNG header is enough for the magic-byte check.
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
PNG_B64 = base64.b64encode(PNG).decode("ascii")

TWO_TEACHERS_CSV = (
    "teacher,turma,turma_display,nivel,horario,student_name,participacao,comportamento,speaking,listening,foco,writing,reading,gramatica,trabalho_equipe,organizacao,pontualidade,respeito_regras,faltas,missed_aulas,aula_extra,feedback_participacao,feedback_foco,feedback_trabalho_equipe,recomendacoes,observacao\n"
    "Chuck,MASTER,Masters,Book,Tue,Jane Doe,4,3,4,5,4,3,4,2,3,3,3,3,1,2,,,,,,\n"
    "Barbara,SPARK,Spark,Book,Tue,Bob Smith,4,3,4,5,4,3,4,2,3,3,3,3,1,2,,,,,,\n"
)


# ── store helpers ────────────────────────────────────────────────────────────


def test_photo_store_keys_by_pseudonym_not_name():
    rows = set_photo([], "MASTER", "Jane Doe", "image/png", PNG_B64)
    assert rows[0]["student_id"] == photo_key("MASTER", "Jane Doe")
    assert "Jane" not in json.dumps(rows)
    assert find_photo(rows, "MASTER", "jane doe ")["photo_mime"] == "image/png"
    assert photo_data_url(rows[0]).startswith("data:image/png;base64,")


def test_set_photo_replaces_existing():
    rows = set_photo([], "MASTER", "Jane Doe", "image/png", PNG_B64)
    rows = set_photo(rows, "MASTER", "Jane Doe", "image/jpeg", "abc")
    assert len(rows) == 1
    assert rows[0]["photo_mime"] == "image/jpeg"


def test_remove_photo_reports_whether_anything_changed():
    rows = set_photo([], "MASTER", "Jane Doe", "image/png", PNG_B64)
    rows, removed = remove_photo(rows, "MASTER", "Jane Doe")
    assert removed and rows == []
    _rows, removed = remove_photo(rows, "MASTER", "Jane Doe")
    assert not removed


def test_move_photo_follows_turma_change():
    rows = set_photo([], "TEENS_1", "Jane Doe", "image/png", PNG_B64)
    rows, moved = move_photo(rows, "TEENS_1", "Jane Doe", "TEENS_2", "Jane Doe")
    assert moved
    assert find_photo(rows, "TEENS_2", "Jane Doe")
    assert not find_photo(rows, "TEENS_1", "Jane Doe")


def test_move_photo_without_source_keeps_target_photo():
    rows = set_photo([], "TEENS_2", "Jane Doe", "image/png", PNG_B64)
    rows, moved = move_photo(rows, "TEENS_1", "Jane Doe", "TEENS_2", "Jane Doe")
    assert not moved
    assert find_photo(rows, "TEENS_2", "Jane Doe")


def test_database_store_student_photos_round_trip(tmp_path):
    store = DatabaseStore(f"sqlite:///{tmp_path / 'app.db'}")
    store.initialize()
    rows = set_photo([], "MASTER", "Jane Doe", "image/png", PNG_B64)
    version = store.save_student_photos(rows)
    loaded, loaded_version = store.load_student_photos_versioned()
    assert loaded == rows
    assert loaded_version == version


# ── report ───────────────────────────────────────────────────────────────────


def _report_student():
    return {
        "teacher": "Chuck", "turma": "MASTER", "turma_display": "Masters",
        "student_name": "Jane Doe", "speaking": "4", "listening": "4",
        "writing": "4", "reading": "4", "gramatica": "4", "participacao": "4",
        "foco": "4", "comportamento": "4", "faltas": "0",
    }


def test_report_embeds_photo_when_present(tmp_path):
    env = create_report_environment(web_app.TMPL_DIR)
    photos = set_photo([], "MASTER", "Jane Doe", "image/png", PNG_B64)
    generate_individual_reports([_report_student()], [], env, tmp_path, photos=photos)
    html = next(tmp_path.glob("*_report.html")).read_text(encoding="utf-8")
    assert 'class="student-photo"' in html
    assert f"data:image/png;base64,{PNG_B64}" in html


def test_report_without_photo_has_no_img(tmp_path):
    env = create_report_environment(web_app.TMPL_DIR)
    generate_individual_reports([_report_student()], [], env, tmp_path)
    html = next(tmp_path.glob("*_report.html")).read_text(encoding="utf-8")
    assert 'class="student-photo"' not in html


def test_report_shows_all_five_skills(tmp_path):
    env = create_report_environment(web_app.TMPL_DIR)
    generate_individual_reports([_report_student()], [], env, tmp_path)
    html = next(tmp_path.glob("*_report.html")).read_text(encoding="utf-8")
    for label in ("Fala", "Audição", "Leitura", "Escrita", "Gramática"):
        assert f'<span class="skill-label">{label}</span>' in html


# ── web routes ───────────────────────────────────────────────────────────────


def _setup(monkeypatch, tmp_path, csv_text=None):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "students.csv").write_text(csv_text or _students_csv(), encoding="utf-8")
    monkeypatch.setattr(web_app, "DATA_DIR", data_dir)
    monkeypatch.setattr(web_app, "OUT_DIR", tmp_path / "output")
    web_app.OUT_DIR.mkdir()
    store = UserStore(db_store=None, json_path=data_dir / "users.json")
    store.initialize()
    store.ensure_bootstrap_superadmin("admin@test.local", "testpass")
    store.create_teacher("chuck@test.local", "pass1234", "Chuck")
    monkeypatch.setattr(web_app, "user_store", store)
    return data_dir


def _upload(client, idx=0, data=PNG, name="face.png"):
    return client.post(
        f"/students/{idx}/photo",
        data={"photo": (io.BytesIO(data), name)},
        content_type="multipart/form-data",
    )


def test_upload_serves_and_lists_photo(monkeypatch, tmp_path):
    data_dir = _setup(monkeypatch, tmp_path)
    client = web_app.app.test_client()
    _login(client)

    response = _upload(client)
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/students/0/edit")

    served = client.get("/students/0/photo")
    assert served.status_code == 200
    assert served.mimetype == "image/png"
    assert served.data == PNG

    stored = (data_dir / "student_photos.json").read_text(encoding="utf-8")
    assert "Jane" not in stored

    listing = client.get("/students").get_data(as_text=True)
    assert "/students/0/photo?v=" in listing

    edit = client.get("/students/0/edit").get_data(as_text=True)
    assert "Foto atualizada" in edit
    assert "Remover foto" in edit


def test_upload_rejects_non_image(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    client = web_app.app.test_client()
    _login(client)

    _upload(client, data=b"not an image", name="x.txt")
    assert client.get("/students/0/photo").status_code == 404
    assert "JPG, PNG ou WebP" in client.get("/students/0/edit").get_data(as_text=True)


def test_clear_photo_removes_it(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    client = web_app.app.test_client()
    _login(client)
    _upload(client)

    client.post("/students/0/photo", data={"clear_photo": "1"})
    assert client.get("/students/0/photo").status_code == 404


def test_teacher_cannot_reach_other_teachers_student_photo(monkeypatch, tmp_path):
    data_dir = _setup(monkeypatch, tmp_path, TWO_TEACHERS_CSV)
    web_app._save_student_photos(
        set_photo([], "SPARK", "Bob Smith", "image/png", PNG_B64),
    )
    client = web_app.app.test_client()
    client.post("/login", data={"email": "chuck@test.local", "password": "pass1234"})

    # Chuck's only visible student is Jane (index 0); Bob is not addressable.
    assert client.get("/students/0/photo").status_code == 404
    assert client.get("/students/1/photo").status_code == 404
    assert _upload(client, idx=1).status_code == 404
    assert find_photo(json.loads((data_dir / "student_photos.json").read_text()), "SPARK", "Bob Smith")


def test_deleting_student_removes_photo(monkeypatch, tmp_path):
    data_dir = _setup(monkeypatch, tmp_path)
    client = web_app.app.test_client()
    _login(client)
    _upload(client)

    client.post("/students/0/delete")
    rows = json.loads((data_dir / "student_photos.json").read_text(encoding="utf-8"))
    assert rows == []


def test_renaming_student_keeps_photo(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "students.csv").write_text(_students_csv(), encoding="utf-8")
    monkeypatch.setattr(web_app, "DATA_DIR", data_dir)
    monkeypatch.setattr(web_app, "OUT_DIR", tmp_path / "output")
    web_app.OUT_DIR.mkdir()
    _init_teacher_store(monkeypatch, data_dir, teacher_name="Chuck")
    client = web_app.app.test_client()
    _login(client, email="teacher@test.local", password="teachpass")
    _upload(client)

    scores = {f: "3" for f in (
        "participacao", "comportamento", "speaking", "listening", "foco", "writing",
        "reading", "gramatica", "trabalho_equipe", "organizacao", "pontualidade",
        "respeito_regras",
    )}
    response = client.post("/students/0/edit", data={
        **scores,
        "teacher": "Chuck",
        "class_choice": "MASTER",
        "nivel": "TEENS 4",
        "student_name": "Jane Smith",
        "orig_student_name": "Jane Doe",
        "orig_turma": "MASTER",
        "faltas": "0",
    })
    assert response.status_code == 302

    rows = json.loads((data_dir / "student_photos.json").read_text(encoding="utf-8"))
    assert find_photo(rows, "MASTER", "Jane Smith")
    assert not find_photo(rows, "MASTER", "Jane Doe")
    assert client.get("/students/0/photo").data == PNG


def test_report_preview_shows_uploaded_photo(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    client = web_app.app.test_client()
    _login(client)
    _upload(client)

    # Preview re-renders from live data, so a report generated before the
    # upload still shows the new photo.
    (web_app.OUT_DIR / "MASTER_Jane_Doe_report.html").write_text("<html>old</html>", encoding="utf-8")
    html = client.get("/reports/preview/MASTER_Jane_Doe_report.html").get_data(as_text=True)
    assert 'class="student-photo"' in html
    assert f"data:image/png;base64,{PNG_B64}" in html
