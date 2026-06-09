#!/usr/bin/env python3
"""Convert teacher spreadsheets into MW report compiler CSV files."""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from csv_import import (  # noqa: E402
    convert_teacher_folder,
    convert_teacher_reports_root,
    merge_lessons,
    parse_atendimentos_csv,
    parse_lesson_plan_csv,
    parse_lessons_csv,
    parse_students_csv,
    parse_upload_csv,
    write_extra_sessions_csv,
    write_lessons_csv,
    write_students_csv,
)
from compiler import load_csv  # noqa: E402


def _read_text(path):
    return Path(path).read_text(encoding='utf-8-sig')


def convert_students(source, dest):
    rows, errors = parse_students_csv(_read_text(source))
    if errors:
        raise SystemExit('\n'.join(errors))
    write_students_csv(dest, rows)
    print(f'Wrote {len(rows)} student row(s) -> {dest}')


def convert_lessons(source, dest, merge_turma=None, merge_from=None):
    text = _read_text(source)
    rows, errors = parse_lessons_csv(text)
    if errors:
        rows, errors = parse_lesson_plan_csv(text)
    if errors:
        raise SystemExit('\n'.join(errors))

    if merge_turma or merge_from:
        base = load_csv(merge_from) if merge_from else []
        turma = merge_turma
        if not turma:
            if rows:
                turma = rows[0]['turma']
            elif base:
                turma = base[0]['turma']
            else:
                raise SystemExit(
                    'Cannot merge lessons: no rows parsed and --merge-turma not set.'
                )
        rows = merge_lessons(base, rows, turma=turma)
    write_lessons_csv(dest, rows)
    print(f'Wrote {len(rows)} lesson row(s) -> {dest}')


def convert_atendimentos(source, dest):
    rows, errors = parse_atendimentos_csv(_read_text(source))
    if errors:
        raise SystemExit('\n'.join(errors))
    write_extra_sessions_csv(dest, rows)
    print(f'Wrote {len(rows)} extra-session row(s) -> {dest}')


def _mirror_teacher_upload_files(teacher, students, lessons, source_dir):
    """Also write upload-ready students.csv + lessons.csv beside the teacher sources."""
    teacher_dir = Path(source_dir) / teacher
    if not teacher_dir.is_dir():
        return
    if students:
        write_students_csv(teacher_dir / 'students.csv', students)
        print(f'  mirrored -> {teacher_dir / "students.csv"}')
    if lessons:
        write_lessons_csv(teacher_dir / 'lessons.csv', lessons)
        print(f'  mirrored -> {teacher_dir / "lessons.csv"}')
    readme = teacher_dir / 'UPLOAD-TO-PROD.txt'
    readme.write_text(
        f'Upload to prod (Upload CSV page):\n\n'
        f'  1. students.csv  -> Alunos\n'
        f'  2. lessons.csv   -> Aulas\n\n'
        f'Do NOT upload monthly grade sheets (e.g. {teacher} - Abril-COMET.csv).\n'
        f'Use only students.csv and lessons.csv from this folder.\n',
        encoding='utf-8',
    )


def convert_teacher_reports(source_dir, data_dir, teacher=None):
    source_dir = Path(source_dir)
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    if teacher:
        teacher_dir = source_dir / teacher
        if not teacher_dir.is_dir():
            raise SystemExit(f'Pasta do professor não encontrada: {teacher_dir}')
        students, lessons, warnings = convert_teacher_folder(teacher_dir)
    else:
        students, lessons, warnings = convert_teacher_reports_root(source_dir)

    if not students and not lessons:
        raise SystemExit('Nenhum dado convertido — verifique a pasta Teacher report.')

    if students:
        dest = data_dir / 'students.csv'
        write_students_csv(dest, students)
        print(f'Wrote {len(students)} student row(s) -> {dest}')
        if teacher:
            _mirror_teacher_upload_files(teacher, students, lessons, source_dir)
    if lessons:
        dest = data_dir / 'lessons.csv'
        write_lessons_csv(dest, lessons)
        print(f'Wrote {len(lessons)} lesson row(s) -> {dest}')

    for note in warnings:
        print(f'  ! {note}')


