"""Helpers for spreadsheet-safe CSV downloads."""

import csv
import io

FORMULA_PREFIXES = ('=', '+', '-', '@', '\t', '\r')


def neutralize_formula_cell(value):
    """Prevent spreadsheet apps from interpreting exported text as a formula."""
    if isinstance(value, str) and value.startswith(FORMULA_PREFIXES):
        return f"'{value}"
    return value


def neutralize_formula_rows(rows):
    return [
        {field: neutralize_formula_cell(value) for field, value in row.items()}
        for row in rows
    ]


def csv_text(fieldnames, rows, *, bom=False):
    """Return CSV text safe for Excel/Sheets downloads."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction='ignore')
    writer.writeheader()
    writer.writerows(neutralize_formula_rows(rows))
    text = buf.getvalue()
    return f'\ufeff{text}' if bom else text
