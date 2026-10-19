"""Parse and normalize reforço / reposição / extra-class scheduling rows."""

import csv
import io
import re
from datetime import date as _date, datetime, timedelta, timezone
from pathlib import Path

from auth import normalize_teacher_name
from form_ui import capitalize_student_name, date_from_form, time_from_form

EXTRA_SESSION_FIELDS = [
    'teacher', 'student_name', 'turma', 'date', 'horario', 'turno',
    'session_type', 'assuntos', 'observacao', 'contatado', 'marcado', 'realizado',
    'assigned_teacher', 'motivo',
]

AUTO_AULA_EXTRA_MARKER = '__auto_aula_extra__'

EXTRA_SESSION_FIELD_LABELS = {
    'teacher': 'Professor',
    'student_name': 'Nome do aluno',
    'turma': 'Turma',
    'date': 'Data',
    'horario': 'Horário',
    'turno': 'Turno',
    'session_type': 'Tipo',
    'assuntos': 'Assuntos trabalhados',
    'motivo': 'Motivo / o que trabalhar',
    'observacao': 'Observação',
    'contatado': 'Contatado',
    'marcado': 'Marcado',
    'realizado': 'Realizado',
    'assigned_teacher': 'Professor da aula extra',
}

SESSION_TYPE_CHOICES = ('Reforço', 'Reposição', 'Nivelamento', 'Aula extra')

# Portuguese headers for CSV download / import (reference spreadsheet)
ATENDIMENTOS_CSV_HEADERS = [
    'Nome do aluno ou responsável',
    'Data',
    'Horário',
    'Assuntos trabalhados',
    'Observação',
    'Turno',
    'Contatado',
    'Marcado',
    'Realizado',
    'Professor',
]

# Portuguese headers from the reference spreadsheet
IMPORT_HEADER_MAP = {
    'nome do aluno ou responsável': 'student_name',
    'nome do aluno ou responsavel': 'student_name',
    'data': 'date',
    'horário': 'horario',
    'horario': 'horario',
    'assuntos trabalhados': 'assuntos',
    'observação': 'observacao',
    'observacao': 'observacao',
    'turno': 'turno',
    'contatado': 'contatado',
    'marcado': 'marcado',
    'realizado': 'realizado',
    'professor': 'teacher',
}


def _norm_header(value):
    return (value or '').strip().lower().replace('\ufeff', '')


def parse_session_type(assuntos):
    text = (assuntos or '').casefold()
    if 'nivelamento' in text or 'nivelamentos' in text:
        return 'Nivelamento'
    if 'reposição' in text or 'reposicao' in text or 'repos' in text:
        return 'Reposição'
    if 'aula extra' in text:
        return 'Aula extra'
    return 'Reforço'


_DASH_TURMA_RE = re.compile(
    r'\s+-\s+([A-Za-zÀ-ÿ]+(?:\s*-\s*[A-Za-z0-9]+)?)\s*$',
    re.IGNORECASE,
)


def parse_turma_from_student_name(student_name):
    """Extract turma hint from names like 'Ana (Comet - A)' or 'Ana - Power'."""
    name = (student_name or '').strip()
    match = re.search(r'\(([^)]+)\)\s*(?:\(\d+\))?$', name)
    if match:
        return match.group(1).strip()
    match = re.search(r'\(([^)]+)\)', name)
    if match:
        return match.group(1).strip()
    match = _DASH_TURMA_RE.search(name)
    if match:
        return match.group(1).strip()
    return ''


def clean_student_display_name(student_name):
    """Remove trailing (2) session markers but keep turma in parentheses."""
    name = (student_name or '').strip()
    name = re.sub(r'\s*\(\d+\)\s*$', '', name)
    return capitalize_student_name(name.strip())


STATUS_OK = 'OK'
STATUS_NO = 'NÃO'

DEFAULT_ATENDIMENTOS_TEMPLATE_ROWS = [
    {
        'Nome do aluno ou responsável': 'Jane Doe (MASTER)',
        'Data': '10/02/2026',
        'Horário': '09:30',
        'Assuntos trabalhados': 'Reforço - revisão de vocabulário da última aula',
        'Observação': 'Substitua pelos dados reais do aluno.',
        'Turno': 'Manhã',
        'Contatado': STATUS_OK,
        'Marcado': STATUS_OK,
        'Realizado': '',
        'Professor': 'Chuck',
    },
    {
        'Nome do aluno ou responsável': 'John Smith (Comet - A)',
        'Data': '12/02/2026',
        'Horário': '14:00',
        'Assuntos trabalhados': 'Reposição - aula perdida (listening e speaking)',
        'Observação': '',
        'Turno': 'Tarde',
        'Contatado': STATUS_OK,
        'Marcado': STATUS_OK,
        'Realizado': STATUS_NO,
        'Professor': 'Amanda',
    },
]


