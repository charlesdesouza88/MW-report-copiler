from form_ui import (
    HABILIDADES_CHOICES,
    LICAO_CONTEUDO_CHOICES,
    licao_choice_for_value,
    next_aula_num,
    normalize_habilidades,
    suggest_licao_conteudo,
    turma_next_aula_map,
)


def test_next_aula_num_empty_turma():
    lessons = [
        {'turma': 'STAR', 'aula_num': '5'},
        {'turma': 'STAR', 'aula_num': '11'},
    ]
    assert next_aula_num(lessons, 'STAR') == '12'
    assert next_aula_num(lessons, 'COMET') == '1'
    assert next_aula_num([], 'STAR') == '1'


def test_next_aula_num_ignores_non_numeric():
    lessons = [
        {'turma': 'STAR', 'aula_num': 'abc'},
        {'turma': 'STAR', 'aula_num': '3'},
    ]
    assert next_aula_num(lessons, 'STAR') == '4'


def test_next_aula_num_case_insensitive_turma():
    lessons = [{'turma': 'star', 'aula_num': '2'}]
    assert next_aula_num(lessons, 'STAR') == '3'


def test_normalize_habilidades_canonical_and_aliases():
    assert normalize_habilidades('IA') == 'Inteligência Artificial'
    assert normalize_habilidades('empreendedorismo') == 'Empreendedorismo'
    assert normalize_habilidades('Inteligencia Emocional') == 'Inteligência emocional'
    assert normalize_habilidades('Liderança') == 'Liderança'
    assert normalize_habilidades('IA + Finanças') == 'IA + Finanças'


def test_normalize_habilidades_empty():
    assert normalize_habilidades('') == ''
    assert normalize_habilidades(None) == ''


def test_licao_choice_for_value():
    assert licao_choice_for_value('8') == 'Lição 8'
    assert licao_choice_for_value('Lesson 12') == 'Lição 12'
    assert licao_choice_for_value('Review') == 'Revisão'
    assert licao_choice_for_value('Revisão') == 'Revisão'
    assert licao_choice_for_value('Aula Dinâmica') == 'Aula Dinâmica'
    assert licao_choice_for_value('Aula 0 - Welcome class') == 'Aula 0 - Welcome class'
    assert licao_choice_for_value('Lição 5') == 'Lição 5'


def test_suggest_licao_conteudo():
    assert suggest_licao_conteudo('7') == 'Lição 7'
    assert suggest_licao_conteudo('101') == ''
    assert suggest_licao_conteudo('') == ''


def test_turma_next_aula_map_uppercase_keys():
    lessons = [
        {'turma': 'STAR', 'aula_num': '10'},
        {'turma': 'COMET', 'aula_num': '22'},
    ]
    result = turma_next_aula_map(lessons, ['STAR', 'COMET'])
    assert result == {'STAR': '11', 'COMET': '23'}


def test_habilidades_choices_count():
    assert len(HABILIDADES_CHOICES) == 5


def test_licao_conteudo_choices_count():
    assert len(LICAO_CONTEUDO_CHOICES) == 102