def convert_bundle(downloads_dir, data_dir):
    downloads_dir = Path(downloads_dir)
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    students_src = downloads_dir / 'students.csv'
    if students_src.exists():
        convert_students(students_src, data_dir / 'students.csv')

    lesson_plan = next(downloads_dir.glob('*Plano de aula*.csv'), None)
    lessons_dest = data_dir / 'lessons.csv'
    if lesson_plan:
        convert_lessons(
            lesson_plan,
            lessons_dest,
            merge_turma='SPARK',
            merge_from=data_dir / 'lessons.csv' if lessons_dest.exists() else ROOT / 'data' / 'lessons.csv',
        )
    elif (downloads_dir / 'lessons.csv').exists():
        convert_lessons(downloads_dir / 'lessons.csv', lessons_dest)

    atendimentos = next(downloads_dir.glob('Atendimentos*.csv'), None)
    if atendimentos and atendimentos.exists():
        convert_atendimentos(atendimentos, data_dir / 'extra_sessions.csv')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)

    students = sub.add_parser('students', help='Convert students.csv (English or Portuguese headers)')
    students.add_argument('source')
    students.add_argument('dest')

    lessons = sub.add_parser('lessons', help='Convert lessons.csv or a teacher lesson plan export')
    lessons.add_argument('source')
    lessons.add_argument('dest')
    lessons.add_argument('--merge-turma', help='Replace only this turma in an existing lessons file')
    lessons.add_argument('--merge-from', help='Existing lessons.csv to merge into')

    atendimentos = sub.add_parser('atendimentos', help='Convert the atendimentos reference spreadsheet')
    atendimentos.add_argument('source')
    atendimentos.add_argument('dest')

    bundle = sub.add_parser('bundle', help='Convert known files from Downloads into data/')
    bundle.add_argument('--downloads-dir', default=str(Path.home() / 'Downloads' / 'MW report copiler'))
    bundle.add_argument('--data-dir', default=str(ROOT / 'data'))

    teacher_reports = sub.add_parser(
        'teacher-reports',
        help='Convert CSV files inside the Teacher report folder into upload-ready students.csv and lessons.csv',
    )
    teacher_reports.add_argument(
        '--source-dir',
        default=str(ROOT.parent / 'Teacher report '),
        help='Path to the Teacher report folder (one subfolder per teacher)',
    )
    teacher_reports.add_argument('--data-dir', default=str(ROOT / 'data'))
    teacher_reports.add_argument(
        '--teacher',
        help='Convert only one teacher folder, e.g. Amanda',
    )
    teacher_reports.add_argument(
        '--all',
        dest='all_teachers',
        action='store_true',
        help='Convert every teacher folder that has source CSVs',
    )

    args = parser.parse_args()

    if args.command == 'students':
        convert_students(args.source, args.dest)
    elif args.command == 'lessons':
        convert_lessons(args.source, args.dest, merge_turma=args.merge_turma, merge_from=args.merge_from)
    elif args.command == 'atendimentos':
        convert_atendimentos(args.source, args.dest)
    elif args.command == 'bundle':
        convert_bundle(args.downloads_dir, args.data_dir)
    elif args.command == 'teacher-reports':
        if getattr(args, 'all_teachers', False):
            source = Path(args.source_dir)
            for teacher_dir in sorted(source.iterdir()):
                if not teacher_dir.is_dir() or teacher_dir.name.startswith('.'):
                    continue
                has_source = any(
                    p.name.casefold() not in {'students.csv', 'lessons.csv'}
                    for p in teacher_dir.glob('*.csv')
                )
                if not has_source:
                    print(f'=== {teacher_dir.name} === (no source CSVs, skipped)')
                    continue
                print(f'=== {teacher_dir.name} ===')
                convert_teacher_reports(
                    args.source_dir,
                    str(Path(args.data_dir) / teacher_dir.name),
                    teacher=teacher_dir.name,
                )
                print()
        else:
            convert_teacher_reports(args.source_dir, args.data_dir, teacher=args.teacher)


if __name__ == '__main__':
    main()