def is_status_ok(value):
    return (value or '').strip().casefold() == 'ok'


def display_status(value):
    """User-facing label for status fields."""
    raw = (value or '').strip()
    if is_status_ok(raw):
        return STATUS_OK
    return raw


def normalize_status(value):
    raw = (value or '').strip()
    if not raw:
        return ''
    low = raw.casefold()
    if low in ('ok', 'sim', 's', 'yes', 'y'):
        return STATUS_OK
    if low in ('não', 'nao', 'n', 'no', 'faltou', 'cancelado'):
        return STATUS_NO
    return raw


def coerce_session_status_fields(row):
    """Normalize legacy lowercase ok in stored rows."""
    for field in ('contatado', 'marcado', 'realizado'):
        if field in row and is_status_ok(row.get(field)):
            row[field] = STATUS_OK
    return row


def student_name_for_csv(row):
    """Format name for spreadsheet import (turma in parentheses when helpful)."""
    name = (row.get('student_name') or '').strip()
    turma = (row.get('turma') or '').strip()
    if turma and f'({turma})' not in name:
        return f'{name} ({turma})' if name else turma
    return name


def internal_row_to_csv_row(row):
    """Map internal storage fields to Portuguese CSV columns."""
    out = {header: '' for header in ATENDIMENTOS_CSV_HEADERS}
    out['Nome do aluno ou responsável'] = student_name_for_csv(row)
    out['Data'] = (row.get('date') or '').strip()
    out['Horário'] = (row.get('horario') or '').strip()
    assuntos = (row.get('assuntos') or '').strip()
    session_type = (row.get('session_type') or '').strip()
    if session_type and session_type.casefold() not in assuntos.casefold():
        assuntos = f'{session_type} - {assuntos}' if assuntos else session_type
    out['Assuntos trabalhados'] = assuntos
    out['Observação'] = (row.get('observacao') or '').strip()
    out['Turno'] = (row.get('turno') or '').strip()
    out['Contatado'] = display_status(row.get('contatado', ''))
    out['Marcado'] = display_status(row.get('marcado', ''))
    out['Realizado'] = display_status(row.get('realizado', ''))
    out['Professor'] = (row.get('teacher') or '').strip()
    return out


def load_atendimentos_template_rows(template_dir):
    path = Path(template_dir) / 'atendimentos_template.csv'
    if path.exists():
        with open(path, newline='', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            rows = [dict(r) for r in reader if any((v or '').strip() for v in r.values())]
            if rows:
                return rows
    return [dict(r) for r in DEFAULT_ATENDIMENTOS_TEMPLATE_ROWS]


def build_atendimentos_template_csv(template_dir, teacher_name=None):
    """UTF-8 CSV with BOM for Excel; optional professor column prefill."""
    rows = load_atendimentos_template_rows(template_dir)
    if teacher_name:
        for row in rows:
            row['Professor'] = teacher_name
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=ATENDIMENTOS_CSV_HEADERS, extrasaction='ignore')
    writer.writeheader()
    writer.writerows(rows)
    return '\ufeff' + buf.getvalue()


def row_from_form(form):
    assuntos = form.get('assuntos', '').strip()
    session_type = form.get('session_type', '').strip() or parse_session_type(assuntos)
    student_name = clean_student_display_name(form.get('student_name', ''))
    turma = form.get('turma', '').strip() or parse_turma_from_student_name(student_name)
    return {
        'teacher': form.get('teacher', '').strip(),
        'student_name': student_name,
        'turma': turma,
        'date': date_from_form(form),
        'horario': time_from_form(form),
        'turno': form.get('turno', '').strip(),
        'session_type': session_type,
        'assuntos': assuntos,
        'observacao': form.get('observacao', '').strip(),
        'contatado': normalize_status(form.get('contatado', '')),
        'marcado': normalize_status(form.get('marcado', '')),
        'realizado': normalize_status(form.get('realizado', '')),
        'assigned_teacher': normalize_teacher_name(form.get('assigned_teacher', '')),
        'motivo': form.get('motivo', '').strip(),
    }


