"""Shared date/time picker helpers (calendar + clock inputs ↔ DD/MM storage)."""

import re
import unicodedata
from datetime import datetime

_ISO_DATE = re.compile(r'^(\d{4})-(\d{2})-(\d{2})$')
_STORAGE_DATE = re.compile(r'^(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?$')
_TIME = re.compile(r'^(\d{1,2}):(\d{2})')

# Lowercase particles kept mid-name (Portuguese / common Romance forms).
_NAME_PARTICLES = frozenset({
    'a', 'as', 'o', 'os', 'e', 'da', 'das', 'de', 'do', 'dos',
    'del', 'di', 'du', 'la', 'le', 'van', 'von', 'y',
})


def capitalize_student_name(name):
    """Title-case a student name, keeping particles like 'da'/'de' lowercase.

    Parenthetical suffixes (e.g. turma hints) are left unchanged.
    """
    text = ' '.join(str(name or '').split())
    if not text:
        return ''

    paren = ''
    match = re.search(r'(\s*\([^)]*\))\s*$', text)
    if match:
        paren = match.group(1)
        text = text[:match.start()].rstrip()
        if not text:
            return (name or '').strip()

    words = [
        _capitalize_name_token(token, first=(i == 0))
        for i, token in enumerate(text.split(' '))
    ]
    return ' '.join(words) + paren


def _capitalize_name_token(token, first=False):
    if '-' in token:
        parts = token.split('-')
        return '-'.join(
            _capitalize_name_token(part, first=(first and i == 0))
            for i, part in enumerate(parts)
        )
    for sep in ("'", '’'):
        if sep in token:
            head, *tail = token.split(sep)
            return sep.join(
                [_capitalize_name_token(head, first=first)]
                + [_capitalize_word(part) if part else part for part in tail]
            )
    folded = token.casefold()
    if not first and folded in _NAME_PARTICLES:
        return folded
    return _capitalize_word(token)


def _capitalize_word(word):
    if not word:
        return word
    return word[0].upper() + word[1:].casefold()


def parse_storage_date(value):
    """
    Normalize a date to DD/MM/YYYY (Brazilian day-first).
    Accepts DD/MM, DD/MM/YYYY, DD.MM.YYYY, or YYYY-MM-DD. Returns '' if invalid.
    """
    raw = (value or '').strip().replace('.', '/')
    if not raw:
        return ''

    iso_match = _ISO_DATE.match(raw)
    if iso_match:
        year, month, day = iso_match.group(1), iso_match.group(2), iso_match.group(3)
        return f'{int(day):02d}/{int(month):02d}/{year}'

    match = _STORAGE_DATE.match(raw)
    if not match:
        return ''

    day_s, month_s, year_s = match.group(1), match.group(2), match.group(3) or ''
    try:
        day, month = int(day_s), int(month_s)
    except ValueError:
        return ''
    if not (1 <= day <= 31 and 1 <= month <= 12):
        return ''

    if year_s:
        year = int(year_s)
        if len(year_s) == 2:
            year = 2000 + year if year < 100 else year
    else:
        year = datetime.now().year

    return f'{day:02d}/{month:02d}/{year:04d}'


def format_date_for_input(value):
    """Display value for Brazilian date fields (DD/MM/YYYY)."""
    return parse_storage_date(value)


def storage_date_to_iso(value):
    """Convert stored DD/MM or DD/MM/YYYY to YYYY-MM-DD (internal use)."""
    parsed = parse_storage_date(value)
    if not parsed:
        return ''

    match = _STORAGE_DATE.match(parsed)
    if not match:
        return ''

    day, month, year = match.group(1), match.group(2), match.group(3)
    return f'{int(year):04d}-{int(month):02d}-{int(day):02d}'


def iso_date_to_storage(iso_value):
    """Convert YYYY-MM-DD to DD/MM/YYYY for CSV storage."""
    return parse_storage_date(iso_value) or (iso_value or '').strip()


