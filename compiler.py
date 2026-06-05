#!/usr/bin/env python3
"""Mister Wiz Report Compiler — generates student and class reports from CSV data."""

import csv
import math
import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from report_names import (class_diagnostic_filename, safe_child_path,
                          student_report_filename)


# ── SVG helpers ──────────────────────────────────────────────────────────────

def _pentagon_points(scores, cx, cy, max_r):
    """Return SVG polygon points string for a 5-axis radar chart.
    Axes in order: Audição, Fala, Gramática, Escrita, Leitura (clockwise from top).
    """
    pts = []
    for i, s in enumerate(scores):
        angle = -math.pi / 2 + i * 2 * math.pi / 5
        r = (float(s) / 5.0) * max_r
        x = round(cx + r * math.cos(angle), 2)
        y = round(cy + r * math.sin(angle), 2)
        pts.append(f"{x},{y}")
    return " ".join(pts)


def pentagon_polygon(scores, cx=100, cy=105, max_r=78):
    return _pentagon_points(scores, cx, cy, max_r)


def pentagon_grid(cx=100, cy=105, max_r=78):
    """Return list of SVG polygon point strings for grid rings (levels 1–5)."""
    rings = []
    for level in range(1, 6):
        r = (level / 5.0) * max_r
        pts = []
        for i in range(5):
            angle = -math.pi / 2 + i * 2 * math.pi / 5
            x = round(cx + r * math.cos(angle), 2)
            y = round(cy + r * math.sin(angle), 2)
            pts.append(f"{x},{y}")
        rings.append(" ".join(pts))
    return rings


def axis_endpoints(cx=100, cy=105, max_r=78):
    """Return list of (x, y) axis tip coordinates."""
    eps = []
    for i in range(5):
        angle = -math.pi / 2 + i * 2 * math.pi / 5
        x = round(cx + max_r * math.cos(angle), 2)
        y = round(cy + max_r * math.sin(angle), 2)
        eps.append((x, y))
    return eps


# Display order for class diagnostic skill columns: (label, dev_scores index)
# dev_scores axis order: Audição(0), Fala(1), Gramática(2), Escrita(3), Leitura(4)
SKILL_COLUMN_DEFS = [
    ('Fala', 1),
    ('Audição', 0),
    ('Escrita', 3),
    ('Leitura', 4),
    ('Gramática', 2),
]


def mini_radar_spoke_chart(dev_scores, highlight_axis, cx=34, cy=36, max_r=24):
    """Small pentagon web chart with one axis highlighted (for per-skill columns)."""
    score = int_score(dev_scores[highlight_axis])
    angle = -math.pi / 2 + highlight_axis * 2 * math.pi / 5
    r = (float(score) / 5.0) * max_r
    hx = round(cx + r * math.cos(angle), 2)
    hy = round(cy + r * math.sin(angle), 2)
    return dict(
        grid=pentagon_grid(cx, cy, max_r),
        axes=axis_endpoints(cx, cy, max_r),
        pentagon=pentagon_polygon(dev_scores, cx, cy, max_r),
        center=(cx, cy),
        highlight_tip=(hx, hy),
        highlight_axis=highlight_axis,
    )


def skill_column_charts(dev_scores):
    return [
        dict(
            label=label,
            axis_index=axis_index,
            score=int_score(dev_scores[axis_index]),
            mini=mini_radar_spoke_chart(dev_scores, axis_index),
        )
        for label, axis_index in SKILL_COLUMN_DEFS
    ]


COMPARISON_DIMS = [
    ('Presença', 'pres_score'),
    ('Desenvolvimento', 'dev_overall'),
    ('Participação', 'part_overall'),
    ('Comportamento', 'comp_overall'),
]


