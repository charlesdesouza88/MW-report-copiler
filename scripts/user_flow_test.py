#!/usr/bin/env python3
"""End-to-end admin user flow (in-process or live server).

Usage:
  .venv/bin/python scripts/user_flow_test.py              # Flask test client + temp data
  .venv/bin/python scripts/user_flow_test.py http://127.0.0.1:5001
"""

from __future__ import annotations

import os
import re
import sys
import tempfile
from html.parser import HTMLParser
from pathlib import Path
from typing import ClassVar

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app as web_app
from auth import UserStore

STUDENTS_CSV = (
    'teacher,turma,turma_display,nivel,horario,student_name,participacao,comportamento,'
    'speaking,listening,foco,writing,reading,gramatica,trabalho_equipe,organizacao,'
    'pontualidade,respeito_regras,faltas,missed_aulas,aula_extra,feedback_participacao,'
    'feedback_foco,feedback_trabalho_equipe,recomendacoes,observacao\n'
    'Chuck,MASTER,Masters,Adults Book 4,Tue 19:00,Jane Doe,4,3,4,5,4,3,4,2,3,3,3,3,1,2,'
    'Reposicao,Good,Focus,Team,Practice speaking,\n'
)

LESSONS_CSV = (
    'turma,aula_num,date,licao_conteudo,atividade_extra,habilidades\n'
    'MASTER,1,01/02/2026,Lesson 1,,\n'
    'MASTER,2,15/02/2026,Lesson 2,,\n'
)


