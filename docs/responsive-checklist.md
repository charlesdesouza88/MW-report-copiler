# Responsive UI — Manual device checklist

Test on production or staging after deploy:

**Base URL:** `https://charlesdesouza88-mw-report-copiler-production.up.railway.app`

Use Chrome DevTools device toolbar at **375px** (phone), **768px** (tablet), and **1280px** (desktop). Test one real phone when possible.

| Route | Pass criteria |
|-------|----------------|
| `/login` | No horizontal scroll; submit button full width; inputs do not trigger iOS zoom; **primary colour lockup** on the white card (not inverted) |
| `/` | Stats readable; hamburger opens/closes drawer; generate button reachable; sidebar is **lavender** with the **colour** lockup |
| `/students` | Cards on phone (&lt;768px); table on tablet+; turma filter works on both views |
| `/admin/teachers` | **Perfil** tappable; Contato / Editar stacked and aligned; table headers **white on purple** (login history included) |
| `/upload` | Hero and CSV panels stack on phone; file picker tappable |
| `/students/new` and edit | Score buttons ≥44px; save visible without zoom |
| `/reports` | Preview / print / download buttons tappable |
| `/reports/preview/...` | Report readable without pinch-zoom; print dialog still OK; lockup not stretched |

## Pain points to watch

- Topbar actions overflowing behind drawer button
- iOS Safari: file inputs inside dropzones
- Long student names in cards
- Report preview: radar chart clipping (horizontal scroll inside card is OK). Overview tiles should share the same left/right edge as the two columns below.
- Dark text on purple headers (must be white — see `docs/brand.md`)
- Navy/purple wordmark on a dark panel (use knockout, never CSS invert). The sidebar is lavender, so it uses the **colour** lockup.

## Automated checks

```bash
pytest
./scripts/smoke_check.sh https://charlesdesouza88-mw-report-copiler-production.up.railway.app
```
