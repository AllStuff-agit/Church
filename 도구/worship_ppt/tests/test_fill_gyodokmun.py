import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from pptx import Presentation

from fill import chars_per_line, fill_gyodokmun, paginate_gyodokmun, split_tail
from fixtures import LABEL, LEADER, PEOPLE, REF, make_mini_theme
from sources import Gyodokmun, load_gyodokmun
from theme import find_shape, kind_slides


def _color(run):
    return str(run.font.color.rgb)


class PaginateTest(unittest.TestCase):
    def test_pairs_not_split(self):
        lines = load_gyodokmun(9).lines  # 12줄 = 6쌍
        pages = paginate_gyodokmun(lines)
        self.assertGreaterEqual(len(pages), 2)
        for page in pages:
            self.assertEqual(page[0][0], "인도")
            self.assertLessEqual(len([l for l in page if l[0] == "인도"]), 3)
        self.assertEqual([l for p in pages for l in p], lines)

    def test_long_lines_kept(self):
        long = "가" * 120
        lines = [("인도", long), ("회중", long), ("인도", long), ("회중", long)]
        pages = paginate_gyodokmun(lines)
        self.assertGreaterEqual(len(pages), 2)
        self.assertEqual([l for p in pages for l in p], lines)

    def test_narrow_box_more_pages(self):
        lines = load_gyodokmun(21).lines
        wide = paginate_gyodokmun(lines, chars={"인도": 40, "회중": 35, "다같이": 35})
        narrow = paginate_gyodokmun(lines, chars={"인도": 12, "회중": 10, "다같이": 10})
        self.assertGreater(len(narrow), len(wide))

    def test_overflow_warns(self):
        long = "가" * 400
        with self.assertWarnsRegex(UserWarning, "넘칩니다"):
            paginate_gyodokmun([("인도", long), ("회중", "짧은 줄")])

    def test_split_tail(self):
        self.assertEqual(split_tail("망하리로다 (1-6) (아멘)"), ("망하리로다", "(1-6) (아멘)"))
        self.assertEqual(split_tail("경외할지어다 (시33:8)"), ("경외할지어다", "(시33:8)"))
        self.assertEqual(split_tail("오만한 자들의 자리에 앉지 아니하고"), ("오만한 자들의 자리에 앉지 아니하고", ""))


class FillTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.prs = Presentation(make_mini_theme(Path(self.tmp.name) / "t.pptx"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_fill_9(self):
        g = load_gyodokmun(9)
        out = fill_gyodokmun(self.prs, kind_slides(self.prs)["교독문"], g)
        cover, pages = out[0], out[1:]
        self.assertEqual(find_shape(self.prs.slides[cover], "교독문번호").text_frame.text, "교독문 9번")
        self.assertEqual(find_shape(self.prs.slides[cover], "교독문부제").text_frame.text, "시편 15편")
        first = self.prs.slides[pages[0]]
        self.assertEqual(find_shape(first, "교독문제목").text_frame.text, "교독문 9번")
        paras = find_shape(first, "교독문본문").text_frame.paragraphs
        self.assertEqual(paras[0].runs[0].text, g.lines[0][1])
        self.assertEqual(_color(paras[0].runs[0]), LEADER)
        self.assertEqual(_color(paras[1].runs[0]), PEOPLE)
        last = find_shape(self.prs.slides[pages[-1]], "교독문본문").text_frame.paragraphs[-1]
        self.assertEqual(last.runs[-1].text, " (1-5) (아멘)")
        self.assertEqual(_color(last.runs[-1]), REF)

    def test_fill_together(self):
        g = load_gyodokmun(1)  # 마지막 줄 다같이
        out = fill_gyodokmun(self.prs, kind_slides(self.prs)["교독문"], g)
        paras = find_shape(self.prs.slides[out[-1]], "교독문본문").text_frame.paragraphs
        self.assertEqual(paras[-2].text, "(다같이)")
        self.assertEqual(_color(paras[-2].runs[0]), LABEL)
        self.assertTrue(paras[-1].runs[0].text.startswith("무릇 의인들의 길은"))

    def test_no_cover(self):
        prs = Presentation(make_mini_theme(Path(self.tmp.name) / "n.pptx", cover=False))
        out = fill_gyodokmun(prs, kind_slides(prs)["교독문"], load_gyodokmun(9))
        self.assertIsNotNone(find_shape(prs.slides[out[0]], "교독문본문"))

    def test_chars_from_box(self):
        body = find_shape(self.prs.slides[kind_slides(self.prs)["교독문"][1]], "교독문본문")
        c = chars_per_line(body)
        self.assertGreater(c["인도"], c["회중"])  # 인도 글자가 더 작으니 한 줄에 더 많이

    def test_all_text_present(self):
        g = load_gyodokmun(9)
        out = fill_gyodokmun(self.prs, kind_slides(self.prs)["교독문"], g)
        text = "".join(find_shape(self.prs.slides[i], "교독문본문").text_frame.text for i in out[1:])
        for _, line in g.lines:
            self.assertIn(split_tail(line)[0], text)


if __name__ == "__main__":
    unittest.main()