def _map_import_row(raw):
    mapped = {}
    for key, value in raw.items():
        if key is None:
            continue
        field = IMPORT_HEADER_MAP.get(_norm_header(key))
        if field:
            mapped[field] = (value or '').strip()
    if not mapped.get('student_name'):
        return None
    assuntos = mapped.get('assuntos', '')
    mapped['session_type'] = parse_session_type(assuntos)
    mapped['student_name'] = clean_student_display_name(mapped['student_name'])
    mapped['turma'] = parse_turma_from_student_name(mapped['student_name'])
    for flag in ('contatado', 'marcado', 'realizado'):
        mapped[flag] = normalize_status(mapped.get(flag, ''))
    for field in EXTRA_SESSION_FIELDS:
        mapped.setdefault(field, '')
    return coerce_session_status_fields(mapped)


def _dict_reader_skip_blank_header(text):
    """Teacher exports often start with an empty separator row before real headers."""
    lines = text.splitlines()
    while lines:
        reader = csv.DictReader(io.StringIO('\n'.join(lines)))
        if reader.fieldnames and any((name or '').strip() for name in reader.fieldnames):
            return reader
        lines = lines[1:]
    return csv.DictReader(io.StringIO(text))


def parse_import_csv(text):
    """Read spreadsheet export; returns list of row dicts."""
    reader = _dict_reader_skip_blank_header(text)
    if not reader.fieldnames:
        return [], ['CSV sem cabeçalho válido.']

    rows = []
    for raw in reader:
        if not any((v or '').strip() for v in raw.values() if v is not None):
            continue
        row = _map_import_row(raw)
        if row:
            rows.append(row)

    if not rows:
        return [], ['Nenhuma linha de atendimento encontrada no arquivo.']
    return rows, []


def load_reference_csv(path):
    """Load rows from the user's reference file path (for one-off import)."""
    return Path(path).read_text(encoding='utf-8-sig')


def normalize_aula_extra(value):
    """Canonical aula_extra flag: Reforço, Reposição, or empty."""
    raw = (value or '').strip()
    low = raw.casefold()
    if low in ('reforço', 'reforco'):
        return 'Reforço'
    if low in ('reposição', 'reposicao'):
        return 'Reposição'
    return ''


def is_auto_aula_extra_row(row):
    return (row.get('observacao') or '').strip() == AUTO_AULA_EXTRA_MARKER


def _student_identity_key(student_name='', turma='', teacher=''):
    name = _display_name_key(student_name)
    return (
        name,
        (turma or '').strip().upper(),
        normalize_teacher_name(teacher).casefold(),
    )


def _display_name_key(name):
    cleaned = clean_student_display_name(name).casefold()
    if ' (' in cleaned:
        cleaned = cleaned.split(' (', 1)[0].strip()
    cleaned = _DASH_TURMA_RE.sub('', cleaned).strip()
    return cleaned


def _turma_head(value):
    text = (value or '').strip().casefold()
    if not text:
        return ''
    return re.split(r'[\s\-]+', text, maxsplit=1)[0]


def _turmas_compatible(row, student):
    """Match extra-session turma to a student code or display name.

    Spreadsheet imports store labels like 'Comet - A' or 'Power - C' while the
    roster uses codes such as COMET / POWER plus turma_display 'Comet' / 'Power'.
    """
    extra = (row.get('turma') or '').strip().casefold()
    if not extra:
        extra = parse_turma_from_student_name(row.get('student_name', '')).casefold()
    code = (student.get('turma') or '').strip().casefold()
    display = (student.get('turma_display') or '').strip().casefold()
    if not extra or not code:
        return True
    if extra == code or (display and extra == display):
        return True
    for token in (code, display):
        if not token:
            continue
        if extra.startswith(token + ' ') or extra.startswith(token + '-') or extra.startswith(token + ' -'):
            return True
    extra_head = _turma_head(extra)
    if extra_head and extra_head in {_turma_head(code), _turma_head(display)}:
        return True
    return False


def _teachers_compatible(row, student):
    """Imported rows often omit Professor; treat blank as a wildcard."""
    row_teacher = normalize_teacher_name(row.get('teacher', '')).casefold()
    student_teacher = normalize_teacher_name(student.get('teacher', '')).casefold()
    if not row_teacher or not student_teacher:
        return True
    return row_teacher == student_teacher