def score_delta_badge(current, prior):
    """Return delta badge metadata for month-over-month score changes."""
    if prior is None:
        return None
    delta = int(current) - int(prior)
    if delta > 0:
        return dict(delta=delta, text=f'+{delta}', css='delta-up', symbol='▲')
    if delta < 0:
        return dict(delta=delta, text=str(delta), css='delta-down', symbol='▼')
    return dict(delta=0, text='→', css='delta-stable', symbol='→')


def comparison_bar_chart(rows, bar_max_w=140, bar_h=10, row_gap=6, label_w=88):
    """SVG layout for grouped current vs prior horizontal bars (scores 1–5)."""
    chart_rows = []
    y = 0
    for row in rows:
        current = int(row['current'])
        prior = row.get('prior')
        chart_rows.append(dict(
            label=row['label'],
            current=current,
            prior=prior,
            current_w=round((current / 5.0) * bar_max_w, 1),
            prior_w=round((int(prior) / 5.0) * bar_max_w, 1) if prior is not None else 0,
            y=y,
            label_x=0,
            bar_x=label_w,
            current_y=y,
            prior_y=y + bar_h + 3,
            delta=score_delta_badge(current, prior),
        ))
        y += bar_h * 2 + row_gap + 14
    return dict(
        rows=chart_rows,
        width=label_w + bar_max_w + 36,
        height=max(y, 1),
        bar_max_w=bar_max_w,
        bar_h=bar_h,
        label_w=label_w,
    )


def composite_donut_chart(current, prior=None, size=96, stroke=10):
    """Progress ring for composite score (1–5 scale). Optional ghost ring for prior month."""
    cx = cy = size / 2
    r = (size - stroke) / 2
    circ = 2 * math.pi * r
    cur_pct = max(0, min(1, float(current) / 5.0))
    cur_len = round(cur_pct * circ, 2)
    cur_gap = round(circ - cur_len, 2)
    prior_pct = None
    prior_len = prior_gap = None
    if prior is not None:
        prior_pct = max(0, min(1, float(prior) / 5.0))
        prior_len = round(prior_pct * circ, 2)
        prior_gap = round(circ - prior_len, 2)
    return dict(
        size=size,
        cx=cx,
        cy=cy,
        r=r,
        stroke=stroke,
        circ=round(circ, 2),
        current=current,
        prior=prior,
        cur_dash=f'{cur_len} {cur_gap}',
        prior_dash=f'{prior_len} {prior_gap}' if prior_len is not None else None,
    )


def column_bar_chart(items, bar_w=28, gap=12, max_h=84, label_h=20, axis_w=18, title=''):
    """Vertical column chart for scores 1–5 with axis labels and bar tracks."""
    n = len(items)
    chart_x = axis_w + 4
    width = chart_x + max(n * (bar_w + gap) + gap, bar_w + gap * 2)
    height = max_h + label_h + 14
    cols = []
    y_ticks = []
    for level in range(1, 6):
        y = round(max_h - (level / 5.0) * max_h, 1)
        y_ticks.append(dict(level=level, y=y, label_x=axis_w - 2))
    for i, item in enumerate(items):
        score = int(item['score'])
        h = round((score / 5.0) * max_h, 1)
        x = chart_x + gap + i * (bar_w + gap)
        cols.append(dict(
            label=item['label'],
            score=score,
            x=x,
            y=max_h - h,
            w=bar_w,
            h=h,
            track_y=0,
            track_h=max_h,
            text_x=round(x + bar_w / 2, 1),
            label_x=round(x + bar_w / 2, 1),
        ))
    return dict(
        width=width,
        height=height,
        max_h=max_h,
        cols=cols,
        label_y=max_h + label_h,
        axis_x=chart_x - 2,
        axis_y=max_h,
        y_ticks=y_ticks,
        title=title,
    )


