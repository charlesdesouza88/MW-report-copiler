"""Print-page regression: A4 landscape must not clip Participação."""

from __future__ import annotations

import html as htmlmod
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from test_compiler import _lessons, _student

from compiler import build_student_ctx, create_report_environment

ROOT = Path(__file__).resolve().parent.parent
CHROME_MAC = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
PRINT_PROBE_JS = """
<script>
document.addEventListener('DOMContentLoaded', () => {
  const page = document.querySelector('.sheet').getBoundingClientRect();
  function clips(box, nodes) {
    return nodes.map(el => {
      const r = el.getBoundingClientRect();
      return {
        cls: (el.className || el.tagName).toString().slice(0, 80),
        dy: +(r.bottom - box.bottom).toFixed(1),
        dx: +(r.right - box.right).toFixed(1),
      };
    }).filter(x => x.dy > 1 || x.dx > 1);
  }
  const cards = [...document.querySelectorAll('.card')];
  const report = {
    pageH: +page.height.toFixed(1),
    pageClipped: clips(page, [...document.querySelectorAll('.sheet-head, .stat, .card')]),
    cards: cards.map((card, i) => {
      const kids = [...card.querySelectorAll(
        '.bar, .bar-note, .missed-line, .makeup, .cal, .radar, .skill-chips, .recs p'
      )];
      return {i, clipped: clips(card.getBoundingClientRect(), kids)};
    }),
  };
  // Text blocks inside a card must not overlap each other (clipping alone misses this).
  report.overlaps = [];
  cards.forEach((card, i) => {
    const blocks = [...card.querySelectorAll('.pres-top, .cal, .missed-title, .missed-line, .makeup, .bar, .radar, .skill-chips')];
    for (let a = 0; a < blocks.length; a++) {
      for (let b = a + 1; b < blocks.length; b++) {
        const r1 = blocks[a].getBoundingClientRect(), r2 = blocks[b].getBoundingClientRect();
        const ox = Math.min(r1.right, r2.right) - Math.max(r1.left, r2.left);
        const oy = Math.min(r1.bottom, r2.bottom) - Math.max(r1.top, r2.top);
        if (ox > 1 && oy > 1) report.overlaps.push({i, a: blocks[a].className, b: blocks[b].className});
      }
    }
  });
  document.documentElement.setAttribute('data-print-check', JSON.stringify(report));
});
</script>
"""


def _chrome_bin() -> Path | None:
    if CHROME_MAC.exists():
        return CHROME_MAC
    for name in ("google-chrome", "chromium", "chromium-browser"):
        found = shutil.which(name)
        if found:
            return Path(found)
    return None


def _render_busy_report() -> str:
    env = create_report_environment(ROOT / "templates")
    extra = [
        {
            "turma": "MASTER",
            "aula_num": str(i),
            "date": f"{i:02d}/01/2026",
            "licao_conteudo": f"L{i}",
            "atividade_extra": "",
            "habilidades": "",
        }
        for i in range(3, 12)
    ]
    return env.get_template("individual_report.html").render(
        **build_student_ctx(
            _student(
                feedback_participacao="Contribuição exemplar nas discussões da turma todos os dias.",
                feedback_foco="Atenção excelente durante as atividades e na hora da história.",
                feedback_trabalho_equipe="Trabalha muito bem com os colegas e ajuda quem precisa.",
                recomendacoes="Continuar lendo em voz alta em casa e revisar o vocabulário da semana com um adulto.",
                organizacao="4",
                pontualidade="5",
                respeito_regras="5",
            ),
            _lessons() + extra,
            report_month="2026-01",
        )
    )


def _render_sample_report(photos=None) -> str:
    """The repo's sample CSVs: attendance calendar + missed-lesson list in Presença."""
    from compiler import load_csv

    templates = ROOT / "data" / "templates"
    students = load_csv(templates / "students_template.csv")
    lessons = load_csv(templates / "lessons_template.csv")
    env = create_report_environment(ROOT / "templates")
    return env.get_template("individual_report.html").render(
        **build_student_ctx(students[0], lessons, report_month="2026-02", photos=photos)
    )


def _render_sample_report_with_photo() -> str:
    from student_photos import set_photo

    photos = set_photo([], "MASTER", "Jane Doe", "image/png", "iVBORw0KGgo=")
    html = _render_sample_report(photos)
    assert 'class="student-photo"' in html
    return html


def _force_print_css(html: str) -> str:
    return (
        html.replace("@media screen {", "@media screen and (min-width: 100000px) {")
        .replace("@media screen and (max-width: 860px)", "@media not all")
        .replace("@media print {", "@media all {")
    )


def test_print_css_fits_sheet_to_a4():
    html = _render_busy_report()
    print_css = html.split("@media print", 1)[1]
    assert "width: 297mm; height: 210mm" in print_css
    # Printed page is white (saves ink); only cards keep a hairline border.
    assert ".sheet { width: 297mm; height: 210mm; overflow: hidden; background: #fff; }" in print_css
    assert "print-color-adjust: exact" in print_css
    assert "Recomendações do professor" in html
    assert html.count('class="bar-note"') == 3


@pytest.mark.skipif(_chrome_bin() is None, reason="Chrome is required to measure print overflow")
@pytest.mark.parametrize(
    "render",
    [_render_busy_report, _render_sample_report, _render_sample_report_with_photo],
    ids=["busy", "sample", "sample-photo"],
)
def test_print_layout_does_not_clip_participacao(tmp_path: Path, render):
    html = _force_print_css(render()).replace("</body>", PRINT_PROBE_JS + "\n</body>")
    report = tmp_path / "report.html"
    report.write_text(html)
    profile = tmp_path / "chrome-profile"
    profile.mkdir()
    proc = subprocess.Popen(
        [
            str(_chrome_bin()),
            "--headless=new",
            "--disable-gpu",
            "--hide-scrollbars",
            "--window-size=1123,794",
            "--virtual-time-budget=4000",
            f"--user-data-dir={profile}",
            "--dump-dom",
            report.resolve().as_uri(),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    try:
        stdout, _ = proc.communicate(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout, _ = proc.communicate()
    text = (stdout or b"").decode("utf-8", "replace")
    match = re.search(r'data-print-check="([^"]*)"', text)
    assert match, "print probe script did not run"
    result = json.loads(htmlmod.unescape(match.group(1)))
    assert result["pageClipped"] == []
    assert result["overlaps"] == []
    for card in result["cards"]:
        assert card["clipped"] == [], card
