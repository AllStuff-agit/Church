"""테스트용 작은 테마 pptx 만들기 (9종 섹션, 종류별 상자 이름)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.util import Emu, Pt

import slides
from structure import THEME_KINDS

BOXES = {
    "교독문": ["교독문제목", "교독문본문"],
    "본문표지": ["성경구절", "설교제목"],
    "말씀구절": ["구절본문", "구절장"],
}


def _box(slide, name, top, text, colors=None):
    tb = slide.shapes.add_textbox(Emu(500000), Emu(top), Emu(11000000), Emu(3000000))
    tb.name = name
    tf = tb.text_frame
    tf.text = text
    if colors:  # 단락별 색 견본: 첫 단락 인도색, 둘째 단락 회중색
        tf.paragraphs[0].runs[0].font.color.rgb = RGBColor.from_string(colors[0])
        p = tf.add_paragraph()
        r = p.add_run()
        r.text = "회중 견본"
        r.font.color.rgb = RGBColor.from_string(colors[1])
    for p in tf.paragraphs:
        for r in p.runs:
            r.font.size = Pt(28)
    return tb


def make_mini_theme(path: Path, skip_kind: str | None = None, rename: tuple | None = None) -> Path:
    prs = Presentation()
    prs.slide_width, prs.slide_height = Emu(12192000), Emu(6858000)
    layout = prs.slide_layouts[6]
    kinds = [k for k in THEME_KINDS if k != skip_kind]
    for kind in kinds:
        s = prs.slides.add_slide(layout)
        _box(s, "표지글", 100000, kind)
        for i, name in enumerate(BOXES.get(kind, [])):
            if rename and rename[0] == name:
                name = rename[1]
            colors = ("7F7F7F", "000000") if name == "교독문본문" else None
            _box(s, name, 900000 + i * 3000000, f"{name} 견본", colors)
    slides.set_sections(prs, [(k, 1) for k in kinds])
    prs.save(path)
    return path
