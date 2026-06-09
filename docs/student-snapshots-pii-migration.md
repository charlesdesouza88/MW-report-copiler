# Student snapshots PII migration

## What changed

`data/student_snapshots.json` no longer stores student names. Each record uses a stable
`student_id` (SHA-256 hash of `turma|student_name`, truncated to 16 hex chars) so
month-over-month trends work without persisting PII in the snapshot file.

Real student names remain in **`data/students.csv`** (and per-teacher copies under
`data/teachers/*/students.csv`). Those files are the authoritative PII store for the app
at runtime. On Railway/production, keep them on the service volume or another secure
data store — not in public git history.

`data/student_snapshots.json` is listed in `.gitignore` and should be generated locally
or on the deployment environment when reports are compiled.

## Regenerating snapshots locally

After compiling reports for a month, the app calls `upsert_month_snapshots()` which writes
anonymized rows. You can also migrate an existing file:

```bash
python3 - <<'PY'
import json
from pathlib import Path
from report_periods import student_snapshot_id

path = Path("data/student_snapshots.json")
rows = json.loads(path.read_text(encoding="utf-8"))
out = []
for row in rows:
    name = (row.pop("student_name", "") or "").strip()
    if name == "Jane Doe" or row.get("is_test"):
        continue
    turma = (row.get("turma") or "").strip()
    if name and not row.get("student_id"):
        row["student_id"] = student_snapshot_id(turma, name)
    if row.get("student_id"):
        out.append(row)
path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"Wrote {len(out)} records")
PY
```

See `data/templates/student_snapshots.example.json` for the expected shape.

## Purging PII from git history

If `student_snapshots.json` (or other CSVs with names) was ever committed, remove it from
all history before pushing to a shared remote:

1. Install [git-filter-repo](https://github.com/newren/git-filter-repo):

   ```bash
   brew install git-filter-repo
   ```

2. **Back up the repo** (clone mirror or tarball).

3. Remove sensitive paths from history:

   ```bash
   git filter-repo --path data/student_snapshots.json --invert-paths
   git filter-repo --path data/students.csv --invert-paths
   git filter-repo --path-glob 'data/teachers/*/students.csv' --invert-paths
   ```

   Run one command per path group, or combine paths in a single invocation as needed.

4. Force-push all branches/tags (coordinate with collaborators — everyone must re-clone):

   ```bash
   git push --force --all
   git push --force --tags
   ```

5. Rotate any secrets that might have been exposed in old commits.

6. Keep production PII only on the deployment volume / secure storage; restore
   `students.csv` from your operational backup, not from git.

## Legacy snapshot files

`load_snapshots()` still accepts old records with `student_name` and derives `student_id`
on read, but new writes use `student_id` only. Re-save via report compilation or the
migration script above to drop legacy name fields from disk.