def horizontal_score_bars(items, bar_max_w=168, bar_h=16, label_w=78, row_gap=10, score_w=22):
    """Aligned horizontal bars with label, track, fill, and score value."""
    rows = []
    y = 0
    for item in items:
        score = int(item['score'])
        fill_w = round((score / 5.0) * bar_max_w, 1)
        rows.append(dict(
            label=item['label'],
            score=score,
            y=y,
            label_x=0,
            label_y=y + bar_h - 3,
            bar_x=label_w,
            bar_y=y,
            track_w=bar_max_w,
            fill_w=fill_w,
            score_x=label_w + bar_max_w + 8,
            score_y=y + bar_h - 3,
        ))
        y += bar_h + row_gap
    return dict(
        rows=rows,
        width=label_w + bar_max_w + score_w + 10,
        height=max(y, 1),
        bar_h=bar_h,
        bar_max_w=bar_max_w,
        label_w=label_w,
    )


def score_ring_row(items, ring_size=58, stroke=7, gap=12):
    """Row of labeled mini progress rings (1–5 scale)."""
    rings = []
    x = 0
    for item in items:
        score = int(item['score'])
        donut = composite_donut_chart(score, size=ring_size, stroke=stroke)
        rings.append(dict(
            label=item['label'],
            score=score,
            x=x,
            donut=donut,
            label_x=round(x + ring_size / 2, 1),
            label_y=ring_size + 12,
        ))
        x += ring_size + gap
    return dict(rings=rings, width=max(x - gap, ring_size), height=ring_size + 18, ring_size=ring_size)


def composite_sparkline(snapshots, turma, student_name, report_month, current_composite, max_points=4):
    """SVG sparkline of composite scores across recent months (needs ≥2 points)."""
    from report_periods import _snapshot_key, month_label, previous_calendar_month, student_snapshot_id

    if not report_month:
        return None
    sid = student_snapshot_id(turma, student_name)
    points = [dict(
        month=report_month,
        label=month_label(report_month)[:3],
        score=int(current_composite),
    )]
    month = report_month
    for _ in range(max_points - 1):
        month = previous_calendar_month(month)
        if not month:
            break
        snap = (snapshots or {}).get(_snapshot_key(turma, sid, month))
        if not snap or snap.get('composite_score') is None:
            break
        points.insert(0, dict(
            month=month,
            label=month_label(month)[:3],
            score=int(snap['composite_score']),
        ))
    if len(points) < 2:
        return None

    w, h, pad_x, pad_y = 132, 40, 6, 4
    step = (w - 2 * pad_x) / max(len(points) - 1, 1)
    plotted = []
    for i, p in enumerate(points):
        x = round(pad_x + i * step, 1)
        y = round(h - pad_y - (p['score'] / 5.0) * (h - 2 * pad_y), 1)
        plotted.append(dict(x=x, y=y, **p))
    path = 'M ' + ' L '.join(f"{pt['x']},{pt['y']}" for pt in plotted)
    return dict(width=w, height=h, path=path, points=plotted)


def class_summary_charts(student_data):
    """Class-level averages bar chart and attendance tier distribution."""
    from report_periods import student_composite_score

    if not student_data:
        return None
    labels = ['Presença', 'Desenv.', 'Particip.', 'Comport.']
    keys = ['pres_score', 'dev_overall', 'part_overall', 'comp_overall']
    avgs = [
        round(sum(sd[k] for sd in student_data) / len(student_data), 1)
        for k in keys
    ]
    bars = comparison_bar_chart(
        [dict(label=l, current=max(1, min(5, int(round(a)))), prior=None) for l, a in zip(labels, avgs)],
        bar_max_w=200,
        bar_h=12,
        row_gap=4,
    )
    total = len(student_data)
    present = sum(1 for sd in student_data if sd['pct'] >= 80)
    partial = sum(1 for sd in student_data if 50 <= sd['pct'] < 80)
    low = total - present - partial
    slices = [
        dict(label='≥80%', count=present, color='#5B2D8E'),
        dict(label='50–79%', count=partial, color='#9B7BB8'),
        dict(label='<50%', count=low, color='#BBBBBB'),
    ]
    bar_w = 220
    x = 0
    for sl in slices:
        sl['w'] = round((sl['count'] / total) * bar_w, 1) if total else 0
        sl['x'] = x
        x += sl['w']
    column_chart = column_bar_chart(
        [dict(label=l, score=max(1, min(5, int(round(a))))) for l, a in zip(labels, avgs)],
        title='Médias da turma',
        bar_w=32,
        gap=14,
    )
    return dict(
        student_count=total,
        averages=avgs,
        bars=bars,
        column_chart=column_chart,
        dimension_rings=score_ring_row([
            dict(label=l, score=max(1, min(5, int(round(a)))))
            for l, a in zip(labels, avgs)
        ], ring_size=52, stroke=6, gap=10),
        attendance_bar=dict(width=bar_w, height=14, slices=slices),
        composite_avg=round(
            sum(student_composite_score(sd) for sd in student_data) / total, 1,
        ),
        composite_donut=composite_donut_chart(
            max(1, min(5, int(round(
                sum(student_composite_score(sd) for sd in student_data) / total,
            )))),
            size=88,
            stroke=9,
        ),
    )


