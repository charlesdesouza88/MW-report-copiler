from db_store import DatabaseStore, prepare_database_url

import pytest


def test_prepare_database_url_adds_ssl_for_postgres():
    url = prepare_database_url("postgres://user:pass@containers.railway.app:5432/railway")
    assert url.startswith("postgresql+psycopg2://")
    assert "sslmode=require" in url


def test_prepare_database_url_strips_prepended_db_name():
    broken = (
        "railwaypostgresql://postgres:pass@postgres.railway.internal:5432/railway"
    )
    url = prepare_database_url(broken)
    assert url.startswith("postgresql+psycopg2://postgres:pass@postgres.railway.internal:5432/railway")


def test_prepare_database_url_leaves_sqlite_untouched():
    url = "sqlite:////tmp/test.db"
    assert prepare_database_url(url) == url


def test_database_store_round_trip(tmp_path):
    db_path = tmp_path / "app.db"
    store = DatabaseStore(f"sqlite:///{db_path}")
    store.initialize()

    students = [
        {"student_name": "Jane Doe", "turma": "MASTER", "speaking": "4"},
        {"student_name": "John Doe", "turma": "MASTER", "speaking": "3"},
    ]
    lessons = [
        {"turma": "MASTER", "aula_num": "1", "date": "01/01", "licao_conteudo": "L1"}
    ]

    store.save_students(students)
    store.save_lessons(lessons)

    assert store.load_students() == students
    assert store.load_lessons() == lessons

    store.check_connection()


def test_database_store_teacher_classes_round_trip(tmp_path):
    db_path = tmp_path / "app.db"
    store = DatabaseStore(f"sqlite:///{db_path}")
    store.initialize()

    rows = [
        {
            'teacher': 'Chuck',
            'turma': 'MASTER',
            'turma_display': 'Masters',
            'semester_id': '2026-S1',
            'horario': 'Terça-feira e Sexta-feira 13:00 - 14:00',
        }
    ]
    version = store.save_teacher_classes(rows)
    loaded, loaded_version = store.load_teacher_classes_versioned()
    assert loaded == rows
    assert loaded_version == version


def test_database_store_rejects_stale_save(tmp_path):
    from db_store import StaleDataError

    db_path = tmp_path / "app.db"
    store = DatabaseStore(f"sqlite:///{db_path}")
    store.initialize()

    students = [{"student_name": "Jane Doe", "turma": "MASTER"}]
    _rows, version = store.load_students_versioned()
    assert version == 0

    store.save_students(students, expected_version=version)
    with pytest.raises(StaleDataError):
        store.save_students(students, expected_version=version)


def test_database_store_skips_corrupt_json_row(tmp_path, caplog):
    import json as json_mod

    from db_store import StudentRow

    db_path = tmp_path / "app.db"
    store = DatabaseStore(f"sqlite:///{db_path}")
    store.initialize()

    good = {"student_name": "Jane Doe", "turma": "MASTER"}
    store.save_students([good])

    with store.session() as session:
        session.add(StudentRow(row_order=99, data_json='{"broken":'))
        session.flush()

    loaded = store.load_students()
    assert loaded == [good]


def test_database_store_users_round_trip(tmp_path):
    db_path = tmp_path / "app.db"
    store = DatabaseStore(f"sqlite:///{db_path}")
    store.initialize()

    users = [
        {
            "id": 1,
            "email": "admin@test.local",
            "password_hash": "hash",
            "role": "superadmin",
            "teacher_name": "",
            "active": True,
        },
        {
            "id": 2,
            "email": "teacher@test.local",
            "password_hash": "hash2",
            "role": "teacher",
            "teacher_name": "Chuck",
            "active": True,
        },
    ]
    store.save_users(users)
    assert store.load_users() == users
