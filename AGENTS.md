# AGENTS.md

## Cursor Cloud specific instructions

This is a Python 3.12 **Flask** web dashboard plus a CLI report compiler ("Mister Wiz Report Compiler"). See `README.md` for full command reference and the data model. Notes below are the non-obvious bits for working in the Cloud VM.

### Services / how to run

- **Flask dashboard** (primary product): `.venv/bin/python app.py`. Dev server binds `0.0.0.0:5000` and auto-picks a free port if 5000 is busy (see the `__main__` block in `app.py`). `scripts/dev.sh` is an alternative that runs the test suite first, then starts the server.
- **CLI compiler**: `.venv/bin/python compiler.py` writes reports to `output/` (gitignored). See caveat below.
- Always use the project virtualenv at `.venv` (created by the startup update script). System `python3` has no third-party packages.

### Required local config (`.env`)

- The app needs a `.env` (gitignored, so not present on a fresh clone — create it). Minimum for local dev in CSV mode:
  - `SUPERADMIN_EMAIL`, `SUPERADMIN_PASSWORD` — bootstrap login. **Login fails if `SUPERADMIN_PASSWORD` is empty.** The superadmin account is created/reconciled from these on startup.
  - `SECRET_KEY` — any long random string (Flask sessions).
- Storage mode is chosen at runtime: **CSV mode is the default**; **DB mode activates only when `DATABASE_URL` is set**. No database is required to run the app or the tests locally.

### Tests / lint / build

- Tests: `.venv/bin/python -m pytest -q` (240 tests, all passing). Config in `pytest.ini` (`pythonpath = .`, `testpaths = tests`). Tests run fully in-process with CSV/JSON storage — no DB or running server needed.
- **No lint tooling is configured** (no flake8/ruff/black/pylint config or deps). "Lint" is not a separate step in this repo.
- No build step for local dev. Production build is the `Dockerfile` (gunicorn), used by Railway (`railway.json`); not needed for development.

### Gotchas

- **CLI `compiler.py` is strict about lesson data**: it aborts with `ERROR: no lessons found for turma(s): ...` if any student's `turma` in `data/students.csv` has no matching rows in `data/lessons.csv`. The committed sample data currently has this mismatch (`MASTER`, `TEENS_1` have students but no lessons), so a bare `python compiler.py` on the sample data exits early. The **web dashboard** report generation instead *skips* turmas without lessons (with a warning) and succeeds — prefer the dashboard "Relatórios → Regenerar" flow, or add matching `lessons.csv` rows, to exercise report generation end-to-end.
- The UI is primarily in **Portuguese** (e.g. "Relatórios" = Reports, "Regenerar" = Generate, "Alunos" = Students).
- A quick no-browser sanity check of the login + main pages: `.venv/bin/python scripts/smoke_journey.py`.