def storage_time_to_input(value):
    """Convert stored time text to HH:MM for <input type=\"time\">."""
    raw = (value or '').strip()
    if not raw:
        return ''

    match = _TIME.search(raw)
    if not match:
        return ''

    return f'{int(match.group(1)):02d}:{match.group(2)}'


def time_input_to_storage(input_value):
    """Normalize clock input to HH:MM."""
    raw = (input_value or '').strip()
    if not raw:
        return ''

    match = _TIME.match(raw)
    if not match:
        return raw

    return f'{int(match.group(1)):02d}:{match.group(2)}'


def date_from_form(form, picker_field='date_picker'):
    """Read date field and return storage string DD/MM/YYYY (day before month)."""
    picker = (form.get(picker_field) or '').strip()
    if picker:
        parsed = parse_storage_date(picker)
        if parsed:
            return parsed

    if picker_field == 'date_picker':
        legacy = (form.get('date') or '').strip()
        if legacy:
            parsed = parse_storage_date(legacy)
            if parsed:
                return parsed

    return ''


WEEKDAY_CHOICES = (
    'Segunda-feira',
    'Terça-feira',
    'Quarta-feira',
    'Quinta-feira',
    'Sexta-feira',
    'Sábado',
    'Domingo',
)


def is_valid_weekday(weekday):
    return (weekday or '').strip() in WEEKDAY_CHOICES


def normalize_weekdays(weekdays):
    """Return up to two valid, distinct weekdays in form order."""
    if isinstance(weekdays, str):
        weekdays = [weekdays] if weekdays else []
    out = []
    for raw in weekdays:
        day = (raw or '').strip()
        if not day or not is_valid_weekday(day):
            continue
        if day not in out:
            out.append(day)
    return out[:2]


def format_weekdays_label(weekdays):
    days = normalize_weekdays(weekdays)
    if not days:
        return ''
    if len(days) == 1:
        return days[0]
    return f'{days[0]} e {days[1]}'


def format_class_time_range(time_start='', time_end='', class_time=''):
    """Clock range for storage/display (e.g. 19:00 - 20:00)."""
    start = (time_start or '').strip()
    end = (time_end or '').strip()
    legacy = (class_time or '').strip()
    if not start and legacy:
        start, end = parse_time_range_from_horario(legacy) if ' - ' in legacy else (legacy, '')
    if start and end:
        return f'{start} - {end}'
    return start or end


def parse_time_range_from_horario(horario):
    """Extract start/end HH:MM from text like 'Terça e quinta, 19:00 - 20:00'."""
    raw = (horario or '').strip()
    match = re.search(r'(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})', raw)
    if not match:
        return '', ''
    return (
        time_input_to_storage(match.group(1)),
        time_input_to_storage(match.group(2)),
    )


def format_class_schedule(weekdays=None, time_start='', time_end='', class_time=''):
    """Human-readable schedule line for turma registry (two weekdays + time range)."""
    if weekdays is None:
        weekdays = []
    day_part = format_weekdays_label(weekdays)
    time_part = format_class_time_range(time_start, time_end, class_time)
    if day_part and time_part:
        return f'{day_part} {time_part}'
    return day_part or time_part


def turma_code_from_display(name):
    """Stable turma id from the teacher's class name (e.g. Turma terça → TURMA_TERCA)."""
    raw = (name or '').strip()
    if not raw:
        return ''
    normalized = unicodedata.normalize('NFD', raw)
    ascii_name = ''.join(c for c in normalized if unicodedata.category(c) != 'Mn')
    code = re.sub(r'[^A-Za-z0-9]+', '_', ascii_name).strip('_').upper()
    return code[:48] or 'TURMA'


def time_from_form(form, field='horario'):
    return time_input_to_storage(form.get(field) or '')