def _row_matches_student(row, student):
    if _display_name_key(row.get('student_name')) != _display_name_key(student.get('student_name')):
        return False
    if not _teachers_compatible(row, student):
        return False
    # Prefer matching on turma when both sides declare one — two students with
    # the same name under the same teacher but different turmas must not mix.
    return _turmas_compatible(row, student)


def filter_sessions_for_teacher(sessions, teacher_name, students):
    """Teacher sees their students' sessions, sessions assigned to them, and unowned rows for their roster."""
    key = normalize_teacher_name(teacher_name).casefold()
    if not key:
        return []
    owned = list(students or [])
    visible = []
    for row in sessions or []:
        row_teacher = normalize_teacher_name(row.get('teacher', '')).casefold()
        assigned = normalize_teacher_name(row.get('assigned_teacher', '')).casefold()
        if key in (row_teacher, assigned):  # their student's request, or a class they were given
            visible.append(row)
            continue
        if row_teacher:
            continue
        if any(_row_matches_student(row, student) for student in owned):
            visible.append(row)
    return visible


def remove_sessions_for_student(rows, student):
    return [row for row in rows or [] if not _row_matches_student(row, student)]


def has_open_session_for_student(rows, student, session_type):
    """True when a pending (not completed) session exists for this student and type."""
    target = (session_type or '').strip()
    for row in rows:
        if not _row_matches_student(row, student):
            continue
        if (row.get('session_type') or '').strip() != target:
            continue
        if is_status_ok(row.get('realizado')):
            continue
        return True
    return False


def pending_session_type_for_student(rows, student):
    """Canonical Reforço/Reposição if this student has a pending extra session."""
    found = ''
    for row in rows or []:
        if not _row_matches_student(row, student):
            continue
        if is_status_ok(row.get('realizado')):
            continue
        session_type = normalize_aula_extra(row.get('session_type'))
        if not session_type:
            continue
        if session_type == 'Reposição':
            return 'Reposição'
        found = session_type
    return found


def apply_open_extra_sessions_to_students(students, session_rows):
    """Normalize aula_extra and overlay pending extra sessions onto the roster.

    Monthly reviews start blank each month, so kids with an open reforço or
    reposição would otherwise disappear from the Alunos filter.
    """
    out = []
    for student in students or []:
        row = dict(student)
        flagged = normalize_aula_extra(row.get('aula_extra'))
        if flagged:
            row['aula_extra'] = flagged
        else:
            overlay = pending_session_type_for_student(session_rows, student)
            if overlay:
                row['aula_extra'] = overlay
        out.append(row)
    return out


def apply_pending_session_flag_to_students(students, session_row):
    """Write aula_extra from an extra session: set when pending, clear when done."""
    if is_status_ok(session_row.get('realizado')):
        return clear_aula_extra_after_completed_session(students, session_row)
    session_type = normalize_aula_extra(session_row.get('session_type'))
    if not session_type:
        return students
    out = []
    changed = False
    for student in students or []:
        row = dict(student)
        if _row_matches_student(session_row, student):
            current = normalize_aula_extra(row.get('aula_extra'))
            if not current:
                row['aula_extra'] = session_type
                changed = True
        out.append(row)
    return out if changed else students


def student_row_from_aula_extra_flag(student):
    """Build a pending extra-session row from a flagged student."""
    session_type = normalize_aula_extra(student.get('aula_extra'))
    if not session_type:
        return None
    name = (student.get('student_name') or '').strip()
    turma = (student.get('turma') or '').strip()
    display_name = f'{name} ({turma})' if turma and f'({turma})' not in name else name
    return coerce_session_status_fields({
        'teacher': (student.get('teacher') or '').strip(),
        'student_name': clean_student_display_name(display_name),
        'turma': turma,
        'date': '',
        'horario': '',
        'turno': '',
        'session_type': session_type,
        'assuntos': session_type,
        'observacao': AUTO_AULA_EXTRA_MARKER,
        'contatado': '',
        'marcado': '',
        'realizado': '',
    })


def sync_student_extra_sessions(all_rows, student):
    """Create or remove auto-synced rows when a student's aula_extra flag changes."""
    session_type = normalize_aula_extra(student.get('aula_extra'))
    # Drop only unscheduled auto requests; once the coordination set a date or a
    # teacher, the row is a real appointment and must survive later saves.
    kept = [
        row for row in all_rows
        if not (is_auto_aula_extra_row(row) and _row_matches_student(row, student)
                and not is_scheduled(row))
    ]
    if not session_type:
        return kept
    if has_open_session_for_student(kept, student, session_type):
        return kept
    new_row = student_row_from_aula_extra_flag(student)
    if new_row:
        kept.append(new_row)
    return kept


