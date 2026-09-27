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
  const page = document.body.getBoundingClientRect();
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
    pageClipped: clips(page, [...document.querySelectorAll('.header, .card, .recomendacoes')]),
    cards: cards.map((card, i) => {
      const kids = [...card.querySelectorAll(
        '.part-scores-row, .scale-item, .fb-item, .fb-heading, .no-makeup, .comp-criteria-item, .bar-label, .pie-cal'
      )];
      return {i, clipped: clips(card.getBoundingClientRect(), kids)};
    }),
  };
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


def _force_print_css(html: str) -> str:
    return (
        html.replace("@media screen {", "@media screen and (min-width: 100000px) {")
        .replace("@media screen and (max-width: 980px)", "@media not all")
        .replace("@media screen and (max-width: 720px)", "@media not all")
        .replace("@media print {", "@media all {")
    )


def test_print_css_places_feedback_beside_scores():
    html = _render_busy_report()
    print_css = html.split("@media print", 1)[1]
    assert '"scores feedback"' in print_css
    assert '"scale feedback"' in print_css
    assert "width: 42px" in print_css
    assert "Com excelência" in html
    assert "Feedback do professor" in html


@pytest.mark.skipif(_chrome_bin() is None, reason="Chrome is required to measure print overflow")
def test_print_layout_does_not_clip_participacao(tmp_path: Path):
    html = _force_print_css(_render_busy_report()).replace("</body>", PRINT_PROBE_JS + "\n</body>")
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
    for card in result["cards"]:
        assert card["clipped"] == [], card
