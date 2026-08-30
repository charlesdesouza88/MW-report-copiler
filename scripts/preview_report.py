#!/usr/bin/env python3
"""Generate sample report HTML and open in the default browser (local design preview)."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from compiler import (
    create_report_environment,
    generate_class_diagnostics,
    generate_individual_reports,
    load_csv,
)


def main():
    students_path = ROOT / 'data' / 'students.csv'
    lessons_path = ROOT / 'data' / 'lessons.csv'
    if not students_path.exists() or not lessons_path.exists():
        print('Missing data/students.csv or data/lessons.csv')
        sys.exit(1)

    out_dir = ROOT / 'output' / 'preview'
    out_dir.mkdir(parents=True, exist_ok=True)

    students = load_csv(students_path)
    lessons = load_csv(lessons_path)
    if not students:
        print('No students in data/students.csv')
        sys.exit(1)

    sample = students[0]
    turma = (sample.get('turma') or '').strip()
    class_students = [s for s in students if (s.get('turma') or '').strip() == turma][:6]
    report_month = None
    for lesson in lessons:
        date = (lesson.get('date') or '').strip()
        if len(date) >= 10 and date[6:10].isdigit():
            report_month = f'{date[6:10]}-{date[3:5]}'
            break

    env = create_report_environment(ROOT / 'templates')
    generate_individual_reports(
        [sample], lessons, env, out_dir, report_month=report_month,
    )
    if class_students:
        generate_class_diagnostics(
            class_students, lessons, env, out_dir, report_month=report_month,
        )

    individual = next(out_dir.glob('*_report.html'), None)
    diagnostic = next(out_dir.glob('*_class_diagnostic.html'), None)
    if not individual:
        print('No report generated.')
        sys.exit(1)

    print('Preview files written to:')
    print(f'  {individual}')
    if diagnostic:
        print(f'  {diagnostic}')
    print('\nOpen in browser (animations show on screen, not in print preview):')

    to_open = individual.resolve().as_uri()
    print(f'  {to_open}')
    if sys.platform == 'darwin':
        subprocess.run(['open', str(individual)], check=False)
    elif sys.platform.startswith('linux'):
        subprocess.run(['xdg-open', str(individual)], check=False)


if __name__ == '__main__':
    main()
