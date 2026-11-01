"""본문표지: 성경구절 표기와 설교 제목. 제목은 단순형(설교제목 상자) 또는 글자 배치형(본문 타이틀 묶음)."""
import copy
import re
from dataclasses import dataclass

from theme import TITLE_BOX, TITLE_GROUP, find_shape

P = "http://schemas.openxmlformats.org/presentationml/2006/main"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"

SMALL, MEDIUM = 0.77, 0.95
# 오해가 적은 조사만 자동으로 작게(이·가·도는 낱말 끝과 헷갈려 제외, 필요하면 (괄호)로 지정)
PARTICLES = ("에서", "으로", "에게", "께서", "을", "를", "은", "는", "의", "에", "로", "와", "과")
ADVANCE = 0.772      # 글자 폭 대비 다음 글자까지 거리(글자끼리 조금 겹침)
WORD_GAP = 0.43      # 기본 글자 폭 대비 낱말 사이 추가 간격
JITTER = (0.0, -0.035, -0.005, 0.02)  # 낱말 안 순번별 높이 흔들림(기본 높이 대비)
SINK = 0.7           # 작은 글자를 아래로 내리는 비율

# 초록잎들꽃 테마 측정값(본문 타이틀 묶음 내부 좌표, EMU)
BASE = {"w": 720360, "h": 926280, "top": 3182400, "size": 833628, "box_left": 1145880, "box_right": 8030160}


@dataclass
class Glyph:
    char: str
    scale: float
    dy: float
    word: int


def parse_title(text: str) -> list:
    """(괄호)는 작게·아래로, [대괄호]는 조금 작게, 표시 없는 낱말은 끝 조사를 자동으로 작게."""
    glyphs = []
    for wi, word in enumerate(text.split()):
        marked = bool(re.search(r"[()\[\]]", word))
        if not marked:
            for part in PARTICLES:
                if word.endswith(part) and len(word) > len(part):
                    word = f"{word[:-len(part)]}({part})"
                    break
        scale = 1.0
        for ch in word:
            if ch == "(":
                scale = SMALL
            elif ch == "[":
                scale = MEDIUM
            elif ch in ")]":
                scale = 1.0
            else:
                glyphs.append(Glyph(ch, scale, 0.0, wi))
    pos = {}
    for g in glyphs:
        n = pos.get(g.word, 0)
        pos[g.word] = n + 1
        g.dy = (1 - g.scale) * SINK + JITTER[n % len(JITTER)]
    return glyphs


def _line_width(glyphs, base) -> float:
    if not glyphs:
        return 0
    w = sum(base["w"] * g.scale * ADVANCE for g in glyphs[:-1]) + base["w"] * glyphs[-1].scale
    return w + base["w"] * WORD_GAP * sum(1 for a, b in zip(glyphs, glyphs[1:]) if a.word != b.word)


def _place(glyphs, base, factor, top_shift) -> list:
    avail_center = (base["box_left"] + base["box_right"]) / 2
    x = avail_center - _line_width(glyphs, base) * factor / 2
    out = []
    for i, g in enumerate(glyphs):
        w, h = base["w"] * g.scale * factor, base["h"] * g.scale * factor
        top = base["top"] + top_shift + (base["h"] * factor - h) * SINK + base["h"] * factor * (g.dy - (1 - g.scale) * SINK)
        out.append((int(x), int(top), int(w), int(h), int(base["size"] * g.scale * factor)))
        if i + 1 < len(glyphs):
            x += w * ADVANCE + (base["w"] * WORD_GAP * factor if glyphs[i + 1].word != g.word else 0)
    return out


def layout(glyphs: list, base: dict = BASE) -> list:
    """글자별 (left, top, width, height, font_size). 넘치면 줄이고, 많이 줄어야 하면 낱말 경계에서 두 줄."""
    avail = base["box_right"] - base["box_left"]
    factor = min(1.0, avail / _line_width(glyphs, base))
    words = sorted({g.word for g in glyphs})
    if factor >= 0.75 or len(words) < 2:
        return _place(glyphs, base, factor, 0)
    best = None
    for cut in words[1:]:
        a = [g for g in glyphs if g.word < cut]
        b = [g for g in glyphs if g.word >= cut]
        worst = max(_line_width(a, base), _line_width(b, base))
        if best is None or worst < best[0]:
            best = (worst, a, b)
    _, a, b = best
    factor = min(1.0, avail / best[0])
    gap = base["h"] * factor * 0.55
    lift = base["h"] * factor * 0.25  # 둘째 줄이 아래 장식에 닿지 않게 조금 올림
    return _place(a, base, factor, -gap - lift) + _place(b, base, factor, gap - lift)


def _set_text(shape, text: str) -> None:
    p = shape.text_frame.paragraphs[0]
    for r in p.runs[1:]:
        r._r.getparent().remove(r._r)
    p.runs[0].text = text


def _move(sp, x, y, w=None, h=None) -> None:
    xfrm = sp.find(f".//{{{A}}}xfrm")
    xfrm.find(f"{{{A}}}off").set("x", str(int(x)))
    xfrm.find(f"{{{A}}}off").set("y", str(int(y)))
    if w is not None:
        xfrm.find(f"{{{A}}}ext").set("cx", str(int(w)))
        xfrm.find(f"{{{A}}}ext").set("cy", str(int(h)))


def fill_cover(prs, slide_index: int, reference: str, title: str, base: dict = BASE) -> None:
    slide = prs.slides[slide_index]
    _set_text(find_shape(slide, "성경구절"), reference)
    box = find_shape(slide, TITLE_BOX)
    if box is not None:
        _set_text(box, title)
        return
    group = find_shape(slide, TITLE_GROUP)
    letters = [sh for sh in group.shapes if sh.name.startswith("설교제목글자")]
    sample = copy.deepcopy(letters[0]._element)
    anchor = letters[0]._element.getprevious()
    parent = letters[0]._element.getparent()
    for sh in letters:
        parent.remove(sh._element)
    next_id = max(int(e.get("id")) for e in slide._element.iter(f"{{{P}}}cNvPr")) + 1
    glyphs = parse_title(title)
    rects = layout(glyphs, base)
    for i, (g, (x, y, w, h, size)) in enumerate(zip(glyphs, rects)):
        sp = copy.deepcopy(sample)
        c_nv = sp.find(f".//{{{P}}}cNvPr")
        c_nv.set("id", str(next_id + i))
        c_nv.set("name", f"설교제목글자 {i + 1}")
        _move(sp, x, y, w, h)
        runs = sp.findall(f".//{{{A}}}r")
        for r in runs[1:]:
            r.getparent().remove(r)
        runs[0].find(f"{{{A}}}t").text = g.char
        runs[0].find(f"{{{A}}}rPr").set("sz", str(round(size / 127)))  # EMU → 1/100pt
        anchor.addnext(sp)
        anchor = sp
    quotes = find_shape(group, "따옴표")
    if quotes is not None:
        lq, rq = find_shape(quotes, "따옴표-left"), find_shape(quotes, "따옴표-right")
        left = min(r[0] for r in rects)          # 두 줄이면 더 긴 줄 기준으로 감싼다
        right = max(r[0] + r[2] for r in rects)
        top = min(r[1] for r in rects) - base["h"] * 0.1
        _move(lq._element, max(0, left - lq.width - base["w"] * 0.1), min(lq.top, top))
        _move(rq._element, right + base["w"] * 0.1, min(rq.top, top))
