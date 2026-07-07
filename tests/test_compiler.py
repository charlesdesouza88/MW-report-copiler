from compiler import (
    build_attendance_calendar,
    build_student_ctx,
    composite_donut_chart,
    create_report_environment,
    generate_individual_reports,
    group_by_turma,
    int_score,
    lessons_for,
    missed_lessons,
    needs_extra,
    pie_path,
    pres_to_score,
    presence_pct,
    score_delta_badge,
)
from report_periods import prior_month_snapshot, student_snapshot_id


def _student(**overrides):
    base = {
        "teacher": "Chuck",
        "turma": "MASTER",
        "turma_display": "Masters",
        "nivel": "Adults Book 4",
        "horario": "Tue/Thu 19:00",
        "student_name": "Jane Doe",
        "participacao": "4",
        "comportamento": "3",
        "speaking": "4",
        "listening": "5",
        "foco": "4",
        "writing": "3",
        "reading": "4",
        "gramatica": "2",
        "trabalho_equipe": "",
        "organizacao": "",
        "pontualidade": "",
        "respeito_regras": "",
        "faltas": "1",
        "missed_aulas": "2",
        "aula_extra": "Reposicao",
        "feedback_participacao": "",
        "feedback_foco": "",
        "feedback_trabalho_equipe": "",
        "recomendacoes": "",
        "observacao": "",
    }
    base.update(overrides)
    return base


def _lessons():
    return [
        {
            "turma": "MASTER",
            "aula_num": "1",
            "date": "01/01",
            "licao_conteudo": "L1",
            "atividade_extra": "",
            "habilidades": "",
        },
        {
            "turma": "MASTER",
            "aula_num": "2",
            "date": "03/01",
            "licao_conteudo": "L2",
            "atividade_extra": "",
            "habilidades": "",
        },
    ]


def test_presence_score_mapping_boundaries():
    assert pres_to_score(95) == 5
    assert pres_to_score(85) == 4
    assert pres_to_score(75) == 3
    assert pres_to_score(65) == 2
    assert pres_to_score(64) == 1


def test_presence_pct_zero_lessons_defaults_to_100():
    assert presence_pct(0, 0) == 100


def test_missed_lessons_and_lessons_for_ignore_turma_case():
    lessons = _lessons()
    student = _student(turma="master", missed_aulas="2")
    assert len(missed_lessons(student, lessons)) == 1
    assert len(lessons_for("master", lessons)) == 2


def test_int_score_clamps_and_defaults():
    assert int_score("9") == 5
    assert int_score("0") == 1
    assert int_score("not-a-number", default=2) == 2


def test_pie_path_full_circle_flag_when_100_percent():
    path_d, full = pie_path(100)
    assert full is True
    assert "A 48,48" in path_d


def test_build_student_ctx_computes_expected_derived_values():
    ctx = build_student_ctx(_student(), _lessons())
    assert ctx["pct"] == 50
    assert ctx["pres_score"] == 1
    assert ctx["needs_makeup"] is True
    assert ctx["part_scores"] == [4, 4, 3]
    assert ctx["comp_scores"] == [3, 3, 3]
    assert len(ctx["missed"]) == 1


def test_build_student_ctx_month_scopes_presence():
    lessons = [
        {
            "turma": "MASTER",
            "aula_num": "1",
            "date": "01/02/2026",
            "licao_conteudo": "L1",
            "atividade_extra": "",
            "habilidades": "",
        },
        {
            "turma": "MASTER",
            "aula_num": "2",
            "date": "01/03/2026",
            "licao_conteudo": "L2",
            "atividade_extra": "",
            "habilidades": "",
        },
    ]
    ctx = build_student_ctx(_student(faltas="1", missed_aulas="2"), lessons, report_month="2026-03")
    assert ctx["pct"] == 0
    assert len(ctx["missed"]) == 1


def test_build_student_ctx_uses_manual_faltas_without_missed_aulas():
    lessons = [
        {
            "turma": "MASTER",
            "aula_num": "1",
            "date": "01/03/2026",
            "licao_conteudo": "L1",
            "atividade_extra": "",
            "habilidades": "",
        },
        {
            "turma": "MASTER",
            "aula_num": "2",
            "date": "08/03/2026",
            "licao_conteudo": "L2",
            "atividade_extra": "",
            "habilidades": "",
        },
    ]
    ctx = build_student_ctx(
        _student(faltas="3", missed_aulas=""),
        lessons,
        report_month="2026-03",
    )
    assert len(ctx["missed"]) == 0
    assert ctx["pct"] == 0
    assert ctx["pres_score"] == 1


