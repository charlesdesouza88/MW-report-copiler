"""Teachers see Portuguese error pages (not Flask's English defaults) for oversized uploads and crashes."""

import io

import app as web_app
from test_app import _init_teacher_store, _login, _students_csv


def _client(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "students.csv").write_text(_students_csv(), encoding="utf-8")
    monkeypatch.setattr(web_app, "DATA_DIR", data_dir)
    monkeypatch.setattr(web_app, "OUT_DIR", tmp_path / "output")
    web_app.OUT_DIR.mkdir()
    _init_teacher_store(monkeypatch, data_dir, teacher_name="Chuck")
    client = web_app.app.test_client()
    _login(client, email="teacher@test.local", password="teachpass")
    return client


def test_oversized_upload_shows_friendly_limit(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    monkeypatch.setitem(web_app.app.config, "MAX_CONTENT_LENGTH", 1024 * 1024)
    big = io.BytesIO(b"x" * (2 * 1024 * 1024))
    resp = client.post("/students/0/photo", data={"photo": (big, "foto.jpg")})
    assert resp.status_code == 413
    html = resp.get_data(as_text=True)
    assert "Arquivo muito grande" in html and "1 MB" in html


def test_server_error_page_is_portuguese_and_json_for_autosave(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    monkeypatch.setitem(web_app.app.config, "PROPAGATE_EXCEPTIONS", False)

    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(web_app, "_scoped_students", boom)
    page = client.get("/students")
    assert page.status_code == 500
    assert "Algo deu errado" in page.get_data(as_text=True)
    assert "boom" not in page.get_data(as_text=True)

    saved = client.post("/students/0/autosave", data={"student_name": "Jane Doe"},
                        headers={"Accept": "application/json"})
    assert saved.status_code == 500
    assert saved.get_json()["ok"] is False
