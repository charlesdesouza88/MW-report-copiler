"""Restore points: overwriting data in the database always leaves a way back."""

from datetime import timedelta

import pytest

import db_store
from db_store import DatabaseStore, backup_reason

JANE = {"student_name": "Jane Doe", "turma": "MASTER", "speaking": "4"}
JOHN = {"student_name": "John Doe", "turma": "MASTER", "speaking": "3"}


@pytest.fixture
def store(tmp_path):
    s = DatabaseStore(f"sqlite:///{tmp_path / 'app.db'}")
    s.initialize()
    return s


@pytest.fixture
def clock(monkeypatch):
    now = {"t": db_store._utcnow()}
    monkeypatch.setattr(db_store, "_utcnow", lambda: now["t"])

    def advance(**delta):
        now["t"] += timedelta(**delta)
    return advance


def _students_backups(store):
    return [b for b in store.list_backups() if b["store"] == "students"]


def test_removing_rows_always_keeps_a_restore_point(store, clock):
    store.save_students([JANE, JOHN])
    assert _students_backups(store) == []  # nothing to protect yet
    store.save_students([JANE, JOHN, {**JOHN, "student_name": "Ana"}])  # first change: auto point
    store.save_students([JANE])  # rows vanish within the interval: still kept
    backups = _students_backups(store)
    assert [b["reason"] for b in backups] == ["removal", "auto"]
    assert backups[0]["row_count"] == 3

    store.restore_backup(backups[0]["id"])
    assert len(store.load_students()) == 3


def test_edits_are_backed_up_at_most_every_interval(store, clock):
    store.save_students([JANE])
    for score in "12345":
        store.save_students([{**JANE, "speaking": score}])  # autosave-style edits
    assert len(_students_backups(store)) == 1
    clock(minutes=31)
    store.save_students([{**JANE, "speaking": "2"}])
    assert len(_students_backups(store)) == 2


def test_bulk_action_backs_up_each_store_once_with_its_reason(store, clock):
    store.save_students([JANE, JOHN])
    store.save_lessons([{"turma": "MASTER", "aula_num": "1"}])
    with backup_reason("Upload de CSV"):
        store.save_students([JOHN])
        store.save_students([JOHN, JANE])
        store.save_lessons([])
    reasons = [(b["store"], b["reason"], b["row_count"]) for b in store.list_backups()]
    assert reasons == [("lessons", "Upload de CSV", 1), ("students", "Upload de CSV", 2)]


def test_restore_keeps_the_current_data_as_its_own_restore_point(store, clock):
    store.save_students([JANE])
    with backup_reason("Upload de CSV"):
        store.save_students([JOHN])
    first = _students_backups(store)[0]
    store.restore_backup(first["id"])
    assert store.load_students() == [JANE]
    latest = _students_backups(store)[0]
    assert latest["reason"] == "restore" and latest["row_count"] == 1
    store.restore_backup(latest["id"])  # undo the restore
    assert store.load_students() == [JOHN]


def test_retention_keeps_recent_points_and_one_per_day(store, clock):
    store.save_students([JANE])
    for _ in range(40):  # 40 days, two points per day
        for _ in range(2):
            clock(hours=11)
            store.save_students([{**JANE, "speaking": str(len(store.list_backups()) % 5)}])
        clock(hours=2)
    backups = _students_backups(store)
    days = {b["created_at"][:10] for b in backups}
    assert len(backups) <= db_store.BACKUP_KEEP_RECENT + db_store.BACKUP_KEEP_DAYS + 1
    assert len(days) >= db_store.BACKUP_KEEP_DAYS - 1


def test_photos_only_backed_up_before_one_disappears_and_capped(store, clock):
    photo = {"turma": "MASTER", "student_name": "Jane Doe", "photo_base64": "x" * 1000}
    store.save_student_photos([photo])
    clock(hours=1)
    store.save_student_photos([{**photo, "photo_base64": "y"}])  # replaced: not copied
    assert [b for b in store.list_backups() if b["store"] == "student_photos"] == []
    for i in range(6):
        store.save_student_photos([photo, {**photo, "student_name": f"K{i}"}])
        store.save_student_photos([photo])
    photo_points = [b for b in store.list_backups() if b["store"] == "student_photos"]
    assert len(photo_points) == db_store.BACKUP_PHOTO_KEEP


def test_login_events_are_not_backed_up(store, clock):
    store.save_login_events([{"email": "a"}, {"email": "b"}])
    store.save_login_events([])
    assert store.list_backups() == []


def test_export_has_every_store_and_no_password_hashes(store):
    store.save_students([JANE])
    store.save_users([{"email": "a@b.c", "password_hash": "secret-hash", "role": "teacher",
                       "teacher_name": "Chuck"}])
    data = store.export_all()
    assert set(DatabaseStore._STORE_NAMES.values()) | {"users"} == set(data)
    assert data["students"] == [JANE]
    assert data["users"][0]["email"] == "a@b.c"
    assert "password_hash" not in data["users"][0]


def test_one_bulk_action_can_be_undone_as_a_whole(store, clock):
    store.save_students([JANE, JOHN])
    store.save_lessons([{"turma": "MASTER", "aula_num": "1"}])
    with backup_reason("Transferência de turma"):
        store.save_students([JOHN])
        clock(seconds=3)  # a slow action still shares one timestamp
        store.save_lessons([])
    points = [b for b in store.list_backups() if b["reason"] == "Transferência de turma"]
    assert len({b["created_at"] for b in points}) == 1
    restored = store.restore_backups([b["id"] for b in points])
    assert sorted(restored) == [("lessons", 1), ("students", 2)]
    assert store.load_students() == [JANE, JOHN]
    assert len(store.load_lessons()) == 1
    with pytest.raises(ValueError):
        store.restore_backups([points[0]["id"], points[0]["id"]])