def reconcile_flagged_students(all_rows, students):
    """Ensure every Reforço/Reposição student has a pending extra-session row."""
    out = list(all_rows)
    for student in students:
        session_type = normalize_aula_extra(student.get('aula_extra'))
        if not session_type:
            continue
        if has_open_session_for_student(out, student, session_type):
            continue
        new_row = student_row_from_aula_extra_flag(student)
        if new_row:
            out.append(new_row)
    return out


def flagged_students_without_session(students, session_rows):
    """Students flagged for extra help who still lack an open session row."""
    pending = []
    for student in students:
        session_type = normalize_aula_extra(student.get('aula_extra'))
        if not session_type:
            continue
        if has_open_session_for_student(session_rows, student, session_type):
            continue
        pending.append({
            'student_name': student.get('student_name', ''),
            'turma': student.get('turma', ''),
            'teacher': student.get('teacher', ''),
            'session_type': session_type,
        })
    return pending


def clear_aula_extra_after_completed_session(students, session_row):
    """Clear the student flag once an extra session is marked done."""
    if not is_status_ok(session_row.get('realizado')):
        return students
    out = []
    changed = False
    for student in students:
        row = dict(student)
        if _row_matches_student(session_row, student) and normalize_aula_extra(row.get('aula_extra')):
            row['aula_extra'] = ''
            changed = True
        out.append(row)
    return out if changed else students


def is_scheduled(row):
    """A date or an assigned teacher means the coordination already scheduled it."""
    return bool((row.get('date') or '').strip() or (row.get('assigned_teacher') or '').strip())


def is_awaiting_schedule(row):
    """Open request with no date yet: shows in the coordination's to-schedule list."""
    return not is_status_ok(row.get('realizado')) and not (row.get('date') or '').strip()


def class_teacher(row):
    """Who gives the extra class: the assigned teacher, else the student's own teacher."""
    return (row.get('assigned_teacher') or '').strip() or (row.get('teacher') or '').strip()


def schedule_session(row, assigned_teacher, date, horario='', turno=''):
    """Coordination assigns who gives the class and when; the booking counts as Marcado."""
    out = dict(row)
    out['assigned_teacher'] = normalize_teacher_name(assigned_teacher)
    out['date'] = date
    out['horario'] = horario
    if turno:
        out['turno'] = turno
    if out['assigned_teacher'] and date:
        out['marcado'] = STATUS_OK
    if out.get('realizado') == STATUS_NO:
        out['realizado'] = ''  # rescheduled after the student missed it
    return out


# Brazil has had no daylight saving since 2019, so a fixed offset is exact.
SCHOOL_TZ = timezone(timedelta(hours=-3))
_WEEKDAYS_PT = ('Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom')


def school_today():
    return datetime.now(SCHOOL_TZ).date()


def parse_session_date(value):
    """dd/mm/yyyy (or yyyy-mm-dd) → date; None when missing or partial."""
    text = (value or '').strip()
    for fmt in ('%d/%m/%Y', '%Y-%m-%d'):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def session_stage(row):
    """Where a row sits in the flow: requested → scheduled → done."""
    if is_status_ok(row.get('realizado')):
        return 'done'
    if is_awaiting_schedule(row):
        return 'requested'
    return 'scheduled'


def session_due_state(row, today=None):
    """For scheduled rows: missed (student did not come), past (result not recorded), today or upcoming."""
    if (row.get('realizado') or '').strip() == STATUS_NO:
        return 'missed'
    when = parse_session_date(row.get('date'))
    if when is None:
        return 'upcoming'
    today = today or school_today()
    if when < today:
        return 'past'
    return 'today' if when == today else 'upcoming'


def session_when(row):
    """'Qua, 15/10/2026 · 14:00' for display."""
    raw = (row.get('date') or '').strip()
    when = parse_session_date(raw)
    label = f'{_WEEKDAYS_PT[when.weekday()]}, {when.strftime("%d/%m/%Y")}' if when else raw
    horario = (row.get('horario') or '').strip()
    return f'{label} · {horario}' if label and horario else (label or horario)


def session_sort_key(row):
    return (parse_session_date(row.get('date')) or _date.max, (row.get('horario') or '').strip())