def expanded_radar_scores(dev_scores, part_overall, pres_score):
    """7-axis scores for an extended skills radar (dev + participação + presença)."""
    return list(dev_scores) + [part_overall, pres_score]


def heptagon_polygon(scores, cx=100, cy=105, max_r=78):
    """Return SVG polygon points for a 7-axis radar chart."""
    pts = []
    n = len(scores)
    for i, s in enumerate(scores):
        angle = -math.pi / 2 + i * 2 * math.pi / n
        r = (float(s) / 5.0) * max_r
        x = round(cx + r * math.cos(angle), 2)
        y = round(cy + r * math.sin(angle), 2)
        pts.append(f'{x},{y}')
    return ' '.join(pts)


def heptagon_grid(cx=100, cy=105, max_r=78, n=7):
    rings = []
    for level in range(1, 6):
        r = (level / 5.0) * max_r
        pts = []
        for i in range(n):
            angle = -math.pi / 2 + i * 2 * math.pi / n
            x = round(cx + r * math.cos(angle), 2)
            y = round(cy + r * math.sin(angle), 2)
            pts.append(f'{x},{y}')
        rings.append(' '.join(pts))
    return rings


def heptagon_axes(cx=100, cy=105, max_r=78, n=7):
    eps = []
    for i in range(n):
        angle = -math.pi / 2 + i * 2 * math.pi / n
        x = round(cx + max_r * math.cos(angle), 2)
        y = round(cy + max_r * math.sin(angle), 2)
        eps.append((x, y))
    return eps


EXPANDED_RADAR_LABELS = [
    'Audição', 'Fala', 'Gramática', 'Escrita', 'Leitura', 'Participação', 'Presença',
]


def build_month_comparison(ctx, snapshots, turma, student_name, report_month, trend=None):
    from report_periods import month_label, prior_month_snapshot, previous_calendar_month, student_composite_score

    prev_month = previous_calendar_month(report_month)
    prior = prior_month_snapshot(snapshots or {}, turma, student_name, report_month)
    composite = student_composite_score(ctx)
    prior_composite = prior.get('composite_score') if prior else None

    dim_rows = []
    for label, key in COMPARISON_DIMS:
        current = ctx[key]
        prior_val = prior.get(key) if prior else None
        dim_rows.append(dict(
            label=label,
            key=key,
            current=current,
            prior=prior_val,
            delta=score_delta_badge(current, prior_val),
        ))

    return dict(
        has_prior=prior is not None,
        prior_month=prev_month,
        prior_month_label=month_label(prev_month) if prev_month else '',
        composite_current=composite,
        composite_prior=prior_composite,
        composite_delta=score_delta_badge(composite, prior_composite),
        trend=trend,
        dims=dim_rows,
        bars=comparison_bar_chart(dim_rows),
        donut=composite_donut_chart(composite, prior_composite),
    )