NIVEL_CHOICES = (
    'KIDS 1',
    'KIDS 2',
    'KIDS 3',
    'KIDS 4',
    'TEENS 1',
    'TEENS 2',
    'TEENS 3',
    'TEENS 4',
    'TEENS 5',
)


def is_valid_nivel(nivel):
    return (nivel or '').strip() in NIVEL_CHOICES


def turma_code_from_nivel(nivel):
    """Stable turma id for a standard level (e.g. KIDS 1 → KIDS_1)."""
    return (nivel or '').strip().replace(' ', '_')


HABILIDADES_CHOICES = (
    'Nenhuma',
    'Liderança',
    'Empreendedorismo',
    'Educação financeira',
    'Inteligência emocional',
    'Inteligência Artificial',
)

LICAO_ESPECIAL_CHOICES = (
    'Aula Dinâmica',
    'Revisão',
)

LICAO_CONTEUDO_CHOICES = LICAO_ESPECIAL_CHOICES + tuple(
    f'Lição {n}' for n in range(1, 101)
)

_LICAO_NUMBER = re.compile(
    r'^(?:lesson|licao|lição|liçao)\s*(\d+)$',
    re.IGNORECASE,
)


def _fold_text(value):
    text = unicodedata.normalize('NFKD', (value or '').strip())
    return ''.join(ch for ch in text if not unicodedata.combining(ch)).casefold()


_HABILIDADES_ALIASES = {
    'ia': 'Inteligência Artificial',
    'inteligencia artificial': 'Inteligência Artificial',
    'empreendedorismo': 'Empreendedorismo',
    'inteligencia emocional': 'Inteligência emocional',
    'educacao financeira': 'Educação financeira',
    'financas': 'Educação financeira',
    'lideranca': 'Liderança',
}


def normalize_habilidades(value):
    """Map known aliases to canonical HABILIDADES_CHOICES; preserve unknown legacy text."""
    raw = (value or '').strip()
    if not raw:
        return ''
    if raw in HABILIDADES_CHOICES:
        return raw
    folded = _fold_text(raw)
    if folded in _HABILIDADES_ALIASES:
        return _HABILIDADES_ALIASES[folded]
    for choice in HABILIDADES_CHOICES:
        if _fold_text(choice) == folded:
            return choice
    return raw


def licao_choice_for_value(value):
    """Match stored licao_conteudo to a dropdown choice when possible; else return raw legacy value."""
    raw = (value or '').strip()
    if not raw:
        return ''
    if raw in LICAO_CONTEUDO_CHOICES:
        return raw
    folded = _fold_text(raw)
    if folded in ('revisao', 'review'):
        return 'Revisão'
    if folded in ('aula dinamica',):
        return 'Aula Dinâmica'
    if raw.isdigit():
        num = int(raw)
        if 1 <= num <= 100:
            return f'Lição {num}'
    match = _LICAO_NUMBER.match(raw)
    if match:
        num = int(match.group(1))
        if 1 <= num <= 100:
            return f'Lição {num}'
    return raw


def _parse_aula_num(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def next_aula_num(lessons, turma):
    """Return str(max numeric aula_num for turma) + 1, or '1' if none."""
    turma_key = (turma or '').strip().upper()
    max_num = 0
    for row in lessons:
        if (row.get('turma') or '').strip().upper() != turma_key:
            continue
        num = _parse_aula_num(row.get('aula_num'))
        if num is not None and num > max_num:
            max_num = num
    return str(max_num + 1) if max_num else '1'


def suggest_licao_conteudo(aula_num):
    """Default lição label for a new aula number (Lição N when 1–100)."""
    num = _parse_aula_num(aula_num)
    if num is not None and 1 <= num <= 100:
        return f'Lição {num}'
    return ''


def turma_next_aula_map(lessons, turmas):
    """Map each turma code to its suggested next aula_num (for form JS). Keys are uppercase."""
    return {
        (t or '').strip().upper(): next_aula_num(lessons, t)
        for t in turmas if t
    }
