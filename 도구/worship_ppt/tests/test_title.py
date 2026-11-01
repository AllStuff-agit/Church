import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from pptx import Presentation

from sources import REPO
from theme import find_shape, kind_slides
from title import BASE, fill_cover, layout, parse_title

THEME = REPO / "2_템플릿/테마/테마-초록잎들꽃.pptx"


class ParseTest(unittest.TestCase):
    def test_markers(self):
        g = parse_title("하나님(을) [대장] 삼으라")
        self.assertEqual("".join(x.char for x in g), "하나님을대장삼으라")
        scale = {x.char: x.scale for x in g}
        self.assertEqual(scale["을"], 0.77)
        self.assertEqual(scale["대"], 0.95)
        self.assertEqual(scale["장"], 0.95)
        self.assertEqual(scale["하"], 1.0)
        self.assertEqual([x.word for x in g], [0, 0, 0, 0, 1, 1, 2, 2, 2])

    def test_auto_particle(self):
        g = parse_title("하나님을 대장 삼으라")
        self.assertEqual(g[3].char, "을")
        self.assertEqual(g[3].scale, 0.77)
        self.assertGreater(g[3].dy, 0)


class LayoutTest(unittest.TestCase):
    def test_centered(self):
        rects = layout(parse_title("하나님(을) [대장] 삼으라"), BASE)
        left, right = rects[0][0], rects[-1][0] + rects[-1][2]
        center = (BASE["box_left"] + BASE["box_right"]) / 2
        self.assertLess(abs((left + right) / 2 - center), (BASE["box_right"] - BASE["box_left"]) * 0.01)

    def test_long_title_fits(self):
        title = "주께서 우리를 향하신 크고 놀라운 사랑으로 모든 민족을 부르시는 하나님"
        glyphs = parse_title(title)
        rects = layout(glyphs, BASE)
        for x, y, w, h, _ in rects:
            self.assertGreaterEqual(x, BASE["box_left"])
            self.assertLessEqual(x + w, BASE["box_right"])
        tops = sorted({round(r[1], -5) for r in rects})
        if len(tops) > 1:  # 두 줄이면 줄바꿈은 낱말 경계
            first_line = [g for g, r in zip(glyphs, rects) if r[1] < (rects[0][1] + rects[-1][1]) / 2]
            next_g = glyphs[len(first_line)]
            self.assertNotEqual(first_line[-1].word, next_g.word)


class QuoteTest(unittest.TestCase):
    def test_quotes_wrap_two_lines(self):
        prs = Presentation(str(THEME))
        idx = kind_slides(prs)["본문표지"][0]
        fill_cover(prs, idx, "시편 23편 1-6절", "여호와는 나의 목자시니 내게 부족함이 없으리로다")
        group = find_shape(prs.slides[idx], "본문 타이틀")
        letters = [sh for sh in group.shapes if sh.name.startswith("설교제목글자")]
        left = min(sh.left for sh in letters)
        right = max(sh.left + sh.width for sh in letters)
        lq, rq = find_shape(group, "따옴표-left"), find_shape(group, "따옴표-right")
        self.assertLessEqual(lq.left + lq.width, left)
        self.assertGreaterEqual(rq.left, right)


class FillCoverTest(unittest.TestCase):
    def test_fill(self):
        prs = Presentation(str(THEME))
        idx = kind_slides(prs)["본문표지"][0]
        fill_cover(prs, idx, "사무엘하 21장 1-14절", "공동체를 회복시키시는 하나님")
        s = prs.slides[idx]
        self.assertEqual(find_shape(s, "성경구절").text_frame.text, "사무엘하 21장 1-14절")
        group = find_shape(s, "본문 타이틀")
        letters = [sh for sh in group.shapes if sh.name.startswith("설교제목글자")]
        self.assertEqual("".join(sh.text_frame.text for sh in letters), "공동체를회복시키시는하나님")
        targets = {e.get("spid") for e in s._element.iter("{http://schemas.openxmlformats.org/presentationml/2006/main}spTgt")}
        self.assertIn(str(group.shape_id), targets)  # 애니메이션 대상 유지
        ids = [sh.shape_id for sh in group.shapes]
        self.assertEqual(len(ids), len(set(ids)))


if __name__ == "__main__":
    unittest.main()