def pie_path(percentage, cx=58, cy=58, r=48):
    """Return (svg_path_d, is_full_circle) for a clockwise attendance pie slice."""
    pct = float(percentage)
    if pct >= 100:
        return f"M {cx},{cy-r} A {r},{r} 0 1,1 {cx - 0.01},{cy-r} Z", True
    angle = (pct / 100) * 2 * math.pi - math.pi / 2
    ex = round(cx + r * math.cos(angle), 2)
    ey = round(cy + r * math.sin(angle), 2)
    large = 1 if pct > 50 else 0
    d = f"M {cx},{cy} L {cx},{cy-r} A {r},{r} 0 {large},1 {ex},{ey} Z"
    return d, False


# ── Data helpers ──────────────────────────────────────────────────────────────

def load_csv(path):
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def int_score(val, default=3):
    try:
        return max(1, min(5, int(float(val))))
    except (TypeError, ValueError):
        return default


def avg_score(scores):
    vals = [float(s) for s in scores if str(s).strip()]
    return round(sum(vals) / len(vals)) if vals else 0


def presence_pct(faltas, total_lessons):
    if total_lessons == 0:
        return 100
    return round(((total_lessons - int(faltas or 0)) / total_lessons) * 100)


def pres_to_score(pct):
    if pct >= 95:
        return 5
    if pct >= 85:
        return 4
    if pct >= 75:
        return 3
    if pct >= 65:
        return 2
    return 1


def missed_lessons(student, all_lessons):
    raw = student.get("missed_aulas", "").strip()
    if not raw:
        return []
    turma = (student.get("turma") or "").strip()
    if not turma:
        return []
    nums = {n.strip() for n in raw.split(",") if n.strip()}
    return [
        lesson
        for lesson in all_lessons
        if lesson.get("turma") == turma and lesson.get("aula_num", "").strip() in nums
    ]


def lessons_for(turma, all_lessons, report_month=None):
    rows = [
        lesson
        for lesson in all_lessons
        if (lesson.get('turma') or '').strip() == turma
        and (lesson.get('aula_num') or '').strip()
    ]
    if not report_month:
        return rows
    from report_periods import lesson_in_month
    return [lesson for lesson in rows if lesson_in_month(lesson, report_month)]


def needs_extra(student):
    ae = student.get("aula_extra", "").strip().lower()
    return ae in ("reforço", "reforco", "reposição", "reposicao")


def group_by_turma(students):
    groups = {}
    for s in students:
        turma = (s.get("turma") or "").strip()
        if not turma:
            continue
        groups.setdefault(turma, []).append(s)
    return groups


# ── Report builders ───────────────────────────────────────────────────────────