def display_student_name(row):
    """Student name without the '(TURMA)' suffix when the turma is shown next to it."""
    name = (row.get('student_name') or '').strip()
    if (row.get('turma') or '').strip():
        name = re.sub(r'\s*\([^()]*\)\s*$', '', name) or name
    return name


def session_reason(row):
    """Why the student needs the class (the request), never the auto marker or a bare type."""
    motivo = (row.get('motivo') or '').strip()
    if motivo:
        return motivo
    if is_status_ok(row.get('realizado')):
        return ''
    assuntos = (row.get('assuntos') or '').strip()
    return '' if assuntos == (row.get('session_type') or '').strip() else assuntos


def find_student_for_session(students, row):
    """The roster student a session row belongs to, or None."""
    for student in students or []:
        if _row_matches_student(row, student):
            return student
    return None


def _session_label(student):
    name = (student.get('student_name') or '').strip()
    turma = (student.get('turma') or '').strip()
    return f'{name} ({turma})' if turma else name


def _point_at_student(row, student):
    out = dict(row)
    out['student_name'] = _session_label(student)
    out['turma'] = (student.get('turma') or '').strip()
    out['teacher'] = normalize_teacher_name(student.get('teacher', ''))
    return out


def _row_is_aligned_with_student(row, student):
    """Exactly the student's current name, teacher and class (blank fields do not count)."""
    target = _point_at_student(row, student)
    return (
        _display_name_key(row.get('student_name')) == _display_name_key(target['student_name'])
        and normalize_teacher_name(row.get('teacher', '')).casefold() == target['teacher'].casefold()
        and (row.get('turma') or '').strip().casefold() == target['turma'].casefold()
    )


def move_open_sessions(rows, old_student, new_student):
    """A student was renamed or changed class/teacher: their open requests follow them."""
    out, changed = [], False
    for row in rows or []:
        if not is_status_ok(row.get('realizado')) and _row_matches_student(row, old_student) \
                and not _row_is_aligned_with_student(row, new_student):
            row = _point_at_student(row, new_student)
            changed = True
        out.append(row)
    return out if changed else rows


def realign_open_sessions(rows, students):
    """Point open requests at the student's current class and teacher.

    Returns (rows, orphans): rows is a new list only when something changed; orphans holds
    the indexes of open requests whose name matches no student in the roster (or several
    students with no way to tell them apart), for the coordination to review. Completed
    classes are history and are left untouched.
    """
    by_name = {}
    for student in students or []:
        by_name.setdefault(_display_name_key(student.get('student_name')), []).append(student)
    out, orphans, changed = [], set(), False
    for i, row in enumerate(rows or []):
        if not is_status_ok(row.get('realizado')):
            same_name = by_name.get(_display_name_key(row.get('student_name')), [])
            aligned = [s for s in same_name if _row_is_aligned_with_student(row, s)]
            if len(aligned) != 1:
                if len(same_name) == 1:
                    row = _point_at_student(row, same_name[0])
                    changed = True
                else:
                    orphans.add(i)
        out.append(row)
    drop = _duplicate_requests(out, orphans)
    if drop:
        keep = [i for i in range(len(out)) if i not in drop]
        position = {old: new for new, old in enumerate(keep)}
        return [out[i] for i in keep], {position[i] for i in orphans}
    return (out if changed else rows), orphans


def _duplicate_requests(rows, orphans):
    """Indexes of open requests that repeat another one for the same student and type.

    Only unscheduled requests are ever dropped, and only when their reason adds nothing:
    a booked class, or a request carrying its own reason, always stays.
    """
    groups = {}
    for i, row in enumerate(rows):
        if i in orphans or is_status_ok(row.get('realizado')):
            continue
        key = (_display_name_key(row.get('student_name')), (row.get('turma') or '').strip().casefold(),
               normalize_teacher_name(row.get('teacher', '')).casefold(), (row.get('session_type') or '').strip())
        groups.setdefault(key, []).append(i)
    drop = set()
    for members in groups.values():
        if len(members) < 2:
            continue
        # Keep a booked one if any, else the one with a reason, else the oldest.
        keeper = min(members, key=lambda i: (not is_scheduled(rows[i]), not (rows[i].get('motivo') or '').strip(), i))
        kept_reason = (rows[keeper].get('motivo') or '').strip()
        for i in members:
            reason = (rows[i].get('motivo') or '').strip()
            if i != keeper and not is_scheduled(rows[i]) and reason in ('', kept_reason):
                drop.add(i)
    return drop