def test_build_attendance_calendar_supports_dd_mm_dates():
    lessons = [
        {
            "turma": "MASTER",
            "aula_num": "1",
            "date": "15/03",
            "licao_conteudo": "L1",
            "atividade_extra": "",
            "habilidades": "",
        },
        {
            "turma": "MASTER",
            "aula_num": "2",
            "date": "22/03",
            "licao_conteudo": "L2",
            "atividade_extra": "",
            "habilidades": "",
        },
    ]
    calendar = build_attendance_calendar(lessons, [], set(), "2026-03")
    assert calendar is not None
    assert calendar["has_class"] is True
    present_days = [
        cell["day"]
        for week in calendar["weeks"]
        for cell in week
        if cell.get("status") == "present"
    ]
    assert 15 in present_days
    assert 22 in present_days


def test_needs_extra_accepts_accented_and_unaccented_values():
    assert needs_extra(_student(aula_extra="Reforco")) is True
    assert needs_extra(_student(aula_extra="Reposicao")) is True
    assert needs_extra(_student(aula_extra="")) is False


def test_build_student_ctx_requires_turma():
    try:
        build_student_ctx(_student(turma=""), _lessons())
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_group_by_turma_skips_rows_without_turma():
    groups = group_by_turma([
        _student(student_name="A", turma="MASTER"),
        _student(student_name="B", turma=""),
        {"student_name": "C"},
    ])
    assert list(groups.keys()) == ["MASTER"]
    assert len(groups["MASTER"]) == 1


def test_group_by_turma_groups_students():
    groups = group_by_turma([
        _student(student_name="A", turma="MASTER"),
        _student(student_name="B", turma="MASTER"),
        _student(student_name="C", turma="SPARK"),
    ])
    assert sorted(groups.keys()) == ["MASTER", "SPARK"]
    assert len(groups["MASTER"]) == 2


def test_individual_report_renders_labeled_overall_scores():
    from pathlib import Path

    from compiler import build_student_ctx

    base = Path(__file__).resolve().parent.parent
    env = create_report_environment(base / "templates")
    html = env.get_template("individual_report.html").render(
        **build_student_ctx(_student(), _lessons())
    )

    assert "card-header" in html
    assert html.count('class="overall-score-label"') == 4
    assert "bubble-abs" not in html
    assert "Nota" in html
    assert "Critérios" in html


def test_score_delta_badge_directions():
    assert score_delta_badge(4, 3)['css'] == 'delta-up'
    assert score_delta_badge(2, 4)['css'] == 'delta-down'
    assert score_delta_badge(3, 3)['css'] == 'delta-stable'
    assert score_delta_badge(3, None) is None


def test_composite_donut_includes_prior_ring():
    donut = composite_donut_chart(4, 3)
    assert donut['prior_dash'] is not None
    assert donut['cur_dash']


def test_build_student_ctx_month_comparison_with_snapshots():
    sid = student_snapshot_id('MASTER', 'Jane Doe')
    snapshots = {
        f'MASTER|{sid}|2026-02': {
            'composite_score': 3,
            'dev_overall': 3,
            'part_overall': 3,
            'comp_overall': 3,
            'pres_score': 3,
        },
    }
    lessons = [
        {
            "turma": "MASTER",
            "aula_num": "1",
            "date": "01/03/2026",
            "licao_conteudo": "L1",
            "atividade_extra": "",
            "habilidades": "",
        },
        {
            "turma": "MASTER",
            "aula_num": "2",
            "date": "03/03/2026",
            "licao_conteudo": "L2",
            "atividade_extra": "",
            "habilidades": "",
        },
    ]
    ctx = build_student_ctx(
        _student(faltas="1", missed_aulas="2"), lessons,
        report_month='2026-03', snapshots=snapshots,
    )
    assert ctx['comparison'] is not None
    assert ctx['comparison']['has_prior'] is True
    assert ctx['pres_score_delta']['css'] == 'delta-down'
    assert ctx['expanded_radar']
    assert len(ctx['expanded_grid']) == 5


def test_individual_report_renders_comparison_section():
    from pathlib import Path

    base = Path(__file__).resolve().parent.parent
    env = create_report_environment(base / "templates")
    sid = student_snapshot_id('MASTER', 'Jane Doe')
    snapshots = {
        f'MASTER|{sid}|2026-02': {
            'composite_score': 3,
            'dev_overall': 3,
            'part_overall': 3,
            'comp_overall': 3,
            'pres_score': 5,
        },
    }
    html = env.get_template('individual_report.html').render(
        **build_student_ctx(
            _student(faltas='1', missed_aulas='2'),
            [
                {
                    "turma": "MASTER",
                    "aula_num": "1",
                    "date": "01/03/2026",
                    "licao_conteudo": "L1",
                    "atividade_extra": "",
                    "habilidades": "",
                },
                {
                    "turma": "MASTER",
                    "aula_num": "2",
                    "date": "03/03/2026",
                    "licao_conteudo": "L2",
                    "atividade_extra": "",
                    "habilidades": "",
                },
            ],
            report_month='2026-03',
            snapshots=snapshots,
        ),
    )
    assert 'Comparativo Mensal' in html
    assert 'Visão Geral (7 eixos)' in html
    assert 'delta-badge' in html
    assert 'Índice Geral' in html


