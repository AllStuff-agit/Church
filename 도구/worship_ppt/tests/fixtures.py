"""테스트용 작은 테마 pptx 만들기 (9종 섹션, 종류별 상자 이름)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.util import Emu, Pt

import slides
from structure import THEME_KINDS

LEADER, PEOPLE, LABEL, REF = "6B7280", "1F2A5A", "6B7280", "9A9A9A"
BOXES = {
    "본문표지": ["성경구절", "설교제목"],
    "말씀구절": ["구절본문", "구절장"],
}


def _box(slide, name, top, text, size=28, height=3000000):
    tb = slide.shapes.add_textbox(Emu(500000), Emu(top), Emu(11000000), Emu(height))
    tb.name = name
    tb.text_frame.text = text
    tb.text_frame.word_wrap = True
    tb.text_frame.paragraphs[0].runs[0].font.size = Pt(size)
    return tb


def _gyodokmun_body(slide):
    """견본 문단 4개: 인도 / 회중 / (다같이) / 다같이 본문 + 장절 조각."""
    tb = _box(slide, "교독문본문", 900000, "인도 견본", 24, 5500000)
    tf = tb.text_frame
    tf.paragraphs[0].runs[0].font.color.rgb = RGBColor.from_string(LEADER)
    for text, size, color in (("회중 견본", 28, PEOPLE), ("(다같이)", 24, LABEL), ("다같이 견본", 28, PEOPLE)):
        r = tf.add_paragraph().add_run()
        r.text, r.font.size, r.font.color.rgb = text, Pt(size), RGBColor.from_string(color)
    ref = tf.paragraphs[3].add_run()
    ref.text, ref.font.size, ref.font.color.rgb = " (1-6)", Pt(20), RGBColor.from_string(REF)


def make_mini_theme(path: Path, skip_kind: str | None = None, rename: tuple | None = None, cover: bool = True) -> Path:
    prs = Presentation()
    prs.slide_width, prs.slide_height = Emu(12192000), Emu(6858000)
    layout = prs.slide_layouts[6]
    sections = []
    for kind in (k for k in THEME_KINDS if k != skip_kind):
        count = 0
        if kind == "교독문" and cover:
            s = prs.slides.add_slide(layout)
            _box(s, "교독문번호", 2000000, "교독문 1번")
            _box(s, "교독문부제", 4000000, "제목", 24)
            count += 1
        s = prs.slides.add_slide(layout)
        _box(s, "표지글", 100000, kind, 12, 300000)
        if kind == "교독문":
            _box(s, "교독문제목", 400000, "교독문 1번", 20, 400000)
            _gyodokmun_body(s)
        for i, name in enumerate(BOXES.get(kind, [])):
            if rename and rename[0] == name:
                name = rename[1]
            _box(s, name, 900000 + i * 3000000, f"{name} 견본")
        sections.append((kind, count + 1))
    slides.set_sections(prs, sections)
    prs.save(path)
    return path