def _load_dotenv():
    env_path = ROOT / '.env'
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding='utf-8').splitlines():
        line = raw.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, v = line.split('=', 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _student_form(name, turma, teacher='Chuck'):
    base = {
        'teacher': teacher,
        'turma': turma,
        'turma_display': 'Test class',
        'nivel': 'Book 1',
        'horario': 'Mon 10:00',
        'student_name': name,
        'participacao': '3',
        'comportamento': '3',
        'speaking': '3',
        'listening': '3',
        'foco': '3',
        'writing': '3',
        'reading': '3',
        'gramatica': '3',
        'trabalho_equipe': '3',
        'organizacao': '3',
        'pontualidade': '3',
        'respeito_regras': '3',
        'faltas': '0',
        'missed_aulas': '',
        'aula_extra': '',
        'feedback_participacao': '',
        'feedback_foco': '',
        'feedback_trabalho_equipe': '',
        'recomendacoes': '',
        'observacao': '',
    }
    return base


def _csrf_from_html(html: str) -> str:
    match = re.search(r'name="csrf_token"\s+value="([^"]+)"', html)
    return match.group(1) if match else ''


def _class_choice_from_html(html: str) -> str:
    """First registered class on the new-student form, if the picker is shown."""
    select = re.search(
        r'<select[^>]*\bname="class_choice"[^>]*>(.*?)</select>',
        html,
        re.DOTALL,
    )
    if not select:
        return ''
    for value in re.findall(r'<option\b[^>]*\bvalue="([^"]*)"', select.group(1)):
        if value.strip():
            return value.strip()
    return ''


class _StudentDeleteFormParser(HTMLParser):
    """Find the delete form inside the named student's own row or card.

    Searching the raw HTML for the name is unsafe: the success banner
    ("Aluno … cadastrado") sits above the list, so the first form after the
    name belongs to whichever real student is listed first.
    """

    _VOID_TAGS: ClassVar[frozenset[str]] = frozenset({
        'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
        'link', 'meta', 'param', 'source', 'track', 'wbr',
    })

    def __init__(self, name: str):
        super().__init__(convert_charrefs=True)
        self.name = name
        self.path = ''
        self.identity: dict[str, str] = {}
        self._depth = 0
        self._text: list[str] = []
        self._form_path = ''
        self._form_identity: dict[str, str] = {}
        self._in_delete_form = False

    @staticmethod
    def _is_student_block(tag: str, attrs: dict[str, str]) -> bool:
        classes = set(attrs.get('class', '').split())
        return (tag == 'tr' and 'student-row' in classes) or (
            tag == 'div' and 'student-card-item' in classes
        )

    def handle_starttag(self, tag, attrs):
        attr_map = {key: value or '' for key, value in attrs}
        if not self._depth:
            if self._is_student_block(tag, attr_map):
                self._depth = 1
                self._text, self._form_path, self._form_identity = [], '', {}
            return
        if tag not in self._VOID_TAGS:
            self._depth += 1
        if tag == 'form':
            action = attr_map.get('action', '')
            self._in_delete_form = '/students/' in action and '/delete' in action and not self._form_path
            if self._in_delete_form:
                self._form_path = action
        elif tag == 'input' and self._in_delete_form and attr_map.get('name', '').startswith('orig_'):
            self._form_identity[attr_map['name']] = attr_map.get('value', '')

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_data(self, data):
        if self._depth:
            self._text.append(data)

    def handle_endtag(self, tag):
        if not self._depth:
            return
        if tag == 'form':
            self._in_delete_form = False
        self._depth -= 1
        if self._depth == 0 and not self.path:
            text = ' '.join(part.strip() for part in self._text if part.strip())
            if self.name in text and self._form_path:
                self.path, self.identity = self._form_path, self._form_identity


def _delete_form_for_student(html: str, name: str) -> tuple[str, dict]:
    """(action, orig_* identity) of the delete form in that student's own row; ('', {}) if none."""
    parser = _StudentDeleteFormParser(name)
    parser.feed(html)
    return parser.path, parser.identity


def _delete_path_for_student(html: str, name: str) -> str:
    return _delete_form_for_student(html, name)[0]


def _delete_identity_for_student(html: str, name: str) -> dict:
    """Hidden orig_* fields of that student's delete form (the server refuses deletes without them)."""
    return _delete_form_for_student(html, name)[1]


class _LessonTurmaParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.turmas: list[str] = []

    def handle_starttag(self, tag, attrs):
        for key, value in attrs:
            if key == 'data-turma' and value and value.strip() not in self.turmas:
                self.turmas.append(value.strip())


def _lesson_turmas_from_html(html: str) -> list[str]:
    parser = _LessonTurmaParser()
    parser.feed(html)
    return parser.turmas


class FlowRunner:
    def __init__(self, label: str):
        self.label = label
        self.failures: list[str] = []
        self.steps: list[tuple[str, bool, str]] = []

    def check(self, name: str, ok: bool, detail: str = ''):
        self.steps.append((name, ok, detail))
        mark = 'OK' if ok else 'FAIL'
        extra = f' — {detail}' if detail else ''
        print(f'  [{mark}] {name}{extra}')
        if not ok:
            self.failures.append(f'{name}{extra}')

    def finish(self):
        print()
        if self.failures:
            print(f'FAIL ({self.label}): {len(self.failures)} step(s)')
            for item in self.failures:
                print(f'  - {item}')
            return 1
        print(f'PASS: whole user flow ({self.label})')
        return 0


def run_inprocess():
    _load_dotenv()
    email = os.environ.get('SUPERADMIN_EMAIL', 'admin@test.local').strip()
    password = os.environ.get('SUPERADMIN_PASSWORD') or os.environ.get('ADMIN_PASSWORD', 'testpass')

    runner = FlowRunner('in-process')
    with tempfile.TemporaryDirectory() as tmp:
        data_dir = Path(tmp) / 'data'
        out_dir = Path(tmp) / 'output'
        data_dir.mkdir()
        out_dir.mkdir()
        (data_dir / 'students.csv').write_text(STUDENTS_CSV, encoding='utf-8')
        (data_dir / 'lessons.csv').write_text(LESSONS_CSV, encoding='utf-8')

        store = UserStore(db_store=None, json_path=data_dir / 'users.json')
        store.initialize()
        store.ensure_bootstrap_superadmin(email, password)

        web_app.DATA_DIR = data_dir
        web_app.OUT_DIR = out_dir
        web_app.SNAPSHOTS_PATH = data_dir / 'student_snapshots.json'
        web_app.db_store = None
        web_app.DB_ENABLED = False
        web_app.user_store = store
        web_app.app.config['WTF_CSRF_ENABLED'] = False
        web_app.limiter.reset()

        client = web_app.app.test_client()

        r = client.post('/login', data={'email': email, 'password': password})
        runner.check('Login', r.status_code == 302, f'status={r.status_code}')

        r = client.get('/')
        html = r.get_data(as_text=True)
        runner.check('Dashboard', r.status_code == 200 and 'Gerar' in html)

        r = client.get('/students/new')
        runner.check('New student form', r.status_code == 200 and 'Novo aluno' in r.get_data(as_text=True))

        r = client.post('/students/new', data={'student_name': 'Bad', 'turma': '', 'teacher': 'Chuck'})
        err_html = r.get_data(as_text=True)
        runner.check(
            'New student validation (missing turma)',
            r.status_code == 200 and 'Informe o nome do aluno e a turma' in err_html,
        )

        new_name = f'Flow Test Kid {os.getpid()}'
        create_form = _student_form(new_name, 'MASTER')
        create_form['class_choice'] = 'MASTER'
        r = client.post(
            '/students/new',
            data=create_form,
            follow_redirects=False,
        )
        loc = r.headers.get('Location', '')
        runner.check(
            'Create student',
            r.status_code == 302 and '/students' in loc,
            loc,
        )

        r = client.get('/students')
        runner.check('Students list shows new row', new_name in r.get_data(as_text=True))

        r = client.get('/lessons')
        runner.check('Lessons page', r.status_code == 200 and 'MASTER' in r.get_data(as_text=True))

        r = client.get('/upload')
        runner.check('Upload page', r.status_code == 200)

        r = client.post('/generate', follow_redirects=False)
        loc = r.headers.get('Location', '')
        runner.check(
            'Generate reports',
            r.status_code == 302 and '/reports' in loc,
            loc,
        )

        r = client.get(loc if loc.startswith('/') else '/reports')
        rep_html = r.get_data(as_text=True)
        runner.check(
            'Reports page after generate',
            r.status_code == 200 and ('Relatório' in rep_html or 'relatório' in rep_html),
        )
        runner.check(
            'Report HTML files on disk',
            any(out_dir.glob('*_report.html')),
            str(len(list(out_dir.glob('*.html')))) + ' files',
        )

        r = client.get('/reports/preview/' + next(out_dir.glob('*_report.html')).name)
        runner.check('Preview report', r.status_code == 200)

    return runner.finish()


def run_live(base: str):
    import http.cookiejar
    import urllib.error
    import urllib.parse
    from urllib.request import HTTPCookieProcessor, Request, build_opener

    _load_dotenv()
    email = os.environ.get('SUPERADMIN_EMAIL', '').strip()
    password = os.environ.get('SUPERADMIN_PASSWORD') or os.environ.get('ADMIN_PASSWORD', '')
    if not email or not password:
        print('FAIL: set SUPERADMIN_EMAIL and SUPERADMIN_PASSWORD in .env')
        return 1

    base = base.rstrip('/')
    runner = FlowRunner(f'live {base}')
    jar = http.cookiejar.CookieJar()
    opener = build_opener(HTTPCookieProcessor(jar))

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    opener_no_redirect = build_opener(HTTPCookieProcessor(jar), _NoRedirect())

    def get(path):
        return opener.open(f'{base}{path}', timeout=60)

    def post(path, data, *, allow_redirect=True):
        body = urllib.parse.urlencode(data).encode()
        req = Request(f'{base}{path}', data=body, method='POST')
        http = opener if allow_redirect else opener_no_redirect
        try:
            return http.open(req, timeout=120)
        except urllib.error.HTTPError as exc:
            if allow_redirect and exc.code in (301, 302, 303, 307, 308):
                loc = exc.headers.get('Location', '')
                if loc:
                    return opener.open(loc if loc.startswith('http') else base + loc, timeout=60)
            raise

    login_html = get('/login').read().decode('utf-8', errors='replace')
    r = post('/login', {
        'email': email,
        'password': password,
        'csrf_token': _csrf_from_html(login_html),
    })
    runner.check('Login', getattr(r, 'status', r.code) in (200, 302))

    html = get('/').read().decode('utf-8', errors='replace')
    runner.check('Dashboard', 'Gerar' in html or 'Relatório' in html)

    new_student_html = get('/students/new').read().decode('utf-8', errors='replace')
    runner.check('New student form', 'Novo aluno' in new_student_html)

    bad_resp = post('/students/new', {
        'student_name': 'X',
        'turma': '',
        'teacher': 'Chuck',
        'csrf_token': _csrf_from_html(new_student_html),
    })
    bad_body = bad_resp.read().decode('utf-8', errors='replace')
    runner.check('New student validation', 'Informe o nome do aluno e a turma' in bad_body)

    new_name = f'Live Flow Kid {os.getpid()}'
    class_choice = _class_choice_from_html(new_student_html)
    lesson_turmas = []
    if not class_choice:
        try:
            lessons_html = get('/lessons').read().decode('utf-8', errors='replace')
            lesson_turmas = _lesson_turmas_from_html(lessons_html)
        except (urllib.error.HTTPError, OSError):
            lesson_turmas = []
    # A registered class is required when the dashboard picker is on the form.
    # Admin/manual forms still need a lesson-backed turma so generation stays valid.
    turma = class_choice or (lesson_turmas[0] if lesson_turmas else f'AUDIT {os.getpid()}')
    try:
        form_data = _student_form(new_name, turma)
        if class_choice:
            form_data['class_choice'] = class_choice
        form_data['csrf_token'] = _csrf_from_html(new_student_html)
        post('/students/new', form_data, allow_redirect=False)
        create_ok = False
        loc = ''
    except urllib.error.HTTPError as e:
        loc = e.headers.get('Location', '')
        create_ok = e.code in (302, 303) and '/students' in (loc or '')
    runner.check('Create student redirect', create_ok, loc or '')

    html = get('/students').read().decode('utf-8', errors='replace')
    runner.check('Students list', new_name in html)
    delete_path, identity = _delete_form_for_student(html, new_name)
    removed = False
    # Never post a delete unless the form is provably the test student's own:
    # on a live server a wrong match would erase a real student.
    if delete_path and identity.get('orig_student_name') == new_name:
        try:
            post(delete_path, {'csrf_token': _csrf_from_html(html), **identity})
        except urllib.error.HTTPError:
            removed = False
        else:
            after = get('/students').read().decode('utf-8', errors='replace')
            removed = new_name not in after
    detail = delete_path or 'delete form not found'
    if delete_path and identity.get('orig_student_name') != new_name:
        detail = f'refused: form identity {identity!r} is not {new_name!r}'
    runner.check('Remove flow-test student', removed, detail)

    try:
        dash_html = get('/').read().decode('utf-8', errors='replace')
        post('/generate', {
            'report_month': '2026-02',
            'csrf_token': _csrf_from_html(dash_html),
        }, allow_redirect=False)
        gen_ok = False
        gen_loc = ''
    except urllib.error.HTTPError as e:
        gen_loc = e.headers.get('Location', '')
        gen_ok = e.code in (302, 303) and '/reports' in (gen_loc or '')
    runner.check('Generate reports', gen_ok, gen_loc or 'no redirect')

    if gen_loc:
        path = gen_loc if gen_loc.startswith('http') else base + gen_loc
        html = opener.open(path, timeout=60).read().decode('utf-8', errors='replace')
        runner.check('Reports page', 'Relatório' in html or 'relatório' in html.lower())

    return runner.finish()


def main():
    base = sys.argv[1] if len(sys.argv) > 1 else ''
    if base:
        return run_live(base)
    return run_inprocess()


if __name__ == '__main__':
    sys.exit(main())
