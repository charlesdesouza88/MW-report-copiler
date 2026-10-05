"""Guards for the live user-flow script's HTML helpers."""

import importlib.util
from pathlib import Path


def _script():
    path = Path(__file__).resolve().parents[1] / 'scripts' / 'user_flow_test.py'
    spec = importlib.util.spec_from_file_location('user_flow_test_script', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_class_choice_reads_first_registered_option():
    script = _script()
    html = '''
    <select name="class_choice" id="class-choice" required>
      <option value="">— Selecione —</option>
      <option value="teens 01">Impact — Terça 14:00</option>
      <option value="MASTER">Masters</option>
    </select>
    '''
    assert script._class_choice_from_html(html) == 'teens 01'


def test_class_choice_is_empty_without_a_picker():
    script = _script()
    html = '<input type="text" name="turma" value="MASTER">'
    assert script._class_choice_from_html(html) == ''


def test_delete_path_is_tied_to_the_named_student():
    script = _script()
    html = '''
    <strong>Jane Doe</strong>
    <form method="post" action="/students/0/delete?month=2026-02">
      <button>Excluir</button>
    </form>
    <strong>Live Flow Kid 99</strong>
    <form method="post" action="/students/4/delete">
      <button>Excluir</button>
    </form>
    '''
    assert script._delete_path_for_student(html, 'Live Flow Kid 99') == '/students/4/delete'


def test_delete_identity_comes_from_the_named_students_form():
    script = _script()
    html = '''
    <strong>Jane Doe</strong>
    <form method="post" action="/students/0/delete">
      <input type="hidden" name="orig_turma" value="MASTER"><input type="hidden" name="orig_student_name" value="Jane Doe">
    </form>
    <strong>Live Flow Kid 99</strong>
    <form method="post" action="/students/4/delete">
      <input type="hidden" name="orig_turma" value="FLOW"><input type="hidden" name="orig_student_name" value="Live Flow Kid 99">
    </form>
    '''
    assert script._delete_identity_for_student(html, 'Live Flow Kid 99') == {
        'orig_turma': 'FLOW', 'orig_student_name': 'Live Flow Kid 99',
    }
    assert script._delete_identity_for_student(html, 'Nobody') == {}
