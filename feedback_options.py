"""Ready-made teacher comments for the Participação feedback fields.

Teachers pick one per category from a dropdown instead of typing; only
Recomendações and Observação geral stay free text. Phrases are written for
parents and avoid gendered adjectives so they fit any student. Groups follow
the 1–5 score bands so the comment can match the grade next to it.
"""

FEEDBACK_FIELDS = ('feedback_participacao', 'feedback_foco', 'feedback_trabalho_equipe')

FEEDBACK_OPTIONS = {
    'feedback_participacao': [
        ('Destaque (4–5)', [
            'Participa ativamente e contribui com ideias em inglês.',
            'Responde com confiança e se arrisca a falar mesmo com dúvidas.',
            'Faz perguntas e comentários que enriquecem a aula.',
        ]),
        ('Bom (3)', [
            'Participa bem quando recebe a vez de falar.',
            'Contribui com frequência nas atividades orais.',
            'Vem ganhando confiança para falar em inglês.',
        ]),
        ('Precisa de atenção (1–2)', [
            'Ainda participa pouco; incentivamos que se arrisque mais a falar.',
            'Prefere ouvir a falar; estamos trabalhando a confiança.',
            'Participação irregular ao longo do mês.',
        ]),
    ],
    'feedback_foco': [
        ('Destaque (4–5)', [
            'Mantém o foco durante toda a aula.',
            'Concentra-se nas tarefas e conclui as atividades no tempo.',
            'Acompanha as explicações com muita atenção.',
        ]),
        ('Bom (3)', [
            'Mantém a atenção na maior parte da aula.',
            'Concentra-se bem, com pequenas distrações.',
            'Melhorou a concentração ao longo do mês.',
        ]),
        ('Precisa de atenção (1–2)', [
            'Distrai-se com facilidade e precisa de lembretes para voltar à tarefa.',
            'Tem dificuldade para manter o foco no fim da aula.',
            'Conversas paralelas têm atrapalhado a concentração.',
        ]),
    ],
    'feedback_trabalho_equipe': [
        ('Destaque (4–5)', [
            'Colabora muito bem e ajuda os colegas.',
            'Lidera atividades em grupo com respeito e organização.',
            'Divide as tarefas e valoriza as ideias do grupo.',
        ]),
        ('Bom (3)', [
            'Trabalha bem em grupo.',
            'Colabora quando recebe incentivo.',
            'Está aprendendo a ouvir e a dividir tarefas com o grupo.',
        ]),
        ('Precisa de atenção (1–2)', [
            'Prefere atividades individuais; estamos incentivando a colaboração.',
            'Precisa respeitar mais a vez dos colegas.',
            'Tem dificuldade em dividir tarefas no grupo.',
        ]),
    ],
}


def feedback_phrases(field):
    """Every ready-made phrase for one field, in dropdown order."""
    return [phrase for _group, phrases in FEEDBACK_OPTIONS.get(field, []) for phrase in phrases]


def is_legacy_feedback(field, value):
    """True for typed text saved before the dropdown existed (kept so nothing is lost)."""
    value = (value or '').strip()
    return bool(value) and value not in feedback_phrases(field)
