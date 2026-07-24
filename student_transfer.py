"""Move students between turmas (level progression) keeping full report history.

When a student advances a level (e.g. TEENS_1 -> TEENS_2) their identity keys
change, because monthly reviews and snapshots are keyed by (turma, student_id)
where student_id = hash(turma|name). This module rewrites those keys so the
history follows the student, and records every move in a transfer log so the
enrollment path stays traceable back to the first turma.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from auth import normalize_teacher_name
from report_periods import student_snapshot_id
from student_reviews import MONTHLY_REVIEW_FIELDS

logger = logging.getLogger(__name__)


def _turma_code(value):
    return (value or '').strip()


def _name_key(value):
    return (value or '').strip().casefold()


def load_transfer_log(path):
    if not path or not Path(path).exists():
        return []
    try:
        raw = json.loads(Path(path).read_text(encoding='utf-8'))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning('Could not read student transfer log %s: %s', path, exc)
        return []
    return raw if isinstance(raw, list) else []


def save_transfer_log(path, entries):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(
        json.dumps(entries, ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8',
    )


def transfers_for_student(entries, student_name, current_turma=None):
    """Log entries for one student, oldest first (their enrollment path)."""
    key = _name_key(student_name)
    rows = [e for e in entries or [] if _name_key(e.get('student_name')) == key]
    if current_turma:
        code = _turma_code(current_turma)
        # Follow the chain backwards from the current turma so students who
        # merely share a name in unrelated turmas don't mix histories.
        chain = []
        cursor = code
        for entry in reversed(rows):
            if _turma_code(entry.get('to_turma')) == cursor:
                chain.append(entry)
                cursor = _turma_code(entry.get('from_turma'))
        return list(reversed(chain))
    return rows


def _rekey_monthly_reviews(monthly_store, old_turma, new_turma, student_name):
    """Move every month row from the old identity to the new one."""
    old_sid = student_snapshot_id(old_turma, student_name)
    new_sid = student_snapshot_id(new_turma, student_name)
    old_prefix = f'{old_turma}|{old_sid}|'
    moved = 0
    for key in [k for k in monthly_store if k.startswith(old_prefix)]:
        month = key.rsplit('|', 1)[-1]
        new_key = f'{new_turma}|{new_sid}|{month}'
        if new_key in monthly_store:
            # Destination month already has data; keep it and drop the stale row.
            del monthly_store[key]
            continue
        row = monthly_store.pop(key)
        row = {
            'report_month': month,
            'turma': new_turma,
            'student_id': new_sid,
            **{field: (row.get(field) or '') for field in MONTHLY_REVIEW_FIELDS},
        }
        monthly_store[new_key] = row
        moved += 1
    return moved


def _rekey_snapshots(snapshot_store, old_turma, new_turma, student_name):
    """Move composite-score snapshots so trends survive the level change."""
    old_sid = student_snapshot_id(old_turma, student_name)
    new_sid = student_snapshot_id(new_turma, student_name)
    old_prefix = f'{old_turma}|{old_sid}|'
    moved = 0
    for key in [k for k in snapshot_store if k.startswith(old_prefix)]:
        month = key.rsplit('|', 1)[-1]
        new_key = f'{new_turma}|{new_sid}|{month}'
        if new_key in snapshot_store:
            del snapshot_store[key]
            continue
        row = dict(snapshot_store.pop(key))
        row['turma'] = new_turma
        row['student_id'] = new_sid
        snapshot_store[new_key] = row
        moved += 1
    return moved


def _update_extra_sessions(extra_rows, old_turma, old_teacher, student_name,
                           new_turma, new_teacher):
    name_key = _name_key(student_name)
    old_teacher_key = normalize_teacher_name(old_teacher).casefold()
    old_code = _turma_code(old_turma).upper()
    updated = 0
    for row in extra_rows or []:
        row_name = _name_key(row.get('student_name'))
        # Auto rows may render the name as "Name (TURMA)".
        if ' (' in row_name:
            row_name = row_name.split(' (', 1)[0].strip()
        if row_name != name_key:
            continue
        if normalize_teacher_name(row.get('teacher', '')).casefold() != old_teacher_key:
            continue
        row_code = _turma_code(row.get('turma')).upper()
        if row_code and old_code and row_code != old_code:
            continue
        row['turma'] = new_turma
        row['teacher'] = new_teacher
        updated += 1
    return updated


def transfer_students(students, selected_names, from_turma, dest,
                      monthly_store, snapshot_store, extra_rows,
                      log_entries, when=None):
    """Transfer the selected students of from_turma to the destination turma.

    dest: {'turma', 'turma_display', 'horario', 'teacher'}
    Mutates students / monthly_store / snapshot_store / extra_rows / log_entries
    in place. Returns (summary, error).
    """
    from_code = _turma_code(from_turma)
    to_code = _turma_code(dest.get('turma'))
    to_teacher = normalize_teacher_name(dest.get('teacher'))
    if not from_code or not to_code:
        return None, 'Selecione a turma de origem e a turma de destino.'
    if from_code == to_code:
        return None, 'A turma de destino deve ser diferente da turma de origem.'
    if not to_teacher:
        return None, 'A turma de destino precisa de um professor responsável.'

    wanted = {_name_key(n) for n in selected_names if _name_key(n)}
    if not wanted:
        return None, 'Selecione ao menos um aluno para transferir.'

    rows = [
        row for row in students
        if _turma_code(row.get('turma')) == from_code
        and _name_key(row.get('student_name')) in wanted
    ]
    if not rows:
        return None, 'Nenhum aluno selecionado foi encontrado na turma de origem.'

    # Refuse moves that would collide with a same-named student already there.
    existing_names = {
        _name_key(row.get('student_name'))
        for row in students
        if _turma_code(row.get('turma')) == to_code
    }
    conflicts = sorted(
        row.get('student_name', '') for row in rows
        if _name_key(row.get('student_name')) in existing_names
    )
    if conflicts:
        return None, (
            'Já existe aluno com o mesmo nome na turma de destino: '
            + ', '.join(conflicts)
        )

    timestamp = when or datetime.now(timezone.utc).strftime('%Y-%m-%d')
    transferred = []
    for row in rows:
        name = (row.get('student_name') or '').strip()
        old_teacher = (row.get('teacher') or '').strip()
        months_moved = _rekey_monthly_reviews(monthly_store, from_code, to_code, name)
        snapshots_moved = _rekey_snapshots(snapshot_store, from_code, to_code, name)
        extras_updated = _update_extra_sessions(
            extra_rows, from_code, old_teacher, name, to_code, to_teacher,
        )

        row['turma'] = to_code
        row['teacher'] = to_teacher
        if dest.get('turma_display'):
            row['turma_display'] = dest['turma_display']
        if dest.get('horario'):
            row['horario'] = dest['horario']

        log_entries.append({
            'date': timestamp,
            'student_name': name,
            'from_turma': from_code,
            'from_teacher': old_teacher,
            'to_turma': to_code,
            'to_teacher': to_teacher,
            'to_turma_display': (dest.get('turma_display') or to_code),
            'months_moved': months_moved,
            'snapshots_moved': snapshots_moved,
            'extra_sessions_updated': extras_updated,
        })
        transferred.append(name)

    return {
        'from_turma': from_code,
        'to_turma': to_code,
        'to_turma_display': dest.get('turma_display') or to_code,
        'to_teacher': to_teacher,
        'students': transferred,
        'count': len(transferred),
    }, None


def students_with_transfer_aliases(students, log_entries):
    """Roster plus pseudo-rows for past identities, for report-file matching.

    A student promoted TEENS_1 -> TEENS_2 keeps HTML reports on disk named
    with the old turma. Adding alias rows (old turma + current teacher) lets
    filename matching and teacher visibility keep working for those files.
    """
    if not log_entries:
        return list(students)
    by_name = {}
    for row in students:
        by_name.setdefault(_name_key(row.get('student_name')), row)
    out = list(students)
    seen = {
        (_turma_code(row.get('turma')), _name_key(row.get('student_name')))
        for row in students
    }
    for entry in log_entries:
        name = (entry.get('student_name') or '').strip()
        current = by_name.get(_name_key(name))
        if not current:
            continue
        old_code = _turma_code(entry.get('from_turma'))
        alias_key = (old_code, _name_key(name))
        if not old_code or alias_key in seen:
            continue
        seen.add(alias_key)
        out.append({
            'teacher': current.get('teacher', ''),
            'turma': old_code,
            'turma_display': old_code,
            'nivel': current.get('nivel', ''),
            'horario': '',
            'student_name': name,
            '_transfer_alias': True,
        })
    return out
