# Mister Wiz brand in this app

Source of truth: *Mister Wiz — Brand & Identity Guide* (Brand / ID folder).  
Code source of truth: `static/css/brand.css` and `static/img/`.

Purple leads, gold accents, plum grounds the text. Navy is **logo wordmark only**. Green and red are **functional feedback only**.

## Palette

| Name | Hex | CSS variable | Use |
|---|---|---|---|
| Primary purple | `#792D83` | `--purple` | Banners, headings, buttons, table headers |
| Dark purple | `#5A1A64` | `--purple-dk` | Secondary text, labels |
| Plum | `#2D1040` | `--plum` | Body text, login gradient |
| Lavender | `#F0E6F3` | `--purple-lt` | Soft fills, sidebar, row banding |
| Gold | `#EFD27E` | `--gold` | Highlights |
| Gold accent | `#EBB22E` | `--gold-accent` | Dividers, emphasis, active nav |
| Green | `#2C7A3F` | `--green` | Success / correct only |
| Red | `#E24B4A` | `--red` | Errors / danger only |
| Soft box | `#F9F5FA` | `--soft` / `--bg` | Page background, panels |
| Hairline | `#D9C7E0` | `--hairline` / `--border` | 1 px rules |

Navy `#1B1464` must not appear in UI chrome. Do not add other blues or greens.

On purple or plum, text must be **white** (or gold for small captions). Gray-on-purple table headers fail contrast.

## Typography

- **UI & reports:** Carlito (`static/fonts/`, SIL OFL), with Calibri as the Word/document face.
- Stack: `Carlito, Calibri, "Segoe UI", sans-serif` (`--font`).
- Do not retype the wordmark in another font.

## Logo files

Place from these masters. Never redraw, recolour, or CSS-filter the lockup.

| File | Use |
|---|---|
| `static/img/logo-primary.png` | Full colour on white |
| `static/img/logo-primary-transparent.png` | Login and light cards (includes *ESCOLA DE LÍDERES*) |
| `static/img/logo-primary-white.png` | Knockout on plum/purple (login, print) |
| `static/img/logo-stacked.png` | Compact / square colour mark |
| `static/img/logo-stacked-white.png` | Compact knockout |
| `static/img/logo-symbol.png` | App icon, favicon source |
| `static/img/favicon.png` | Browser tab |
| `static/img/logo-*-print.png` | Embedded in self-contained report HTML |

### Do

- Colour lockup on white or lavender.
- White knockout on plum, purple, or photography.
- Keep **3.81 : 1** when resizing the primary lockup (minimum ~120 px wide so the descriptor stays legible).
- Pair purple with gold for emphasis; plum for body text.

### Don't

- Stretch, squash, or rotate the logo.
- Recolour it, or use `filter: invert()` / drop shadows / outlines.
- Put the navy-and-purple logo on a dark background (the wordmark disappears).
- Use navy anywhere except inside the official lockup.

## Where it is applied

- **Login** — purple→plum gradient; primary colour lockup on the white card.
- **Dashboard shell** — lavender sidebar, gold rule under the mark, colour wordmark + symbol tile; active nav is purple with a gold inset. Nav uses the **Mister Wiz Icon Library** (24 grid, 2 px round stroke, `currentColor`).
- **Print reports** (`templates/`) — same purple/plum/gold tokens; logos inlined as data URIs so files stay self-contained. Individual reports embed a **subset of the Icon Library** (24 grid, 2 px round stroke, `currentColor`) because they cannot load the dashboard sprite. Header, overview strip, and the two-column body share a 12 px gutter so their outer edges line up.
- **Usuários** — table headers white on purple; row actions: larger **Perfil** button, **Contato** / **Editar** stacked and left-aligned with each other.

## Iconography

Source: *Mister Wiz Icon Library* in the Caratinga design-system export. Sprite: `static/img/icons.svg`. Macros: `web_templates/_macros/icons.html`.

- 24 px grid, **2 px** stroke, round caps and joins, one colour per icon.
- Purple (`currentColor` → `#792D83`) on lavender/white; **white** on purple/plum; gold `#EFD27E` only for emphasis.
- Sizes: 16 · 24 · 32 · 48. Do not go below 16 — use the Wiz symbol instead.
- Never fill, rotate, or combine two icons into one.
- Upload and Sair are the same stroke system (not on the 90-icon sheet; needed for app chrome).

When adding a colour, use a `var(--…)` from `brand.css`. If it is not in the table above, it is off-brand.