def build_student_ctx(s, all_lessons, report_month=None, trend=None, snapshots=None):
    from report_periods import month_label

    turma = (s.get("turma") or "").strip()
    if not turma:
        raise ValueError('Student row is missing turma')
    turma_lessons = lessons_for(turma, all_lessons, report_month=report_month)
    total = len(turma_lessons)
    missed = missed_lessons(s, all_lessons)
    if report_month:
        from report_periods import lesson_in_month
        missed = [m for m in missed if lesson_in_month(m, report_month)]
        faltas = len(missed)
    else:
        try:
            faltas = max(0, int(float(s.get("faltas") or 0)))
        except (TypeError, ValueError):
            faltas = 0

    pct = presence_pct(faltas, total)
    pie_d, full_circle = pie_path(pct)
    pres_score = pres_to_score(pct)
    needs_makeup = (s.get("aula_extra", "").strip().lower() in ("reposição", "reposicao"))

    # Participação: Contribuição oral, Foco e atenção, Trabalho em equipe
    part_scores = [
        int_score(s.get("participacao", 3)),
        int_score(s.get("foco", 3)),
        int_score(s.get("trabalho_equipe") or s.get("comportamento", 3)),
    ]
    part_overall = avg_score(part_scores)

    # Desenvolvimento: Audição, Fala, Gramática, Escrita, Leitura
    dev_scores = [
        int_score(s.get("listening", 3)),
        int_score(s.get("speaking", 3)),
        int_score(s.get("gramatica", 3)),
        int_score(s.get("writing", 3)),
        int_score(s.get("reading", 3)),
    ]
    dev_overall = avg_score(dev_scores)
    dev_labels = ["Audição", "Fala", "Gramática", "Escrita", "Leitura"]

    # Comportamento: Organização, Pontualidade, Respeito
    comp_scores = [
        int_score(s.get("organizacao") or s.get("comportamento", 3)),
        int_score(s.get("pontualidade") or s.get("comportamento", 3)),
        int_score(s.get("respeito_regras") or s.get("comportamento", 3)),
    ]
    comp_overall = avg_score(comp_scores)

    expanded_scores = expanded_radar_scores(dev_scores, part_overall, pres_score)
    part_labels = ['Oral', 'Foco', 'Equipe']
    comp_labels = ['Organização', 'Pontualidade', 'Respeito']
    ctx = dict(
        student=s,
        report_month=report_month,
        report_month_label=month_label(report_month) if report_month else '',
        trend=trend,
        pct=pct,
        pie_d=pie_d,
        full_circle=full_circle,
        missed=missed,
        pres_score=pres_score,
        needs_makeup=needs_makeup,
        part_scores=part_scores,
        part_overall=part_overall,
        dev_scores=dev_scores,
        dev_overall=dev_overall,
        dev_labels=dev_labels,
        pentagon=pentagon_polygon(dev_scores),
        grid=pentagon_grid(),
        axes=axis_endpoints(),
        skill_columns=skill_column_charts(dev_scores),
        dev_column_chart=column_bar_chart([
            dict(label=dev_labels[i], score=dev_scores[i]) for i in range(len(dev_scores))
        ], title='Habilidades'),
        part_column_chart=column_bar_chart([
            dict(label=part_labels[i], score=part_scores[i]) for i in range(len(part_scores))
        ], title='Critérios'),
        comp_column_chart=column_bar_chart([
            dict(label=comp_labels[i], score=comp_scores[i]) for i in range(len(comp_labels))
        ], title='Critérios'),
        comp_labels=comp_labels,
        horizontal_dev_bars=horizontal_score_bars([
            dict(label=dev_labels[i], score=dev_scores[i]) for i in range(len(dev_labels))
        ]),
        dimension_rings=score_ring_row([
            dict(label='Presença', score=pres_score),
            dict(label='Desenv.', score=dev_overall),
            dict(label='Particip.', score=part_overall),
            dict(label='Comport.', score=comp_overall),
        ]),
        comp_scores=comp_scores,
        comp_overall=comp_overall,
        expanded_radar=heptagon_polygon(expanded_scores),
        expanded_grid=heptagon_grid(n=len(expanded_scores)),
        expanded_axes=heptagon_axes(n=len(expanded_scores)),
        expanded_labels=EXPANDED_RADAR_LABELS,
        comparison=None,
        composite_sparkline=None,
    )
    if report_month:
        ctx['comparison'] = build_month_comparison(
            ctx, snapshots, turma, s.get('student_name', ''), report_month, trend=trend,
        )
        for dim in ctx['comparison']['dims']:
            ctx[f"{dim['key']}_delta"] = dim['delta']
        from report_periods import student_composite_score
        ctx['composite_sparkline'] = composite_sparkline(
            snapshots, turma, s.get('student_name', ''), report_month,
            student_composite_score(ctx),
        )
    return ctx