def test_prior_month_snapshot_lookup():
    sid = student_snapshot_id('MASTER', 'Jane')
    snapshots = {f'MASTER|{sid}|2026-02': {'composite_score': 4}}
    row = prior_month_snapshot(snapshots, 'MASTER', 'Jane', '2026-03')
    assert row['composite_score'] == 4
    assert prior_month_snapshot(snapshots, 'MASTER', 'Jane', '2026-02') is None


def test_report_generation_escapes_text_and_sanitizes_filename(tmp_path):
    from pathlib import Path

    base = Path(__file__).resolve().parent.parent
    env = create_report_environment(base / "templates")
    student = _student(
        turma="../MASTER",
        student_name="../Jane <script>alert(1)</script>",
        feedback_participacao="<script>alert(1)</script>",
        recomendacoes="<img src=x onerror=alert(1)>",
    )
    lessons = [
        {
            "turma": "../MASTER",
            "aula_num": "1",
            "date": "01/01",
            "licao_conteudo": "L1",
            "atividade_extra": "",
            "habilidades": "",
        },
    ]

    generate_individual_reports([student], lessons, env, tmp_path)

    generated = list(tmp_path.glob("*_report.html"))
    assert len(generated) == 1
    assert generated[0].parent == tmp_path
    assert ".." not in generated[0].name
    html = generated[0].read_text(encoding="utf-8")
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<img src=x" not in html


# ── audit regression tests ────────────────────────────────────────────────────

def test_avg_score_rounds_half_up():
    from compiler import avg_score

    # Python's built-in round() is banker's rounding (2.5 → 2); scores must
    # always round .5 up so equivalent averages land on the same grade.
    assert avg_score([2, 3]) == 3
    assert avg_score([3, 4]) == 4
    assert avg_score([1, 2]) == 2
    assert avg_score([4, 5]) == 5


def test_composite_score_rounds_half_up():
    from report_periods import student_composite_score

    ctx = {'dev_overall': 3, 'part_overall': 2, 'comp_overall': 2, 'pres_score': 3}
    assert student_composite_score(ctx) == 3  # 2.5 rounds up, not to even


def test_presence_pct_clamped_to_0_100():
    assert presence_pct(5, 3) == 0  # more faltas than lessons can't go negative
    assert presence_pct(-1, 4) == 100  # negative faltas can't exceed 100


def test_load_csv_strips_excel_bom(tmp_path):
    from compiler import load_csv

    path = tmp_path / "students.csv"
    path.write_bytes("turma,student_name\nMASTER,Àna Çedilha\n".encode("utf-8-sig"))
    rows = load_csv(path)
    assert rows[0]["turma"] == "MASTER"
    assert rows[0]["student_name"] == "Àna Çedilha"


def test_attendance_calendar_accepts_legacy_ddmm_dates():
    from datetime import datetime
    from compiler import build_attendance_calendar

    year = datetime.now().year
    lessons = [{"turma": "MASTER", "aula_num": "1", "date": "05/03"}]
    cal = build_attendance_calendar(lessons, [], set(), f"{year}-03")
    assert cal["has_class"]
    statuses = [cell["status"] for week in cal["weeks"] for cell in week if cell["day"] == 5]
    assert statuses == ["present"]


def test_missed_unknown_lessons_are_flagged():
    student = _student(missed_aulas="2,99")
    lessons = [
        {"turma": "MASTER", "aula_num": "1", "date": "01/03/2026", "licao_conteudo": "L1"},
        {"turma": "MASTER", "aula_num": "2", "date": "08/03/2026", "licao_conteudo": "L2"},
    ]
    ctx = build_student_ctx(student, lessons)
    assert ctx["missed_unknown"] == ["99"]
    assert [m["aula_num"] for m in ctx["missed"]] == ["2"]


def test_turmas_without_lessons_detected():
    from compiler import turmas_without_lessons

    students = [_student(), _student(turma="NOVA", student_name="Beto")]
    lessons = [{"turma": "MASTER", "aula_num": "1", "date": "01/03/2026"}]
    assert turmas_without_lessons(students, lessons) == ["NOVA"]
    assert turmas_without_lessons(students, lessons + [
        {"turma": "nova", "aula_num": "1", "date": "01/03/2026"},
    ]) == []
