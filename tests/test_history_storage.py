"""Trends (monthly snapshots) and the transfer log live in the database when one is configured."""

import json

import app as web_app
from db_store import DatabaseStore
from report_periods import student_snapshot_id


def _snapshot(month, turma="MASTER", name="Jane Doe", score=4):
    return {
        "report_month": month,
        "turma": turma,
        "student_id": student_snapshot_id(turma, name),
        "composite_score": score,
        "dev_overall": score,
        "part_overall": score,
        "comp_overall": score,
        "pres_score": score,
    }


def _transfer(name="Jane Doe"):
    return {
        "date": "2026-09-01", "student_name": name,
        "from_turma": "TEENS_1", "from_teacher": "Chuck",
        "to_turma": "TEENS_2", "to_teacher": "Paula", "to_turma_display": "Teens 2",
        "months_moved": 1, "snapshots_moved": 1, "extra_sessions_updated": 0,
    }


def _db_mode(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    store = DatabaseStore(f"sqlite:///{tmp_path / 'app.db'}")
    store.initialize()
    monkeypatch.setattr(web_app, "DATA_DIR", data_dir)
    monkeypatch.setattr(web_app, "SNAPSHOTS_PATH", data_dir / "student_snapshots.json")
    monkeypatch.setattr(web_app, "db_store", store)
    return store, data_dir


def test_database_store_round_trips_snapshots_and_transfers(tmp_path):
    store = DatabaseStore(f"sqlite:///{tmp_path / 'app.db'}")
    store.initialize()
    rows = [_snapshot("2026-08")]
    version = store.save_student_snapshots(rows)
    assert store.load_student_snapshots_versioned() == (rows, version)
    log = [_transfer()]
    version = store.save_student_transfers(log)
    assert store.load_student_transfers_versioned() == (log, version)


def test_snapshots_saved_to_database_not_disk(monkeypatch, tmp_path):
    store, data_dir = _db_mode(monkeypatch, tmp_path)
    with web_app.app.test_request_context():
        snaps = web_app._load_snapshot_store()
        assert snaps == {}
        row = _snapshot("2026-08")
        snaps[f"MASTER|{row['student_id']}|2026-08"] = row
        assert web_app._save_snapshot_store(snaps)
    assert not (data_dir / "student_snapshots.json").exists()
    rows, _ = store.load_student_snapshots_versioned()
    assert rows == [row]
    with web_app.app.test_request_context():
        assert list(web_app._load_snapshot_store().values()) == [row]


def test_transfer_log_saved_to_database_not_disk(monkeypatch, tmp_path):
    store, data_dir = _db_mode(monkeypatch, tmp_path)
    with web_app.app.test_request_context():
        assert web_app._load_transfer_log() == []
        assert web_app._save_transfer_log([_transfer()])
    assert not (data_dir / "student_transfers.json").exists()
    with web_app.app.test_request_context():
        assert web_app._load_transfer_log() == [_transfer()]


def test_existing_files_are_imported_once(monkeypatch, tmp_path):
    """Trends/transfers written to disk before the move to Postgres are kept."""
    store, data_dir = _db_mode(monkeypatch, tmp_path)
    (data_dir / "student_snapshots.json").write_text(
        json.dumps([_snapshot("2026-07"), _snapshot("2026-08")]), encoding="utf-8",
    )
    (data_dir / "student_transfers.json").write_text(json.dumps([_transfer()]), encoding="utf-8")

    with web_app.app.test_request_context():
        assert len(web_app._load_snapshot_store()) == 2
        assert web_app._load_transfer_log() == [_transfer()]
    assert len(store.load_student_snapshots_versioned()[0]) == 2
    assert store.load_student_transfers_versioned()[0] == [_transfer()]

    # Once the database has been written, later file contents are ignored.
    with web_app.app.test_request_context():
        assert web_app._save_transfer_log([])
    (data_dir / "student_transfers.json").write_text(json.dumps([_transfer("Other")]), encoding="utf-8")
    with web_app.app.test_request_context():
        assert web_app._load_transfer_log() == []


def test_generation_records_trend_snapshot_in_database(monkeypatch, tmp_path):
    store, data_dir = _db_mode(monkeypatch, tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    monkeypatch.setattr(web_app, "OUT_DIR", out_dir)
    student = {
        "teacher": "Chuck", "turma": "MASTER", "turma_display": "Masters",
        "student_name": "Jane Doe", "speaking": "4", "listening": "4", "writing": "4",
        "reading": "4", "gramatica": "4", "participacao": "4", "foco": "4",
        "comportamento": "4", "faltas": "0",
    }
    lessons = [{"turma": "MASTER", "aula_num": "1", "date": "05/01/2026",
                "licao_conteudo": "L1", "atividade_extra": "", "habilidades": ""}]
    with web_app.app.test_request_context():
        web_app._run_report_generation([student], lessons, "2026-01")
    rows, _ = store.load_student_snapshots_versioned()
    assert [r["report_month"] for r in rows] == ["2026-01"]
    assert rows[0]["student_id"] == student_snapshot_id("MASTER", "Jane Doe")
    assert not (data_dir / "student_snapshots.json").exists()
