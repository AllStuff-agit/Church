"""테마 견본 슬라이드에 내용 채우기: 교독문."""
import copy
import math
import re

import slides
from theme import find_shape

A = "http://schemas.openxmlformats.org/drawingml/2006/main"

# 한 줄에 들어가는 글자 수 어림값(견본 상자 폭 기준)과 한 장에 넣을 화면 줄 수
GYO_CHARS = {"인도": 30, "회중": 25, "다같이": 25}
GYO_MAX_PAIRS, GYO_MAX_LINES = 3, 10
TAIL = re.compile(r"^(.*?)\s*((?:\((?:[^()]*\d[^()]*|아멘)\)\s*)+)$")


def split_tail(text: str) -> tuple:
    """줄 끝의 장절·(아멘)을 떼어 낸다: ('본문', '(1-6) (아멘)')."""
    m = TAIL.match(text.strip())
    return (m.group(1), re.sub(r"\s+", " ", m.group(2)).strip()) if m else (text.strip(), "")


def _cost(role: str, text: str, chars: dict) -> int:
    lines = math.ceil(len(split_tail(text)[0]) / chars[role]) or 1
    return lines + (1 if role == "다같이" else 0)  # (다같이) 표시 줄


def chars_per_line(shape) -> dict:
    """견본 상자 폭과 견본 문단 글자 크기로 역할별 한 줄 글자 수를 어림한다(한글 한 글자 폭 ≈ 글자 크기)."""
    width = shape.width - (shape.text_frame.margin_left or 0) - (shape.text_frame.margin_right or 0)
    sizes = [p.runs[0].font.size for p in shape.text_frame.paragraphs if p.runs]
    leader, people = sizes[0], sizes[1] if len(sizes) > 1 else sizes[0]
    together = sizes[3] if len(sizes) > 3 else people
    return {"인도": max(1, width // leader), "회중": max(1, width // people), "다같이": max(1, width // together)}


def paginate_gyodokmun(lines: list, max_pairs: int = GYO_MAX_PAIRS, max_lines: int = GYO_MAX_LINES,
                       chars: dict = GYO_CHARS) -> list:
    """인도+회중 쌍(또는 다같이 줄 하나)을 묶음으로, 한 장에 최대 max_pairs 묶음·max_lines 화면 줄."""
    groups, i = [], 0
    while i < len(lines):
        if lines[i][0] == "인도" and i + 1 < len(lines) and lines[i + 1][0] == "회중":
            groups.append(lines[i:i + 2]); i += 2
        else:
            groups.append(lines[i:i + 1]); i += 1
    pages, page, used = [], [], 0
    for g in groups:
        cost = sum(_cost(r, t, chars) for r, t in g)
        if page and (len(page) >= max_pairs or used + cost > max_lines):
            pages.append(page); page, used = [], 0
        page.append(g); used += cost
    if page:
        pages.append(page)
    return [[line for g in p for line in g] for p in pages]


def _set_text(shape, text: str) -> None:
    """첫 단락 첫 조각 서식을 살려 글자만 바꾼다."""
    tf = shape.text_frame
    for p in tf.paragraphs[1:]:
        p._p.getparent().remove(p._p)
    p = tf.paragraphs[0]
    for r in p.runs[1:]:
        r._r.getparent().remove(r._r)
    p.runs[0].text = text


def _paragraph(sample, text: str, tail: str, tail_sample):
    p = copy.deepcopy(sample)
    runs = p.findall(f"{{{A}}}r")
    for r in runs[1:]:
        p.remove(r)
    runs[0].find(f"{{{A}}}t").text = text
    if tail:
        t = copy.deepcopy(tail_sample)
        t.find(f"{{{A}}}t").text = " " + tail
        runs[0].addnext(t)
    return p


def _first_no_space(p) -> None:
    ppr = p.find(f"{{{A}}}pPr")
    if ppr is not None:
        for el in ppr.findall(f"{{{A}}}spcBef"):
            ppr.remove(el)


def _fill_body(shape, page: list) -> None:
    txb = shape.text_frame._txBody
    samples = txb.findall(f"{{{A}}}p")
    leader, people, label, together = (samples + samples[-1:] * 4)[:4]
    tail_sample = together.findall(f"{{{A}}}r")[-1]
    for p in samples:
        txb.remove(p)
    out = []
    for role, line in page:
        text, tail = split_tail(line)
        if role == "다같이":
            out.append(_paragraph(label, "(다같이)", "", tail_sample))
            out.append(_paragraph(together, text, tail, tail_sample))
        else:
            out.append(_paragraph(leader if role == "인도" else people, text, tail, tail_sample))
    _first_no_space(out[0])
    for p in out:
        txb.append(p)


def fill_gyodokmun(prs, section_slides: list, g) -> list:
    """교독문 섹션 견본(표지 장 선택, 본문 장 필수)을 채운다. [표지?, 본문 장들] 인덱스를 돌려준다."""
    cover = next((i for i in section_slides if find_shape(prs.slides[i], "교독문번호") is not None), None)
    body = next(i for i in section_slides if find_shape(prs.slides[i], "교독문본문") is not None)
    pages = paginate_gyodokmun(g.lines, chars=chars_per_line(find_shape(prs.slides[body], "교독문본문")))
    targets = [body] + [slides.duplicate_slide(prs, body) for _ in pages[1:]]  # 채우기 전에 견본을 복제
    for idx, page in zip(targets, pages):
        s = prs.slides[idx]
        _set_text(find_shape(s, "교독문제목"), f"교독문 {g.number}번")
        _fill_body(find_shape(s, "교독문본문"), page)
    if cover is None:
        return targets
    _set_text(find_shape(prs.slides[cover], "교독문번호"), f"교독문 {g.number}번")
    sub = find_shape(prs.slides[cover], "교독문부제")
    if sub is not None:
        _set_text(sub, g.title)
    return [cover] + targets


# ── 말씀구절 ──────────────────────────────────────────────

VERSE_MAX_CHARS = 110  # 초록잎들꽃 견본(HY견고딕 38.4pt, 약 7줄) 기준 한 장에 넣는 글자 수


def split_verse(number: int, text: str, max_chars: int = VERSE_MAX_CHARS) -> list:
    """한 절을 장 단위 조각으로. 조각 길이를 고르게 하고, 첫 조각만 절 번호, 낱말 중간에서 자르지 않는다."""
    full = f"{number} {text}"
    target = len(full) / math.ceil(len(full) / max_chars)
    words, parts, cur = text.split(), [], f"{number}"
    for w in words:
        if len(cur) + 1 + len(w) > target + 5 and cur not in (f"{number}", ""):
            parts.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}" if cur else w
    parts.append(cur)
    return parts


def fill_verses(prs, slide_index: int, passages: list, max_chars: int = VERSE_MAX_CHARS) -> list:
    """말씀구절 견본을 절(조각)마다 한 장씩 채운다. 견본 자신이 첫 장."""
    from sources import load_verses  # 순환 import 피함

    pieces = []
    for p in passages:
        unit = "편" if p.book == "시편" else "장"
        for number, text in load_verses(p):
            for piece in split_verse(number, text, max_chars):
                pieces.append((f"{p.book} {p.chapter}{unit}", piece))
    targets = [slide_index] + [slides.duplicate_slide(prs, slide_index) for _ in pieces[1:]]
    for idx, (chapter, piece) in zip(targets, pieces):
        s = prs.slides[idx]
        _set_text(find_shape(s, "구절장"), chapter)
        _set_text(find_shape(s, "구절본문"), piece)
    return targets