def build_class_ctx(turma, students, all_lessons, report_month=None, snapshots=None):
    from report_periods import compute_month_trend, month_label, student_composite_score

    turma_lessons = lessons_for(turma, all_lessons, report_month=report_month)
    info = students[0]
    snapshots = snapshots or {}

    student_data = []
    for s in students:
        trend = None
        if report_month:
            ctx_for_score = build_student_ctx(s, all_lessons, report_month=report_month)
            composite = student_composite_score(ctx_for_score)
            trend = compute_month_trend(
                composite, report_month, snapshots,
                s.get('turma', ''), s.get('student_name', ''),
            )
        ctx = build_student_ctx(
            s, all_lessons, report_month=report_month, trend=trend, snapshots=snapshots,
        )
        student_data.append(ctx)

    return dict(
        turma=turma,
        turma_display=info.get("turma_display", turma),
        nivel=info.get("nivel", ""),
        horario=info.get("horario", ""),
        teacher=info.get("teacher", ""),
        report_month=report_month,
        report_month_label=month_label(report_month) if report_month else '',
        lessons=turma_lessons,
        students=student_data,
        class_summary=class_summary_charts(student_data),
        grid=pentagon_grid(),
        axes=axis_endpoints(),
    )


# ── Output generators ─────────────────────────────────────────────────────────

def create_report_environment(template_dir):
    return Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(("html", "xml")),
    )


def generate_individual_reports(students, lessons, env, out_dir, report_month=None, snapshots=None):
    from report_periods import compute_month_trend, month_label, student_composite_score
    tpl = env.get_template("individual_report.html")
    snapshots = snapshots or {}
    for s in students:
        turma = (s.get('turma') or '').strip()
        student_name = (s.get('student_name') or '').strip()
        if not turma or not student_name:
            print(f"  ⚠ skipping student row missing turma/name: {s!r}")
            continue
        trend = None
        if report_month:
            base_ctx = build_student_ctx(s, lessons, report_month=report_month)
            composite = student_composite_score(base_ctx)
            trend = compute_month_trend(
                composite, report_month, snapshots,
                turma, student_name,
            )
        ctx = build_student_ctx(
            s, lessons, report_month=report_month, trend=trend, snapshots=snapshots,
        )
        if report_month:
            ctx['report_month_label'] = month_label(report_month)
        html = tpl.render(**ctx)
        fname = student_report_filename(turma, student_name, report_month)
        safe_child_path(out_dir, fname).write_text(html, encoding="utf-8")
        print(f"  ✓ {fname}")


def generate_class_diagnostics(students, lessons, env, out_dir, report_month=None, snapshots=None):
    tpl = env.get_template("class_diagnostic.html")
    snapshots = snapshots or {}
    for turma, group in group_by_turma(students).items():
        ctx = build_class_ctx(turma, group, lessons, report_month=report_month, snapshots=snapshots)
        html = tpl.render(**ctx)
        fname = class_diagnostic_filename(turma, report_month)
        safe_child_path(out_dir, fname).write_text(html, encoding="utf-8")
        print(f"  ✓ {fname}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    base = Path(__file__).parent
    data_dir = base / "data"
    tmpl_dir = base / "templates"
    out_dir = base / "output"
    out_dir.mkdir(exist_ok=True)

    students_file = data_dir / "students.csv"
    lessons_file = data_dir / "lessons.csv"

    if not students_file.exists():
        print(f"ERROR: {students_file} not found.", file=sys.stderr)
        sys.exit(1)
    if not lessons_file.exists():
        print(f"ERROR: {lessons_file} not found.", file=sys.stderr)
        sys.exit(1)

    students = load_csv(students_file)
    lessons = load_csv(lessons_file)

    env = create_report_environment(tmpl_dir)

    print("\nGenerating individual student reports...")
    generate_individual_reports(students, lessons, env, out_dir)

    print("\nGenerating class diagnostics...")
    generate_class_diagnostics(students, lessons, env, out_dir)

    print(f"\nDone! {len(students)} student reports + {len(group_by_turma(students))} class diagnostics → {out_dir}/")


if __name__ == "__main__":
    main()
